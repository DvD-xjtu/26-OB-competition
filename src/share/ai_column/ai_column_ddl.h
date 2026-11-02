#pragma once
#include "share/ai_column/ai_column_definition.h"
#include "share/schema/ob_table_schema.h"
#include "share/schema/ob_column_schema.h"
#include "lib/charset/ob_charset.h"
#include <algorithm>

namespace oceanbase { namespace share {

// Allocate normal physical hidden columns so ordinary DML and index maintenance
// own their transactional visibility and rollback behavior.
inline int finalize_ai_columns(schema::ObTableSchema &table)
{
  using namespace common;
  using namespace schema;
  int ret = OB_SUCCESS;
  uint64_t next_id = table.get_max_used_column_id();
  for (int64_t i = 0; i < table.get_column_count(); ++i) {
    next_id = std::max(next_id, table.get_column_schema_by_idx(i)->get_column_id());
  }
  const int64_t count = table.get_column_count();
  for (int64_t i = 0; OB_SUCC(ret) && i < count; ++i) {
    ObColumnSchemaV2 *column = table.get_column_schema_by_idx(i);
    if (column != nullptr && column->is_ai_column()) {
      const uint64_t result_id = column->get_column_id();
      AiColumnDefinition def;
      if (OB_FAIL(def.parse(column->get_ai_column_info()))) { }
      else if (def.state_column_id != 0) { continue; }
      else {
        std::vector<std::string> canonical_dependencies;
        for (const auto &name : def.dependencies) {
          const ObColumnSchemaV2 *dependency = table.get_column_schema(ObString(name.size(), name.data()));
          if (dependency == nullptr || dependency->is_ai_column() || dependency->is_hidden()) {
            ret = OB_NOT_SUPPORTED;
            break;
          } else {
            const ObString &canonical = dependency->get_column_name_str();
            std::string value(canonical.ptr(),canonical.length());
            if (std::find(canonical_dependencies.begin(),canonical_dependencies.end(),value) == canonical_dependencies.end()) {
              canonical_dependencies.push_back(value);
            }
          }
        }
        def.dependencies.swap(canonical_dependencies);
        uint64_t *ids[] = {&def.state_column_id, &def.request_column_id, &def.result_spec_column_id};
        const char *suffixes[] = {"state", "request", "spec"};
        for (int j = 0; OB_SUCC(ret) && j < 3; ++j) {
          ObColumnSchemaV2 hidden;
          hidden.set_column_id(++next_id);
          *ids[j] = next_id;
          const std::string name = "__ai_" + std::to_string(result_id) + "_" + suffixes[j];
          if (OB_FAIL(hidden.set_column_name(ObString(name.size(), name.data())))) { }
          else {
            hidden.set_is_hidden(true);
            hidden.set_nullable(true);
            if (j == 0) { hidden.set_data_type(ObIntType); }
            else { hidden.set_data_type(j == 2 ? ObLongTextType : ObVarcharType); hidden.set_data_length(j == 2 ? 16777216 : 128);
              hidden.set_collation_type(CS_TYPE_UTF8MB4_BIN); hidden.set_charset_type(CHARSET_UTF8MB4); }
            if (OB_FAIL(table.add_column(hidden))) { }
          }
        }
        if (OB_SUCC(ret)) {
          const std::string info = def.serialize();
          column = table.get_column_schema(result_id);
          if (column == nullptr) { ret = OB_ERR_UNEXPECTED; }
          else { ret = column->set_ai_column_info(ObString(info.size(), info.data())); }
        }
      }
    }
  }
  if (OB_SUCC(ret)) { table.set_max_used_column_id(next_id); }
  return ret;
}
} }
