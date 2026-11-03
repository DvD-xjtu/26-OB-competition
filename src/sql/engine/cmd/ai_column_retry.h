#pragma once

#include "common/mysqlclient/ob_mysql_transaction.h"
#include "common/mysqlclient/ob_mysql_result.h"
#include "share/ai_column/ai_column_definition.h"
#include "query/session/ob_inner_sql_connection_access.h"
#include "share/schema/ob_schema_getter_guard.h"
#include "share/schema/ob_multi_version_schema_service.h"
#include "sql/engine/ob_exec_context.h"
#include "sql/engine/cmd/ai_column_retry_predicate.h"
#include "sql/engine/ob_physical_plan_ctx.h"
#include "sql/engine/expr/ob_expr_uuid_short.h"
#include "sql/resolver/ddl/ob_alter_table_stmt.h"
#include "sql/session/ob_sql_session_info.h"
#include <cctype>
#include <string>
#include <vector>

namespace oceanbase { namespace sql {

// RETRY is a native, data-only ALTER action. It locks the selected business
// rows, invalidates the physical columns (and their indexes), and enqueues the
// corresponding snapshots in one transaction. It never calls a model inline.
class AiColumnRetry
{
  using Definition = share::AiColumnDefinition;
  using Column = share::schema::ObColumnSchemaV2;
  using Table = share::schema::ObTableSchema;
  struct Snapshot {
    std::string key, input, config;
    bool input_null = false, config_null = false;
  };
  static std::string text(const common::ObString &s)
  { return s.empty() ? std::string() : std::string(s.ptr(), s.length()); }
  static std::string ident(const common::ObString &s)
  {
    std::string out("`");
    for (int64_t i = 0; i < s.length(); ++i) {
      out += s.ptr()[i]; if (s.ptr()[i] == '`') { out += '`'; }
    }
    return out + '`';
  }
  static std::string literal(const std::string &s)
  {
    static const char hex[] = "0123456789abcdef";
    std::string out("CONVERT(X'");
    for (unsigned char c : s) { out += hex[c >> 4]; out += hex[c & 15]; }
    return out + "' USING utf8mb4)";
  }
  static int read_string(common::sqlclient::ObMySQLResult &row, const char *name,
                         std::string &out, bool &is_null)
  {
    common::ObObj obj;
    int ret = row.get_obj(name, obj);
    if (ret == common::OB_SUCCESS) {
      is_null = obj.is_null();
      if (!is_null) { out = text(obj.get_string()); }
    }
    return ret;
  }
  static int collect(common::ObMySQLTransaction &tx, ObExecContext &ctx,
                     const Table &table, const Definition &def,
                     const std::string &qualified, const std::string &condition,
                     std::vector<Snapshot> &snapshots)
  {
    int ret = common::OB_SUCCESS;
    const common::ObRowkeyInfo &keys = table.get_rowkey_info();
    std::string query("SELECT ");
    std::vector<std::string> key_names;
    for (int64_t i = 0; OB_SUCC(ret) && i < keys.get_size(); ++i) {
      uint64_t id = 0;
      const Column *column = nullptr;
      if (OB_FAIL(keys.get_column_id(i, id))) {
      } else if (OB_ISNULL(column = table.get_column_schema(id))) {
        ret = common::OB_ERR_UNEXPECTED;
      } else {
        key_names.push_back(ident(column->get_column_name_str()));
        query += key_names.back() + ',';
      }
    }
    if (OB_SUCC(ret) && key_names.empty()) { ret = common::OB_NOT_SUPPORTED; }
    query += "CAST((" + def.input_expr + ") AS CHAR CHARACTER SET utf8mb4) AS __ai_input,"
        + (def.config_expr.empty() ? std::string("NULL")
           : "CAST((" + def.config_expr + ") AS CHAR CHARACTER SET utf8mb4)")
        + " AS __ai_config FROM " + qualified + " WHERE " + condition + " FOR UPDATE";
    common::ObISQLClient::ReadResult result;
    common::sqlclient::ObMySQLResult *rows = nullptr;
    if (OB_FAIL(ret)) {
    } else if (OB_FAIL(tx.read(result, query.c_str()))) {
    } else if (OB_ISNULL(rows = result.get_result())) { ret = common::OB_ERR_UNEXPECTED; }
    common::ObObjPrintParams params = ctx.get_my_session()->create_obj_print_params();
    params.need_cast_expr_ = true;
    GET_SQL_MODE_BIT(IS_NO_BACKSLASH_ESCAPES, ctx.get_my_session()->get_sql_mode(), params.skip_escape_);
    while (OB_SUCC(ret) && OB_SUCC(ret = rows->next())) {
      Snapshot value;
      common::ObArenaAllocator allocator("AiRetryRow");
      for (size_t i = 0; OB_SUCC(ret) && i < key_names.size(); ++i) {
        common::ObObj obj;
        char *buffer = nullptr;
        int64_t length = 0, pos = 0;
        if (OB_FAIL(rows->get_obj(static_cast<int64_t>(i), obj,
                                 ctx.get_my_session()->get_timezone_info(), &allocator))) {
        } else {
          std::string key_value;
          if (obj.is_string_type() || obj.get_type() == common::ObORawType) {
            static const char digits[] = "0123456789abcdef";
            key_value = "X'";
            const common::ObString bytes = obj.get_string();
            for (int64_t n=0; n<bytes.length(); ++n) {
              const unsigned char c = bytes.ptr()[n];
              key_value += digits[c >> 4]; key_value += digits[c & 15];
            }
            key_value += '\'';
          } else if (OB_FAIL(obj.print_sql_literal(buffer, length, pos, allocator, params))) { }
          else { key_value.assign(buffer, pos); }
          if (OB_SUCC(ret)) {
            if (i != 0) { value.key += " AND "; }
            value.key += key_names[i] + " = " + key_value;
          }
        }
      }
      if (OB_SUCC(ret) && value.key.size() > 2048) { ret = common::OB_SIZE_OVERFLOW; }
      if (OB_FAIL(ret)) {
      } else if (OB_FAIL(read_string(*rows, "__ai_input", value.input, value.input_null))) {
      } else if (OB_FAIL(read_string(*rows, "__ai_config", value.config, value.config_null))) {
      } else { snapshots.push_back(std::move(value)); }
    }
    if (ret == common::OB_ITER_END) { ret = common::OB_SUCCESS; }
    return ret;
  }
public:
  static int execute(ObExecContext &ctx, ObAlterTableStmt &stmt)
  {
    int ret = common::OB_SUCCESS;
    const Table *table = nullptr;
    const Column *column = nullptr;
    const Column *state = nullptr, *request = nullptr, *spec = nullptr;
    const share::schema::ObDatabaseSchema *db = nullptr;
    Definition def;
    share::schema::ObSchemaGetterGuard guard;
    if (GCTX.schema_service_ == nullptr || ctx.get_my_session() == nullptr || ctx.get_sql_proxy() == nullptr) {
      ret = common::OB_ERR_UNEXPECTED;
    } else if (OB_FAIL(GCTX.schema_service_->get_runtime_schema_guard(guard))) {
    } else if (OB_FAIL(guard.get_table_schema(
                         stmt.get_alter_table_schema().get_table_id(), table))) {
    } else if (table == nullptr
               || (column = table->get_column_schema(stmt.get_retry_ai_column_name())) == nullptr
               || !column->is_ai_column()) { ret = common::OB_SCHEMA_ERROR;
    } else if (OB_FAIL(def.parse(column->get_ai_column_info()))) {
    } else if ((state = table->get_column_schema(def.state_column_id)) == nullptr
               || (request = table->get_column_schema(def.request_column_id)) == nullptr
               || (spec = table->get_column_schema(def.result_spec_column_id)) == nullptr) {
      ret = common::OB_SCHEMA_ERROR;
    } else if (OB_FAIL(guard.get_database_schema(table->get_database_id(), db))) {
    } else if (db == nullptr) { ret = common::OB_SCHEMA_ERROR; }
    if (OB_SUCC(ret)) {
      const std::string qualified = ident(db->get_database_name_str()) + '.' + ident(table->get_table_name_str());
      bool no_backslash_escapes = false;
      GET_SQL_MODE_BIT(IS_NO_BACKSLASH_ESCAPES, ctx.get_my_session()->get_sql_mode(), no_backslash_escapes);
      const std::string where = AiColumnRetryPredicate::rewrite(text(stmt.get_retry_ai_column_predicate()),
                                          ident(state->get_column_name_str()), no_backslash_escapes);
      common::ObMySQLTransaction tx;
      std::vector<Snapshot> snapshots;
      ObSQLSessionInfo *inner = nullptr;
      common::ObTimeZoneInfoWrap old_tz;
      ObSQLMode old_mode = 0;
      bool restore_environment = false;
      if (OB_FAIL(tx.start(ctx.get_sql_proxy(), true))) {
        LOG_INFO("AI retry transaction start failed", K(ret));
      } else if (OB_ISNULL(inner = query::ObInnerSQLConnectionAccess::get_session(tx.get_connection()))) {
        ret = common::OB_ERR_UNEXPECTED;
      } else if (OB_FAIL(old_tz.deep_copy(inner->get_tz_info_wrap()))) {
      } else {
        old_mode = inner->get_sql_mode();
        restore_environment = true;
        if (OB_FAIL(tx.get_connection()->set_session_variable(common::ObString::make_string("sql_mode"),
                          static_cast<int64_t>(ctx.get_my_session()->get_sql_mode())))) {
        } else if (OB_FAIL(tx.get_connection()->set_tz_info_wrap(ctx.get_my_session()->get_tz_info_wrap()))) {
        } else { ret = collect(tx, ctx, *table, def, qualified, where, snapshots);
          if (OB_FAIL(ret)) { LOG_INFO("AI retry collect failed", K(ret)); }
        }
      }
      for (size_t i = 0; OB_SUCC(ret) && i < snapshots.size(); ++i) {
        const Snapshot &row = snapshots[i];
        const std::string request_id = std::to_string(ObExprUuidShort::generate_uuid_short());
        const std::string input = row.input_null ? "NULL" : literal(row.input);
        const std::string config = row.config_null ? "NULL" : literal(row.config);
        rapidjson::StringBuffer buffer;
        rapidjson::Writer<rapidjson::StringBuffer> json(buffer);
        json.StartObject(); json.Key("input");
        if (row.input_null) { json.Null(); } else { json.String(row.input.data(), row.input.size()); }
        json.Key("config");
        if (row.config_null) { json.Null(); } else { json.String(row.config.data(), row.config.size()); }
        json.EndObject();
        const std::string snapshot(buffer.GetString(), buffer.GetSize());
        const std::string update = "UPDATE " + qualified + " SET " + ident(column->get_column_name_str())
            + "=NULL," + ident(state->get_column_name_str()) + "=0,"
            + ident(request->get_column_name_str()) + '=' + literal(request_id) + ','
            + ident(spec->get_column_name_str()) + '=' + literal(snapshot) + " WHERE " + row.key;
        int64_t affected = 0;
        if (OB_FAIL(tx.write(update.c_str(), affected))) {
          LOG_INFO("AI retry update failed", K(ret));
        } else if (affected != 1) { ret = common::OB_ERR_UNEXPECTED; }
        const std::string insert = "INSERT INTO oceanbase.__all_ai_column_task "
            "(table_id,column_id,rowkey_predicate,request_id,definition_version,model_name,input_text,"
            "result_type,dimension,max_retries,retry_count,state,eligible_ts,lease_owner,lease_expires,"
            "result,last_error,system_prompt,config) VALUES ("
            + std::to_string(table->get_table_id()) + ',' + std::to_string(column->get_column_id()) + ','
            + literal(row.key) + ',' + literal(request_id) + ',' + std::to_string(def.definition_version)
            + ',' + literal(def.model_name) + ',' + input + ',' + literal(def.result_type) + ','
            + std::to_string(def.dimension) + ',' + std::to_string(def.max_retries)
            + ",0,0,NOW(6),'',NULL,NULL,0," + literal(def.system_prompt) + ',' + config
            + ") ON DUPLICATE KEY UPDATE request_id=VALUES(request_id),"
            "definition_version=VALUES(definition_version),model_name=VALUES(model_name),"
            "input_text=VALUES(input_text),result_type=VALUES(result_type),dimension=VALUES(dimension),"
            "max_retries=VALUES(max_retries),retry_count=0,state=0,eligible_ts=NOW(6),lease_owner='',"
            "lease_expires=NULL,result=NULL,last_error=0,system_prompt=VALUES(system_prompt),config=VALUES(config)";
        if (OB_SUCC(ret)) { ret = tx.write(insert.c_str(), affected); }
      }
      if (OB_FAIL(ret)) { LOG_INFO("AI retry prior restore failed", K(ret)); }
      if (restore_environment) {
        const int mode_ret = tx.get_connection()->set_session_variable(
            common::ObString::make_string("sql_mode"), static_cast<int64_t>(old_mode));
        const int tz_ret = tx.get_connection()->set_tz_info_wrap(old_tz);
        if (OB_SUCC(ret)) { ret = mode_ret == common::OB_SUCCESS ? tz_ret : mode_ret; }
      }
      if (tx.is_started()) {
        const int end_ret = tx.end(ret == common::OB_SUCCESS);
        if (OB_SUCC(ret)) { ret = end_ret; }
      }
      if (OB_SUCC(ret) && ctx.get_physical_plan_ctx() != nullptr) {
        ctx.get_physical_plan_ctx()->set_affected_rows(snapshots.size());
      }
    }
    return ret;
  }
};
} }
