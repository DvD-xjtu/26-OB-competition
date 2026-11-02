#pragma once

#include "share/ai_column/ai_column_definition.h"
#include "sql/engine/dml/ob_table_modify_op.h"
#include "sql/engine/expr/ob_expr_uuid_short.h"
#include "sql/engine/expr/ob_expr_lob_utils.h"
#include "share/schema/ob_schema_getter_guard.h"
#include "sql/engine/expr/ob_expr_ai/ob_ai_func_utils.h"

namespace oceanbase { namespace sql {

// AI columns use the same physical DML and index maintenance as ordinary
// columns. Only metadata task writes recurse through the session's inner SQL
// connection, so their commit/rollback boundary is the business transaction.
class AiColumnDml
{
  using Definition = share::AiColumnDefinition;
  using Column = share::schema::ObColumnSchemaV2;
  using Table = share::schema::ObTableSchema;
  static std::string ident(const common::ObString &name)
  {
    std::string out("`");
    for (int64_t i = 0; i < name.length(); ++i) {
      if (name.ptr()[i] == '`') { out += '`'; }
      out += name.ptr()[i];
    }
    return out + '`';
  }
  static std::string quoted(const std::string &text)
  {
    static const char hex[] = "0123456789abcdef";
    std::string out("CONVERT(X'");
    for (unsigned char ch : text) { out += hex[ch >> 4]; out += hex[ch & 15]; }
    return out + "' USING utf8mb4)";
  }
  static int index(const ObDMLBaseCtDef &ctdef, uint64_t id)
  {
    for (int64_t i = 0; i < ctdef.column_ids_.count(); ++i) {
      if (ctdef.column_ids_.at(i) == id) { return static_cast<int>(i); }
    }
    return -1;
  }
  static int literal(ObTableModifyOp &op, const ObExprPtrIArray &row,
                     int64_t idx, std::string &out, bool key_literal = false)
  {
    int ret = common::OB_SUCCESS;
    common::ObDatum *datum = nullptr;
    common::ObObj value;
    char *buf = nullptr;
    int64_t length = 0, pos = 0;
    if (idx < 0 || idx >= row.count() || row.at(idx) == nullptr) {
      ret = common::OB_ERR_UNEXPECTED;
    } else if (OB_FAIL(row.at(idx)->eval(op.get_eval_ctx(), datum))) {
    } else if (OB_FAIL(datum->to_obj(value, row.at(idx)->obj_meta_))) {
    } else if (key_literal && !value.is_null() && value.is_string_type()) {
      // Persist mode-independent key predicates; workers may use a different
      // SQL mode than the transaction that created the task.
      static const char hex[] = "0123456789abcdef";
      const common::ObString data = value.get_string();
      out = "X'";
      for (int64_t i = 0; i < data.length(); ++i) {
        const unsigned char ch = static_cast<unsigned char>(data.ptr()[i]);
        out += hex[ch >> 4]; out += hex[ch & 15];
      }
      out += '\'';
    } else if (!value.is_null() && (value.is_string_type() || value.is_json())) {
      // Object SQL printers are diagnostic helpers: text printers can truncate
      // to their current buffer, and cannot fetch an out-of-row LOB themselves.
      // Resolve the complete value using the business transaction first.
      common::ObString data = datum->get_string();
      if (OB_FAIL(ObTextStringHelper::read_real_string_data(op.get_exec_ctx(),
                      &op.get_exec_ctx().get_allocator(), value.get_type(), value.get_collation_type(),
                      row.at(idx)->obj_meta_.has_lob_header(), data))) {
      } else if (value.is_json()) {
        common::ObIJsonBase *json = nullptr;
        common::ObJsonBuffer buffer(&op.get_exec_ctx().get_allocator());
        if (OB_FAIL(common::ObJsonBaseFactory::get_json_base(&op.get_exec_ctx().get_allocator(), data,
                        common::ObJsonInType::JSON_BIN, common::ObJsonInType::JSON_BIN, json, 0))) {
        } else if (OB_FAIL(json->print(buffer, false, data.length()))) {
        } else {
          out = "CAST(" + quoted(std::string(buffer.ptr(), buffer.length())) + " AS JSON)";
        }
      } else {
        static const char hex[] = "0123456789abcdef";
        std::string bytes("X'");
        for (int64_t i = 0; i < data.length(); ++i) {
          unsigned char ch = static_cast<unsigned char>(data.ptr()[i]);
          bytes += hex[ch >> 4]; bytes += hex[ch & 15];
        }
        bytes += '\'';
        const char *charset = common::ObCharset::charset_name(value.get_collation_type());
        const char *collation = common::ObCharset::collation_name(value.get_collation_type());
        if (charset == nullptr || collation == nullptr) { ret = common::OB_ERR_UNEXPECTED; }
        else { out = "CONVERT(" + bytes + " USING " + charset + ") COLLATE " + collation; }
      }
    } else if (OB_FAIL(value.print_sql_literal(buf, length, pos,
                         op.get_exec_ctx().get_allocator(), op.get_obj_print_params()))) {
    } else { out.assign(buf, pos); }
    return ret;
  }
  static int different(ObTableModifyOp &op, const ObDMLBaseCtDef &ctdef,
                       uint64_t column_id, bool &changed)
  {
    int ret = common::OB_SUCCESS;
    std::string old_value, new_value;
    const int idx = index(ctdef, column_id);
    if (OB_FAIL(literal(op, ctdef.old_row_, idx, old_value))) {
    } else if (OB_FAIL(literal(op, ctdef.new_row_, idx, new_value))) {
    } else { changed = old_value != new_value; }
    return ret;
  }
  static int rowkey(ObTableModifyOp &op, const Table &table,
                    const ObDMLBaseCtDef &ctdef, const ObExprPtrIArray &row,
                    std::string &out)
  {
    int ret = common::OB_SUCCESS;
    out.clear();
    const common::ObRowkeyInfo &keys = table.get_rowkey_info();
    for (int64_t i = 0; OB_SUCC(ret) && i < keys.get_size(); ++i) {
      uint64_t id = 0;
      std::string value;
      const Column *column = nullptr;
      if (OB_FAIL(keys.get_column_id(i, id))) {
      } else if (OB_ISNULL(column = table.get_column_schema(id))) {
        ret = common::OB_ERR_UNEXPECTED;
      } else if (OB_FAIL(literal(op, row, index(ctdef, id), value, true))) {
      } else {
        if (i != 0) { out += " AND "; }
        out += ident(column->get_column_name_str()) + " = " + value;
      }
    }
    if (OB_SUCC(ret) && (out.empty() || out.size() > 2048)) { ret = common::OB_SIZE_OVERFLOW; }
    return ret;
  }
  static int set_text(ObTableModifyOp &op, const ObDMLBaseCtDef &ctdef,
                      uint64_t id, const std::string &value)
  {
    int ret = common::OB_SUCCESS;
    const int idx = index(ctdef, id);
    if (idx < 0 || idx >= ctdef.new_row_.count()) { ret = common::OB_ERR_UNEXPECTED; }
    else {
      ObExpr &expr = *ctdef.new_row_.at(idx);
      op.clear_dml_evaluated_flag(&expr);
      common::ObDatum &datum = expr.locate_datum_for_write(op.get_eval_ctx());
      common::ObString text(static_cast<int32_t>(value.size()), value.data());
      if (OB_FAIL(common::ObAIFuncUtils::set_string_result(expr, op.get_eval_ctx(), datum, text))) {
      } else {
        expr.get_eval_info(op.get_eval_ctx()).evaluated_ = true;
        if (expr.is_batch_result()) { expr.get_evaluated_flags(op.get_eval_ctx()).set(op.get_eval_ctx().get_batch_idx()); }
      }
    }
    return ret;
  }
  static int set_value(ObTableModifyOp &op, const ObDMLBaseCtDef &ctdef,
                       uint64_t id, bool is_null, int64_t value = 0)
  {
    const int idx = index(ctdef, id);
    if (idx < 0 || idx >= ctdef.new_row_.count()) { return common::OB_ERR_UNEXPECTED; }
    ObExpr &expr = *ctdef.new_row_.at(idx);
    op.clear_dml_evaluated_flag(&expr);
    common::ObDatum &datum = expr.locate_datum_for_write(op.get_eval_ctx());
    if (is_null) { datum.set_null(); } else { datum.set_int(value); }
    expr.get_eval_info(op.get_eval_ctx()).evaluated_ = true;
    if (expr.is_batch_result()) { expr.get_evaluated_flags(op.get_eval_ctx()).set(op.get_eval_ctx().get_batch_idx()); }
    return common::OB_SUCCESS;
  }
  static int input_snapshot(ObTableModifyOp &op, const Table &table,
                            const ObDMLBaseCtDef &ctdef, const Definition &def,
                            std::string &snapshot)
  {
    int ret = common::OB_SUCCESS;
    std::string query = "SELECT CAST((" + def.input_expr + ") AS CHAR CHARACTER SET utf8mb4) AS ai_input, "
        + (def.config_expr.empty() ? "NULL" : "CAST((" + def.config_expr + ") AS CHAR CHARACTER SET utf8mb4)")
        + " AS ai_config FROM (SELECT ";
    for (size_t i = 0; OB_SUCC(ret) && i < def.dependencies.size(); ++i) {
      const Column *column = table.get_column_schema(common::ObString::make_string(def.dependencies[i].c_str()));
      std::string value;
      if (column == nullptr) { ret = common::OB_SCHEMA_ERROR; }
      else if (OB_FAIL(literal(op, ctdef.new_row_, index(ctdef, column->get_column_id()), value))) {
      } else {
        if (i != 0) { query += ','; }
        query += value + " AS " + ident(column->get_column_name_str());
      }
    }
    if (def.dependencies.empty()) { query += "1 AS ai_dummy"; }
    query += ") ai_snapshot";
    if (OB_SUCC(ret)) {
      common::ObMySQLProxy::MySQLResult result;
      if (OB_FAIL(op.begin_nested_session(false))) {
      } else {
        if (OB_FAIL(op.execute_read(query.c_str(), result))) {
        } else if (OB_ISNULL(result.get_result())) { ret = common::OB_ERR_UNEXPECTED;
        } else if (OB_FAIL(result.get_result()->next())) {
        } else {
          common::ObObj value;
          if (OB_FAIL(result.get_result()->get_obj("ai_input", value))) {
          } else {
            rapidjson::StringBuffer buffer;
            rapidjson::Writer<rapidjson::StringBuffer> writer(buffer);
            writer.StartObject(); writer.Key("input");
            for (int field = 0; OB_SUCC(ret) && field < 2; ++field) {
              if (field == 1) {
                ret = result.get_result()->get_obj("ai_config", value);
                writer.Key("config");
              }
              if (OB_FAIL(ret)) {
              } else if (value.is_null()) { writer.Null(); }
              else {
                common::ObString data = value.get_string();
                if (OB_FAIL(ObTextStringHelper::read_real_string_data(op.get_exec_ctx(),
                        &op.get_exec_ctx().get_allocator(), value.get_type(), value.get_collation_type(),
                        value.has_lob_header(), data))) {
                } else { writer.String(data.ptr(), data.length()); }
              }
            }
            if (OB_SUCC(ret)) {
              writer.EndObject(); snapshot.assign(buffer.GetString(), buffer.GetSize());
            }
          }
        }
        result.reset();
        const int end_ret = op.end_nested_session();
        if (OB_SUCC(ret)) { ret = end_ret; }
      }
    }
    return ret;
  }
  static int get_table(ObTableModifyOp &op, const ObDMLBaseCtDef &ctdef, const Table *&table)
  {
    auto *ctx = op.get_exec_ctx().get_sql_ctx();
    if (ctx == nullptr || ctx->schema_guard_ == nullptr) { return common::OB_ERR_UNEXPECTED; }
    return ctx->schema_guard_->get_table_schema(ctdef.das_base_ctdef_.index_tid_, table);
  }
public:
  static int prepare(ObTableModifyOp &op, const ObDMLBaseCtDef &ctdef, bool inserted)
  {
    int ret = common::OB_SUCCESS;
    const Table *table = nullptr;
    if (!ctdef.has_ai_column_ || op.get_exec_ctx().get_my_session()->is_inner()) { return ret; }
    if (OB_FAIL(get_table(op, ctdef, table))) { return ret; }
    if (table == nullptr) { return common::OB_SCHEMA_ERROR; }
    bool pk_changed = inserted;
    for (int64_t i = 0; OB_SUCC(ret) && !pk_changed && i < table->get_rowkey_info().get_size(); ++i) {
      uint64_t id = 0;
      if (OB_FAIL(table->get_rowkey_info().get_column_id(i, id))) {
      } else if (OB_FAIL(different(op, ctdef, id, pk_changed))) {}
    }
    std::string request;
    for (auto it = table->column_begin(); OB_SUCC(ret) && it != table->column_end(); ++it) {
      const Column &column = **it;
      if (!column.is_ai_column()) { continue; }
      Definition def;
      bool changed = pk_changed;
      if (OB_FAIL(def.parse(column.get_ai_column_info()))) { break; }
      for (size_t i = 0; OB_SUCC(ret) && !changed && i < def.dependencies.size(); ++i) {
        const Column *dep = table->get_column_schema(common::ObString::make_string(def.dependencies[i].c_str()));
        if (dep == nullptr) { ret = common::OB_SCHEMA_ERROR; }
        else { ret = different(op, ctdef, dep->get_column_id(), changed); }
      }
      if (OB_SUCC(ret) && changed) {
        if (request.empty()) { request = std::to_string(ObExprUuidShort::generate_uuid_short()); }
        std::string snapshot;
        if (OB_FAIL(input_snapshot(op, *table, ctdef, def, snapshot))) {
        } else if (OB_FAIL(set_value(op, ctdef, column.get_column_id(), true))) {
        } else if (OB_FAIL(set_value(op, ctdef, def.state_column_id, false, 0))) {
        } else if (OB_FAIL(set_text(op, ctdef, def.request_column_id, request))) {
        } else if (OB_FAIL(set_text(op, ctdef, def.result_spec_column_id, snapshot))) {}
      }
    }
    return ret;
  }
  static int after(ObTableModifyOp &op, const ObDMLBaseCtDef &ctdef, ObDmlEventType event)
  {
    int ret = common::OB_SUCCESS;
    const Table *table = nullptr;
    if (!ctdef.has_ai_column_ || op.get_exec_ctx().get_my_session()->is_inner()) { return ret; }
    if (OB_FAIL(get_table(op, ctdef, table))) { return ret; }
    if (table == nullptr) { return common::OB_SCHEMA_ERROR; }
    const bool inserted = event == ObDmlEventType::DE_INSERTING;
    const bool deleted = event == ObDmlEventType::DE_DELETING;
    std::string old_key, new_key;
    if (!inserted && OB_FAIL(rowkey(op, *table, ctdef, ctdef.old_row_, old_key))) {
    } else if (!deleted && OB_FAIL(rowkey(op, *table, ctdef, ctdef.new_row_, new_key))) {}
    if (OB_FAIL(ret)) { return ret; }
    if (OB_FAIL(op.begin_nested_session(false))) { return ret; }
    if (deleted || (!inserted && old_key != new_key)) {
      std::string sql = "DELETE FROM oceanbase.__all_ai_column_task WHERE table_id="
          + std::to_string(table->get_table_id()) + " AND rowkey_predicate=" + quoted(old_key);
      ret = op.execute_write(sql.c_str());
    }
    for (auto it = table->column_begin(); OB_SUCC(ret) && !deleted && it != table->column_end(); ++it) {
      const Column &column = **it;
      if (!column.is_ai_column()) { continue; }
      Definition def;
      bool changed = inserted;
      if (OB_FAIL(def.parse(column.get_ai_column_info()))) { break; }
      if (!inserted && OB_FAIL(different(op, ctdef, def.request_column_id, changed))) { break; }
      if (!changed) { continue; }
      common::ObDatum *request_datum = nullptr, *snapshot_datum = nullptr;
      const int req_idx = index(ctdef, def.request_column_id);
      const int spec_idx = index(ctdef, def.result_spec_column_id);
      if (req_idx < 0 || spec_idx < 0) { ret = common::OB_ERR_UNEXPECTED; break; }
      if (OB_FAIL(ctdef.new_row_.at(req_idx)->eval(op.get_eval_ctx(), request_datum))) {
      } else if (OB_FAIL(ctdef.new_row_.at(spec_idx)->eval(op.get_eval_ctx(), snapshot_datum))) {}
      if (OB_FAIL(ret)) { break; }
      common::ObString snapshot;
      if (OB_FAIL(ObTextStringHelper::read_real_string_data(op.get_exec_ctx(), op.get_exec_ctx().get_allocator(),
                      *snapshot_datum, ctdef.new_row_.at(spec_idx)->datum_meta_,
                      ctdef.new_row_.at(spec_idx)->obj_meta_.has_lob_header(), snapshot))) { break; }
      rapidjson::Document doc;
      doc.Parse(snapshot.ptr(), snapshot.length());
      if (doc.HasParseError() || !doc.IsObject() || !doc.HasMember("input") ||
          (!doc["input"].IsNull() && !doc["input"].IsString()) ||
          (doc.HasMember("config") && !doc["config"].IsNull() && !doc["config"].IsString())) {
        ret = common::OB_INVALID_DATA; break;
      }
      const std::string input = doc["input"].IsNull() ? "NULL" : quoted(std::string(doc["input"].GetString(), doc["input"].GetStringLength()));
      const std::string config = !doc.HasMember("config") || doc["config"].IsNull() ? "NULL"
          : quoted(std::string(doc["config"].GetString(), doc["config"].GetStringLength()));
      const std::string request(request_datum->get_string().ptr(), request_datum->get_string().length());
      std::string sql = "INSERT INTO oceanbase.__all_ai_column_task "
          "(table_id,column_id,rowkey_predicate,request_id,definition_version,model_name,input_text,result_type,dimension,max_retries,retry_count,state,eligible_ts,lease_owner,lease_expires,result,last_error,system_prompt,config) VALUES ("
          + std::to_string(table->get_table_id()) + ',' + std::to_string(column.get_column_id()) + ',' + quoted(new_key)
          + ',' + quoted(request) + ',' + std::to_string(def.definition_version) + ',' + quoted(def.model_name)
          + ',' + input + ',' + quoted(def.result_type) + ',' + std::to_string(def.dimension) + ',' + std::to_string(def.max_retries)
          + ",0,0,NOW(6),'',NULL,NULL,0," + quoted(def.system_prompt) + ',' + config + ") ON DUPLICATE KEY UPDATE "
          "request_id=VALUES(request_id),definition_version=VALUES(definition_version),model_name=VALUES(model_name),input_text=VALUES(input_text),result_type=VALUES(result_type),dimension=VALUES(dimension),max_retries=VALUES(max_retries),retry_count=0,state=0,eligible_ts=NOW(6),lease_owner='',lease_expires=NULL,result=NULL,last_error=0,system_prompt=VALUES(system_prompt),config=VALUES(config)";
      ret = op.execute_write(sql.c_str());
    }
    const int end_ret = op.end_nested_session();
    if (OB_SUCC(ret)) { ret = end_ret; }
    return ret;
  }
};
} }
