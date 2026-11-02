#pragma once

#include <cstdio>
#include <string>
#include <vector>
#include "common/object/ob_object.h"

namespace oceanbase { namespace sql {

class FileSqlParquet;

struct FileSqlCell {
  std::string text;
  bool is_null = true;
  common::ObObjType declared_type = common::ObMaxType;
};
struct FileSqlColumn {
  std::string name;
  common::ObObjType type = common::ObNullType;
  bool nullable = false;
  int16_t temporal_scale = 0;
};
struct FileSqlOptions {
  std::string format = "csv";
  bool header = true;
  char delimiter = ',';
  char quote = '"';
  char escape = '"';
  std::string null_text;
};

// Holds only one logical record and the inferred schema, never the complete file.
class FileSqlReader {
public:
  FileSqlReader() = default;
  ~FileSqlReader();
  FileSqlReader(const FileSqlReader &) = delete;
  FileSqlReader &operator=(const FileSqlReader &) = delete;
  int open(const std::string &path, const FileSqlOptions &options);
  int infer();
  int rewind();
  int next(std::vector<FileSqlCell> &row);
  int check_unchanged() const;
  const std::string &path() const { return path_; }
  const std::string &error() const { return error_; }
  const std::vector<FileSqlColumn> &columns() const { return columns_; }
  std::string descriptor() const;
  int open_descriptor(const std::string &descriptor);
  static bool is_descriptor(const std::string &value);
private:
  int csv_record(std::vector<FileSqlCell> &row);
  int json_record(std::vector<std::string> &keys, std::vector<FileSqlCell> &row);
  int fail(const char *message);
  static common::ObObjType infer_type(const FileSqlCell &cell);
  static common::ObObjType widen(common::ObObjType lhs, common::ObObjType rhs);
  FileSqlParquet *parquet_ = nullptr;
  FILE *file_ = nullptr;
  void *directory_ = nullptr;
  FileSqlOptions options_;
  std::string path_;
  std::string error_;
  std::vector<FileSqlColumn> columns_;
  int64_t size_ = 0;
  int64_t device_ = 0;
  int64_t inode_ = 0;
  int64_t mtime_ = 0;
  int64_t mtime_ns_ = 0;
  int64_t record_ = 0;
};

} }
