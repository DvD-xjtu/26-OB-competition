/* Copyright (c) 2026 OceanBase. Licensed under the Apache License, Version 2.0. */
#define USING_LOG_PREFIX SERVER_OMT
#include "observer/ai_service/ai_column_worker.h"
#include "common/mysqlclient/ob_mysql_proxy.h"
#include "common/mysqlclient/ob_mysql_transaction.h"
#include "common/mysqlclient/ob_mysql_result.h"
#include "share/ob_server_struct.h"
#include "share/rc/ob_server_runtime.h"
#include "share/schema/ob_multi_version_schema_service.h"
#include "share/schema/ob_schema_getter_guard.h"
#include "share/ai_column/ai_column_definition.h"
#include "query/ai/ob_ai_endpoint_resolver.h"
#include "sql/engine/expr/ob_expr_ai/ob_ai_func_utils.h"
#include "lib/time/ob_time_utility.h"
#include <atomic>
#include <cmath>
#include <cstdlib>
#include <cerrno>
#include <limits>
#include <string>
#include <vector>
#include <curl/curl.h>
#include <rapidjson/document.h>

namespace oceanbase { namespace observer {
using namespace common;
namespace {
constexpr int64_t LEASE_SECONDS = 30;
constexpr int64_t MAX_RESPONSE_BYTES = 16 * 1024 * 1024;
std::atomic<uint64_t> owner_sequence{0};

std::string text(const ObString &s) { return std::string(s.ptr(), s.length()); }
ObString view(const std::string &s) { return ObString(static_cast<int32_t>(s.size()), s.data()); }
std::string identifier(const std::string &s)
{
  std::string out("`");
  for (char c : s) { out += c; if (c == '`') { out += '`'; } }
  return out + '`';
}
// Hex literals avoid session-dependent backslash escaping and embedded NULs.
std::string literal(const std::string &s)
{
  if (s.empty()) { return "''"; }
  static const char hex[] = "0123456789abcdef";
  std::string out("_utf8mb4 0x");
  out.reserve(out.size() + s.size() * 2);
  for (unsigned char c : s) { out += hex[c >> 4]; out += hex[c & 15]; }
  return out;
}
int string_field(sqlclient::ObMySQLResult &r, const char *name, std::string &s, bool *is_null = nullptr)
{
  ObString value;
  int ret = r.get_varchar(name, value);
  if (ret == OB_ERR_NULL_VALUE) {
    if (is_null != nullptr) { *is_null = true; }
    s.clear(); ret = OB_SUCCESS;
  } else if (ret == OB_SUCCESS) {
    if (is_null != nullptr) { *is_null = false; }
    s = text(value);
  }
  return ret;
}
struct Task {
  int64_t table_id = 0, column_id = 0, definition_version = 0;
  int64_t dimension = 0, max_retries = 0, retry_count = 0, state = 0;
  int64_t lease_valid = 0, eligible = 0;
  std::string lease_owner;
  std::string rowkey, request, model, input, result_type, config, system_prompt, result;
  bool input_null = false, result_null = false;
};
std::string group_where(const Task &t)
{
  return "table_id=" + std::to_string(t.table_id) + " AND rowkey_predicate="
      + literal(t.rowkey) + " AND request_id=" + literal(t.request);
}
std::string owned_where(const Task &t, const std::string &owner)
{
  return group_where(t) + " AND lease_owner=" + literal(owner) + " AND lease_expires>NOW(6)";
}
int write_sql(ObISQLClient &client, const std::string &sql, int64_t *count = nullptr)
{
  int64_t affected = 0;
  int ret = client.write(sql.c_str(), affected);
  if (count != nullptr) { *count = affected; }
  return ret;
}
int count_owned(const Task &group, const std::string &owner, int64_t &count)
{
  ObISQLClient::ReadResult result;
  const std::string sql = "SELECT COUNT(*) AS task_count FROM oceanbase.__all_ai_column_task WHERE "
      + owned_where(group, owner);
  int ret = GCTX.sql_proxy_->read(result, sql.c_str());
  auto *rows = result.get_result();
  if (ret == OB_SUCCESS && rows == nullptr) { ret = OB_ERR_UNEXPECTED; }
  if (ret == OB_SUCCESS && (ret = rows->next()) == OB_SUCCESS) { ret = rows->get_int("task_count", count); }
  return ret;
}
int end_transaction(ObMySQLTransaction &tx, int ret)
{
  if (tx.is_started()) {
    const int end_ret = tx.end(ret == OB_SUCCESS);
    if (ret == OB_SUCCESS) { ret = end_ret; }
  }
  return ret;
}
int load_tasks(ObISQLClient &client, const std::string &where, bool lock, std::vector<Task> &tasks)
{
  ObISQLClient::ReadResult result;
  const std::string sql = "SELECT table_id,column_id,rowkey_predicate,request_id,definition_version,"
      "model_name,input_text,result_type,dimension,max_retries,retry_count,state,config,system_prompt,result,lease_owner,"
      "(lease_expires IS NOT NULL AND lease_expires>NOW(6)) AS lease_valid,"
      "(eligible_ts IS NULL OR eligible_ts<=NOW(6)) AS eligible "
      "FROM oceanbase.__all_ai_column_task WHERE " + where + " ORDER BY column_id" + (lock ? " FOR UPDATE" : "");
  int ret = client.read(result, sql.c_str());
  sqlclient::ObMySQLResult *rows = result.get_result();
  if (ret == OB_SUCCESS && rows == nullptr) { ret = OB_ERR_UNEXPECTED; }
  while (ret == OB_SUCCESS && (ret = rows->next()) == OB_SUCCESS) {
    Task t;
    if ((ret = rows->get_int("table_id", t.table_id)) == OB_SUCCESS
        && (ret = rows->get_int("column_id", t.column_id)) == OB_SUCCESS
        && (ret = rows->get_int("definition_version", t.definition_version)) == OB_SUCCESS
        && (ret = rows->get_int("dimension", t.dimension)) == OB_SUCCESS
        && (ret = rows->get_int("max_retries", t.max_retries)) == OB_SUCCESS
        && (ret = rows->get_int("retry_count", t.retry_count)) == OB_SUCCESS
        && (ret = rows->get_int("state", t.state)) == OB_SUCCESS
        && (ret = rows->get_int("lease_valid", t.lease_valid)) == OB_SUCCESS
        && (ret = rows->get_int("eligible", t.eligible)) == OB_SUCCESS
        && (ret = string_field(*rows, "lease_owner", t.lease_owner)) == OB_SUCCESS
        && (ret = string_field(*rows, "rowkey_predicate", t.rowkey)) == OB_SUCCESS
        && (ret = string_field(*rows, "request_id", t.request)) == OB_SUCCESS
        && (ret = string_field(*rows, "model_name", t.model)) == OB_SUCCESS
        && (ret = string_field(*rows, "input_text", t.input, &t.input_null)) == OB_SUCCESS
        && (ret = string_field(*rows, "result_type", t.result_type)) == OB_SUCCESS
        && (ret = string_field(*rows, "config", t.config)) == OB_SUCCESS
        && (ret = string_field(*rows, "system_prompt", t.system_prompt)) == OB_SUCCESS
        && (ret = string_field(*rows, "result", t.result, &t.result_null)) == OB_SUCCESS) {
      tasks.push_back(std::move(t));
    }
  }
  if (ret == OB_ITER_END) { ret = OB_SUCCESS; }
  return ret;
}
size_t receive_body(char *bytes, size_t size, size_t count, void *data)
{
  auto &body = *static_cast<std::string *>(data);
  if (size != 0 && count > static_cast<size_t>(MAX_RESPONSE_BYTES) / size) { return 0; }
  const size_t length = size * count;
  if (body.size() + length > static_cast<size_t>(MAX_RESPONSE_BYTES)) { return 0; }
  body.append(bytes, length);
  return length;
}
// Exactly one HTTP attempt. Automatic retries belong to the durable task state,
// rather than being hidden inside a transport retry loop.
int send_once(const ObString &url, const ObArray<ObString> &headers,
              const ObString &body, std::string &response)
{
  int ret = OB_SUCCESS;
  CURL *handle = curl_easy_init();
  curl_slist *header_list = nullptr;
  std::string url_copy = text(url), body_copy = text(body);
  for (int64_t i = 0; ret == OB_SUCCESS && i < headers.count(); ++i) {
    std::string header = text(headers.at(i));
    curl_slist *next = curl_slist_append(header_list, header.c_str());
    if (next == nullptr) { ret = OB_ALLOCATE_MEMORY_FAILED; } else { header_list = next; }
  }
  if (handle == nullptr) { ret = OB_ALLOCATE_MEMORY_FAILED; }
  if (ret == OB_SUCCESS) {
    const auto set_option = [&](CURLoption option, auto value) {
      if (ret == OB_SUCCESS && curl_easy_setopt(handle, option, value) != CURLE_OK) { ret = OB_CURL_ERROR; }
    };
    set_option(CURLOPT_URL, url_copy.c_str());
    set_option(CURLOPT_HTTPHEADER, header_list);
    set_option(CURLOPT_POST, 1L);
    set_option(CURLOPT_POSTFIELDSIZE_LARGE, static_cast<curl_off_t>(body_copy.size()));
    set_option(CURLOPT_POSTFIELDS, body_copy.data());
    set_option(CURLOPT_NOSIGNAL, 1L);
    set_option(CURLOPT_CONNECTTIMEOUT_MS, 2000L);
    set_option(CURLOPT_TIMEOUT_MS, 10000L);
    set_option(CURLOPT_WRITEFUNCTION, receive_body);
    set_option(CURLOPT_WRITEDATA, &response);
    const CURLcode code = ret == OB_SUCCESS ? curl_easy_perform(handle) : CURLE_FAILED_INIT;
    long status = 0;
    if (code != CURLE_OK || curl_easy_getinfo(handle, CURLINFO_RESPONSE_CODE, &status) != CURLE_OK
        || status < 200 || status >= 300) { ret = OB_CURL_ERROR; }
  }
  if (handle != nullptr) { curl_easy_cleanup(handle); }
  curl_slist_free_all(header_list);
  return ret;
}
int invoke(Task &task)
{
  task.result_null = task.input_null;
  if (task.input_null) { return OB_SUCCESS; }
  ObArenaAllocator allocator(ObMemAttr("AiColInvoke"));
  ObAIFuncExprInfo *info = nullptr;
  share::ObAiModelEndpointInfo endpoint;
  auto *resolver = share::server_service<query::ObIAiEndpointResolver>();
  int ret = ObAIFuncUtils::get_ai_func_info(allocator, view(task.model), info);
  if (ret == OB_SUCCESS && (info == nullptr || resolver == nullptr)) { ret = OB_ERR_UNEXPECTED; }
  if (ret == OB_SUCCESS) { ret = resolver->resolve_by_model_name(view(task.model), allocator, endpoint, false); }
  ObJsonObject *config = nullptr, *body = nullptr;
  ObAIFuncIComplete *completion = nullptr;
  ObAIFuncIEmbed *embedding = nullptr;
  ObArray<ObString> headers;
  ObString key, request_model, input = view(task.input), system = view(task.system_prompt);
  if (ret == OB_SUCCESS) {
    request_model = endpoint.get_request_model_name().empty() ? info->model_ : endpoint.get_request_model_name();
    ret = endpoint.get_unencrypted_access_key(allocator, key);
  }
  if (ret == OB_SUCCESS && !task.config.empty()) {
    ObString config_text = view(task.config);
    ret = ObAIFuncJsonUtils::get_json_object_form_str(allocator, config_text, config);
  }
  if (ret == OB_SUCCESS && task.result_type == "vector") {
    ObArray<ObString> inputs;
    if (info->type_ != share::EndpointType::DENSE_EMBEDDING) { ret = OB_INVALID_ARGUMENT; }
    else if ((ret = ObAIFuncUtils::get_embed_provider(allocator, endpoint.get_provider(), embedding)) == OB_SUCCESS
             && (ret = embedding->get_header(allocator, key, headers)) == OB_SUCCESS
             && (ret = inputs.push_back(input)) == OB_SUCCESS) {
      if (config == nullptr) { ret = ObAIFuncJsonUtils::get_json_object(allocator, config); }
      ObJsonInt *dimensions = nullptr;
      if (ret == OB_SUCCESS && (ret = ObAIFuncJsonUtils::get_json_int(allocator, task.dimension, dimensions)) == OB_SUCCESS
          && (ret = config->add("dimensions", dimensions)) == OB_SUCCESS) {
        ret = embedding->get_body(allocator, request_model, inputs, config, body);
      }
    }
  } else if (ret == OB_SUCCESS) {
    if (info->type_ != share::EndpointType::COMPLETION) { ret = OB_INVALID_ARGUMENT; }
    else if ((ret = ObAIFuncUtils::get_complete_provider(allocator, endpoint.get_provider(), completion)) == OB_SUCCESS
             && (ret = completion->get_header(allocator, key, headers)) == OB_SUCCESS) {
      ret = completion->get_body(allocator, request_model, system, input, config, body);
    }
  }
  ObString body_text;
  std::string response;
  if (ret == OB_SUCCESS && (ret = ObAIFuncJsonUtils::print_json_to_str(allocator, body, body_text)) == OB_SUCCESS) {
    ret = send_once(endpoint.get_url(), headers, body_text, response);
  }
  ObIJsonBase *root = nullptr, *parsed = nullptr;
  if (ret == OB_SUCCESS) {
    ret = ObJsonBaseFactory::get_json_base(&allocator, view(response), ObJsonInType::JSON_TREE,
                                         ObJsonInType::JSON_TREE, root);
    if (ret == OB_SUCCESS && (root == nullptr || root->json_type() != ObJsonNodeType::J_OBJECT)) {
      ret = OB_INVALID_DATA;
    }
  }
  if (ret == OB_SUCCESS) {
    auto *object = static_cast<ObJsonObject *>(root);
    ret = embedding != nullptr ? embedding->parse_output(allocator, object, parsed)
                               : completion->parse_output(allocator, object, parsed);
  }
  if (ret == OB_SUCCESS && embedding != nullptr) {
    if (parsed == nullptr || parsed->json_type() != ObJsonNodeType::J_ARRAY || parsed->element_count() != 1) {
      ret = OB_INVALID_DATA;
    } else {
      ObIJsonBase *vector = static_cast<ObJsonArray *>(parsed)->get_value(0);
      ObString vector_text;
      if (vector == nullptr || vector->json_type() != ObJsonNodeType::J_ARRAY
          || vector->element_count() != task.dimension) { ret = OB_INVALID_DATA; }
      else if ((ret = ObAIFuncJsonUtils::print_json_to_str(allocator, vector, vector_text)) == OB_SUCCESS) {
        task.result = text(vector_text);
        rapidjson::Document check;
        check.Parse(task.result.data(), task.result.size());
        if (check.HasParseError() || !check.IsArray()) { ret = OB_INVALID_DATA; }
        else for (const auto &value : check.GetArray()) {
          if (!value.IsNumber() || !std::isfinite(value.GetDouble())
              || std::abs(value.GetDouble()) > std::numeric_limits<float>::max()) { ret = OB_INVALID_DATA; break; }
        }
      }
    }
  } else if (ret == OB_SUCCESS) {
    if (parsed == nullptr || parsed->json_type() != ObJsonNodeType::J_STRING) { ret = OB_INVALID_DATA; }
    else {
      task.result.assign(parsed->get_data(), parsed->get_data_length());
      if (task.result_type == "json") {
        rapidjson::Document check;
        check.Parse(task.result.data(), task.result.size());
        if (check.HasParseError()) { ret = OB_INVALID_DATA; }
      } else if (task.result_type == "integer") {
        const char *begin = task.result.c_str(); char *end = nullptr;
        errno = 0; (void)std::strtoll(begin, &end, 10);
        if (errno != 0 || begin == end || *end != '\0') { ret = OB_INVALID_DATA; }
      }
    }
  }
  return ret;
}

bool is_result_conversion_error(int ret)
{
  return ret == OB_DATA_OUT_OF_RANGE || ret == OB_ERR_WARN_DATA_OUT_OF_RANGE
      || ret == OB_ERR_DATA_TOO_LONG || ret == OB_ERR_TRUNCATED_WRONG_VALUE_FOR_FIELD
      || ret == OB_ERR_TRUNCATED_WRONG_VALUE || ret == OB_ERR_INVALID_JSON_TEXT
      || ret == OB_ERR_INVALID_JSON_TEXT_IN_PARAM || ret == OB_ERR_JSON_VALUE_TOO_BIG
      || ret == OB_ERR_NUMERIC_JSON_VALUE_OUT_OF_RANGE || ret == OB_ERR_INVALID_JSON_VALUE_FOR_CAST
      || ret == OB_ERR_INVALID_VECTOR_DIM;
}

int publish_group(const Task &group, const std::string &owner)
{
  int ret = OB_SUCCESS;
  ObMySQLTransaction tx;
  if (OB_FAIL(tx.start(GCTX.sql_proxy_))) { return ret; }
  std::vector<Task> tasks;
  if (OB_FAIL(load_tasks(tx, group_where(group), true, tasks))) {
  } else if (!tasks.empty()) {
    bool terminal = true;
    for (const Task &t : tasks) {
      if (t.lease_owner != owner || !t.lease_valid) { return end_transaction(tx, OB_EAGAIN); }
      terminal &= t.state == 2 || t.state == 4;
    }
    if (terminal) {
      share::schema::ObSchemaGetterGuard guard;
      const share::schema::ObTableSchema *table = nullptr;
      const share::schema::ObDatabaseSchema *database = nullptr;
      if (OB_FAIL(GCTX.schema_service_->get_runtime_schema_guard(guard))) {
      } else if (OB_FAIL(guard.get_table_schema(group.table_id, table))) {
      } else if (table != nullptr && OB_FAIL(guard.get_database_schema(table->get_database_id(), database))) {
      }
      std::vector<std::string> assignments, failed_assignments;
      std::string predicate = group.rowkey;
      bool current = table != nullptr && database != nullptr;
      for (const Task &t : tasks) {
        if (!current || ret != OB_SUCCESS) { break; }
        const auto *column = table->get_column_schema(t.column_id);
        share::AiColumnDefinition def;
        if (column == nullptr || !column->is_ai_column()) { current = false; break; }
        if (OB_FAIL(def.parse(column->get_ai_column_info()))) { break; }
        const auto *state = table->get_column_schema(def.state_column_id);
        const auto *request = table->get_column_schema(def.request_column_id);
        if (state == nullptr || request == nullptr || def.definition_version != t.definition_version) {
          current = false; break;
        }
        const std::string result_column = identifier(text(column->get_column_name_str()));
        const std::string state_column = identifier(text(state->get_column_name_str()));
        assignments.push_back(result_column + '='
            + (t.state == 4 || t.result_null ? "NULL" : literal(t.result))
            + ',' + state_column + '=' + (t.state == 4 ? "2" : "1"));
        failed_assignments.push_back(result_column + "=NULL," + state_column + "=2");
        predicate += " AND " + identifier(text(request->get_column_name_str())) + '=' + literal(t.request);
      }
      if (ret == OB_SUCCESS && current && !assignments.empty()) {
        const std::string prefix = "UPDATE " + identifier(text(database->get_database_name_str())) + '.'
            + identifier(text(table->get_table_name_str())) + " SET ";
        // Separate statements isolate a target-column conversion failure. They
        // still share this locked transaction and become visible in one commit.
        for (size_t i = 0; ret == OB_SUCCESS && i < assignments.size(); ++i) {
          ret = write_sql(tx, prefix + assignments[i] + " WHERE " + predicate);
          if (is_result_conversion_error(ret)) {
            // A conversion error rolls back only its statement. The SQL proxy
            // intentionally latches errors; clear that latch before publishing
            // FAILED for this column, without discarding its successful peers.
            tx.reset_last_error();
            ret = write_sql(tx, prefix + failed_assignments[i] + " WHERE " + predicate);
          }
        }
      }
      if (ret == OB_SUCCESS) {
        ret = write_sql(tx, "DELETE FROM oceanbase.__all_ai_column_task WHERE " + owned_where(group, owner));
      }
    } else {
      ret = write_sql(tx, "UPDATE oceanbase.__all_ai_column_task SET lease_owner='',lease_expires=NULL WHERE "
                           + owned_where(group, owner));
    }
  }
  return end_transaction(tx, ret);
}
} // namespace

int AiColumnWorker::init()
{
  set_run_wrapper(share::server_runtime());
  return OB_SUCCESS;
}
void AiColumnWorker::run1()
{
  while (!has_set_stop()) {
    bool worked = false;
    const int ret = run_once(worked);
    if (ret != OB_SUCCESS || !worked) { ob_usleep(100000); }
  }
}
int AiColumnWorker::run_once(bool &worked)
{
  int ret = OB_SUCCESS;
  worked = false;
  if (GCTX.schema_service_ == nullptr || GCTX.sql_proxy_ == nullptr) { return OB_NOT_INIT; }
  Task group;
  {
    ObISQLClient::ReadResult result;
    const char *sql = "SELECT q.table_id,q.column_id,q.rowkey_predicate,q.request_id "
        "FROM oceanbase.__all_ai_column_task q "
        "WHERE (q.lease_expires IS NULL OR q.lease_expires<=NOW(6)) "
        "AND (q.eligible_ts IS NULL OR q.eligible_ts<=NOW(6)) "
        "AND NOT EXISTS (SELECT 1 FROM oceanbase.__all_ai_column_task x "
        "WHERE x.table_id=q.table_id AND x.rowkey_predicate=q.rowkey_predicate AND x.request_id=q.request_id "
        "AND (x.lease_expires>NOW(6) OR (x.state NOT IN (2,4) AND x.eligible_ts>NOW(6)))) "
        "ORDER BY q.eligible_ts,q.table_id,q.column_id LIMIT 1";
    if (OB_FAIL(GCTX.sql_proxy_->read(result, sql))) { return ret; }
    auto *rows = result.get_result();
    if (rows == nullptr) { return OB_ERR_UNEXPECTED; }
    if ((ret = rows->next()) == OB_ITER_END) { return OB_SUCCESS; }
    if (ret != OB_SUCCESS) { return ret; }
    if (OB_FAIL(rows->get_int("table_id", group.table_id))) {
    } else if (OB_FAIL(rows->get_int("column_id", group.column_id))) {
    } else if (OB_FAIL(string_field(*rows, "rowkey_predicate", group.rowkey))) {
    } else if (OB_FAIL(string_field(*rows, "request_id", group.request))) {}
  }
  if (ret != OB_SUCCESS) { return ret; }
  std::string owner = std::to_string(ObTimeUtility::current_time()) + ':' + std::to_string(++owner_sequence);
  std::vector<Task> tasks;
  {
    ObMySQLTransaction tx;
    if (OB_FAIL(tx.start(GCTX.sql_proxy_))) { return ret; }
    if (OB_FAIL(load_tasks(tx, group_where(group), true, tasks))) {
    } else if (!tasks.empty()) {
      // Recheck under the group row locks: the initial selection is only a hint.
      for (const Task &t : tasks) {
        if (t.lease_valid || (!t.eligible && t.state != 2 && t.state != 4)) { ret = OB_EAGAIN; break; }
      }
      int64_t affected = 0;
      const std::string sql = "UPDATE oceanbase.__all_ai_column_task SET lease_owner=" + literal(owner)
          + ",lease_expires=DATE_ADD(NOW(6),INTERVAL " + std::to_string(LEASE_SECONDS) + " SECOND) WHERE "
          + group_where(group) + " AND (lease_expires IS NULL OR lease_expires<=NOW(6))";
      if (ret == OB_SUCCESS && OB_FAIL(write_sql(tx, sql, &affected))) {
      } else if (ret == OB_SUCCESS && affected != static_cast<int64_t>(tasks.size())) { ret = OB_EAGAIN; }
    }
    ret = end_transaction(tx, ret);
  }
  if (ret != OB_SUCCESS || tasks.empty()) { return ret; }
  worked = true;
  for (Task &task : tasks) {
    if (has_set_stop()) { return OB_CANCELED; }
    if (task.state == 2 || task.state == 4) { continue; }
    // Renew the entire group before each external call, including already staged
    // results. A multi-column group may take longer than one lease in total.
    int64_t affected = 0;
    const std::string one = owned_where(task, owner) + " AND column_id=" + std::to_string(task.column_id);
    if (OB_FAIL(write_sql(*GCTX.sql_proxy_, "UPDATE oceanbase.__all_ai_column_task SET lease_expires=DATE_ADD(NOW(6),INTERVAL "
            + std::to_string(LEASE_SECONDS) + " SECOND) WHERE " + owned_where(group, owner), &affected))) { return ret; }
    // UPDATE counts changed rows; renewing within the same clock tick may
    // legitimately change none, so verify ownership with a matching-row count.
    if (OB_FAIL(count_owned(group, owner, affected))) { return ret; }
    if (affected != static_cast<int64_t>(tasks.size())) { return OB_SUCCESS; }
    if (OB_FAIL(write_sql(*GCTX.sql_proxy_, "UPDATE oceanbase.__all_ai_column_task SET state=1 WHERE "
        + one, &affected))) { return ret; }
    const int call_ret = invoke(task);
    std::string update;
    if (call_ret == OB_SUCCESS) {
      update = "state=2,result=" + (task.result_null ? "NULL" : literal(task.result)) + ",last_error=0";
    } else if (task.retry_count < task.max_retries) {
      update = "state=3,retry_count=retry_count+1,last_error=" + std::to_string(call_ret)
          + ",eligible_ts=DATE_ADD(NOW(6),INTERVAL 1 SECOND)";
    } else { update = "state=4,result=NULL,last_error=" + std::to_string(call_ret); }
    if (OB_FAIL(write_sql(*GCTX.sql_proxy_, "UPDATE oceanbase.__all_ai_column_task SET " + update + " WHERE " + one))) { return ret; }
  }
  return publish_group(group, owner);
}
} } // namespace oceanbase::observer
