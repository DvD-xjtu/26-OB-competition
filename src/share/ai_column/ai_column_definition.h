#pragma once

#include <cstdint>
#include <string>
#include <vector>
#include <rapidjson/document.h>
#include <rapidjson/stringbuffer.h>
#include <rapidjson/writer.h>
#include "lib/ob_errno.h"
#include "lib/string/ob_string.h"

namespace oceanbase { namespace share {

struct AiColumnDefinition
{
  std::string model_name;
  std::string input_expr;
  std::string expr;
  std::string column_name;
  std::string result_type;
  std::string system_prompt;
  std::string config_expr;
  std::vector<std::string> dependencies;
  int64_t dimension = 0;
  int64_t max_retries = 2;
  uint64_t state_column_id = 0;
  uint64_t request_column_id = 0;
  uint64_t result_spec_column_id = 0;
  int64_t definition_version = 1;

  std::string serialize() const
  {
    rapidjson::StringBuffer buffer;
    rapidjson::Writer<rapidjson::StringBuffer> out(buffer);
    out.StartObject();
    auto string = [&](const char *key, const std::string &value) {
      out.Key(key); out.String(value.data(), static_cast<rapidjson::SizeType>(value.size()));
    };
    string("model_name", model_name); string("input_expr", input_expr);
    string("expr", expr); string("column_name", column_name);
    string("result_type", result_type); string("system_prompt", system_prompt); string("config_expr", config_expr);
    out.Key("dependencies"); out.StartArray();
    for (const auto &name : dependencies) {
      out.String(name.data(), static_cast<rapidjson::SizeType>(name.size()));
    }
    out.EndArray();
    out.Key("dimension"); out.Int64(dimension);
    out.Key("max_retries"); out.Int64(max_retries);
    out.Key("state_column_id"); out.Uint64(state_column_id);
    out.Key("request_column_id"); out.Uint64(request_column_id);
    out.Key("result_spec_column_id"); out.Uint64(result_spec_column_id);
    out.Key("definition_version"); out.Int64(definition_version);
    out.EndObject();
    return std::string(buffer.GetString(), buffer.GetSize());
  }

  int parse(const common::ObString &json)
  {
    rapidjson::Document doc;
    doc.Parse(json.ptr(), static_cast<size_t>(json.length()));
    if (doc.HasParseError() || !doc.IsObject()) { return common::OB_INVALID_ARGUMENT; }
    AiColumnDefinition value;
    auto string = [&](const char *key, std::string &out) -> bool {
      if (!doc.HasMember(key) || !doc[key].IsString()) { return false; }
      out.assign(doc[key].GetString(), doc[key].GetStringLength()); return true;
    };
    if (!string("model_name", value.model_name) || !string("input_expr", value.input_expr)
        || !string("expr", value.expr) || !string("column_name", value.column_name)
        || !string("result_type", value.result_type) || !string("system_prompt", value.system_prompt)
        || !string("config_expr", value.config_expr)
        || !doc.HasMember("dependencies") || !doc["dependencies"].IsArray()) {
      return common::OB_INVALID_ARGUMENT;
    }
    for (const auto &name : doc["dependencies"].GetArray()) {
      if (!name.IsString()) { return common::OB_INVALID_ARGUMENT; }
      value.dependencies.emplace_back(name.GetString(), name.GetStringLength());
    }
    auto integer = [&](const char *key, int64_t &out) -> bool {
      if (!doc.HasMember(key) || !doc[key].IsInt64()) { return false; }
      out = doc[key].GetInt64(); return true;
    };
    int64_t state = 0, request = 0, spec = 0;
    if (!integer("dimension", value.dimension) || !integer("max_retries", value.max_retries)
        || !integer("state_column_id", state) || !integer("request_column_id", request)
        || !integer("result_spec_column_id", spec) || !integer("definition_version", value.definition_version)
        || state < 0 || request < 0 || spec < 0 || value.max_retries < 0) {
      return common::OB_INVALID_ARGUMENT;
    }
    value.state_column_id = static_cast<uint64_t>(state);
    value.request_column_id = static_cast<uint64_t>(request);
    value.result_spec_column_id = static_cast<uint64_t>(spec);
    *this = value;
    return common::OB_SUCCESS;
  }
};

} }
