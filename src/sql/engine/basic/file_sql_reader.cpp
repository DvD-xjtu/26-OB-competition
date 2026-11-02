#include "sql/engine/basic/file_sql_reader.h"
#include "sql/engine/basic/file_sql_parquet.h"
#include <algorithm>
#include <cerrno>
#include <cmath>
#include <cstdlib>
#include <cstring>
#include <limits>
#include <sstream>
#include <sys/stat.h>
#ifndef _WIN32
#include <unistd.h>
#include <dirent.h>
#include <fnmatch.h>
#endif
#include "share/json/ob_json_helper.h"

namespace oceanbase { namespace sql {
using namespace common;
namespace {
constexpr size_t MAX_RECORD_BYTES = 16 * 1024 * 1024;
constexpr size_t MAX_COLUMNS = 4096;
const std::string PREFIX = "seekdb-file-sql-v1|";
std::string hex(const std::string &s)
{
  const char *digits = "0123456789abcdef";
  std::string out;
  for (unsigned char c : s) { out += digits[c >> 4]; out += digits[c & 15]; }
  return out;
}
bool unhex(const std::string &s, std::string &out)
{
  out.clear();
  if (s.size() % 2) { return false; }
  auto digit = [](char c) { return c >= '0' && c <= '9' ? c - '0' : c >= 'a' && c <= 'f' ? c - 'a' + 10 : -1; };
  for (size_t i = 0; i < s.size(); i += 2) {
    int a = digit(s[i]), b = digit(s[i + 1]);
    if (a < 0 || b < 0) { return false; }
    out += static_cast<char>((a << 4) | b);
  }
  return true;
}
bool integer(const std::string &s, int64_t &out)
{
  if (s.empty() || s.find_first_not_of("+-0123456789") != std::string::npos) { return false; }
  char *end = nullptr;
  errno = 0;
  out = std::strtoll(s.c_str(), &end, 10);
  return errno == 0 && end == s.c_str() + s.size();
}
bool date(const std::string &s)
{
  if (s.size() < 10 || s[4] != '-' || s[7] != '-') { return false; }
  for (size_t i = 0; i < 10; ++i) {
    if (i != 4 && i != 7 && (s[i] < '0' || s[i] > '9')) { return false; }
  }
  int year = std::atoi(s.substr(0, 4).c_str()), month = std::atoi(s.substr(5, 2).c_str());
  int day = std::atoi(s.substr(8, 2).c_str());
  const int days[] = {0,31,28,31,30,31,30,31,31,30,31,30,31};
  bool leap = year % 4 == 0 && (year % 100 != 0 || year % 400 == 0);
  return year > 0 && month >= 1 && month <= 12 && day >= 1 && day <= days[month] + (month == 2 && leap);
}
}
FileSqlReader::~FileSqlReader() {
  delete parquet_;
  if (file_ != nullptr) { fclose(file_); }
#ifndef _WIN32
  if (directory_ != nullptr) { closedir(static_cast<DIR *>(directory_)); }
#endif
}
int FileSqlReader::fail(const char *message)
{
  error_ = path_ + ": record " + std::to_string(record_) + ": " + message;
  return OB_INVALID_ARGUMENT;
}
int FileSqlReader::open(const std::string &path, const FileSqlOptions &options)
{
#ifdef _WIN32
  return OB_NOT_SUPPORTED;
#else
  if (file_ != nullptr) { fclose(file_); file_ = nullptr; }
  if (directory_ != nullptr) { closedir(static_cast<DIR *>(directory_)); directory_ = nullptr; }
  delete parquet_; parquet_ = nullptr;
  options_ = options;
  columns_.clear(); record_ = 0; error_.clear();
  if (path.empty() || path.find('\0') != std::string::npos) { return fail("invalid path"); }
  char resolved[4096];
  if (options_.format == "glob") {
    size_t slash = path.find_last_of('/');
    std::string parent = slash == std::string::npos ? "." : path.substr(0, slash);
    std::string pattern = slash == std::string::npos ? path : path.substr(slash + 1);
    if (parent.empty()) { parent = "/"; }
    if (::realpath(parent.c_str(), resolved) == nullptr) { return fail("cannot resolve directory"); }
    std::string canonical = resolved;
    directory_ = opendir(canonical.c_str());
    if (directory_ == nullptr) { return fail("cannot open directory"); }
    struct stat st;
    if (fstat(dirfd(static_cast<DIR *>(directory_)), &st)) { return fail("cannot stat directory"); }
    path_ = canonical + (canonical == "/" ? "" : "/") + pattern;
    size_ = st.st_size; device_ = st.st_dev; inode_ = st.st_ino; mtime_ = st.st_mtime;
#if defined(__linux__)
    mtime_ns_ = st.st_mtim.tv_nsec;
#endif
    columns_.push_back({"file", ObVarcharType, false});
    return OB_SUCCESS;
  }

  if (::realpath(path.c_str(), resolved) == nullptr) { return fail("cannot resolve file"); }
  path_ = resolved;
  file_ = fopen(path_.c_str(), "rb");
  if (file_ == nullptr) { return fail("cannot open file"); }
  struct stat st;
  if (fstat(fileno(file_), &st) != 0 || !S_ISREG(st.st_mode)) { return fail("input must be a regular file"); }
  // Resolve the opened descriptor as well: a symlink change between resolution and open must not escape checks.
  std::string descriptor_path = "/proc/self/fd/" + std::to_string(fileno(file_));
#if defined(__linux__)
  if (::realpath(descriptor_path.c_str(), resolved) == nullptr) { return fail("cannot resolve opened file"); }
  path_ = resolved;
#endif
  size_ = st.st_size; inode_ = st.st_ino; device_ = st.st_dev; mtime_ = st.st_mtime;
#if defined(__linux__)
  mtime_ns_ = st.st_mtim.tv_nsec;
#endif
  if (options_.delimiter == '\n' || options_.delimiter == '\r' || options_.delimiter == '\0'
      || options_.delimiter == options_.quote) { return fail("invalid CSV delimiter"); }
  if (options_.format == "parquet") { return OB_SUCCESS; }
  if (options_.format != "csv" && options_.format != "json") { return OB_NOT_SUPPORTED; }
  return OB_SUCCESS;
#endif
}
int FileSqlReader::check_unchanged() const
{
#ifdef _WIN32
  return OB_NOT_SUPPORTED;
#else
  if (directory_ != nullptr) { return OB_SUCCESS; }
  struct stat st, path_st;
  if (file_ == nullptr || fstat(fileno(file_), &st) || stat(path_.c_str(), &path_st)
      || st.st_size != size_ || st.st_ino != inode_ || st.st_dev != device_ || st.st_mtime != mtime_
      || path_st.st_ino != inode_ || path_st.st_dev != device_
#if defined(__linux__)
      || st.st_mtim.tv_nsec != mtime_ns_
#endif
      ) { return OB_STATE_NOT_MATCH; }
  return OB_SUCCESS;
#endif
}
int FileSqlReader::csv_record(std::vector<FileSqlCell> &row)
{
  row.clear();
  std::string value;
  bool quoted = false, inside = false, closed = false, touched = false;
  size_t bytes = 0;
  auto push = [&]() {
    FileSqlCell cell; cell.text = value; cell.is_null = !quoted && value == options_.null_text;
    row.push_back(cell); value.clear(); quoted = inside = closed = false;
  };
  for (;;) {
    int c = fgetc(file_);
    if (c == EOF) {
      if (ferror(file_)) { return fail("read failed"); }
      if (inside) { return fail("unterminated quoted field"); }
      if (!touched && row.empty() && value.empty()) { return OB_ITER_END; }
      push(); ++record_; return OB_SUCCESS;
    }
    touched = true;
    if (++bytes > MAX_RECORD_BYTES || row.size() >= MAX_COLUMNS) { return fail("record resource limit exceeded"); }
    if (inside) {
      if (c == options_.escape && options_.escape != options_.quote) {
        int escaped = fgetc(file_);
        if (escaped == EOF) { return fail("unterminated escape"); }
        value += static_cast<char>(escaped);
      } else if (c == options_.quote) {
        int following = fgetc(file_);
        if (following == options_.quote && options_.escape == options_.quote) { value += options_.quote; }
        else { if (following != EOF) { ungetc(following, file_); } inside = false; closed = true; }
      } else { value += static_cast<char>(c); }
    } else if (c == options_.delimiter) {
      push();
    } else if (c == '\n' || c == '\r') {
      if (c == '\r') { int following = fgetc(file_); if (following != '\n' && following != EOF) { ungetc(following, file_); } }
      push(); ++record_; return OB_SUCCESS;
    } else if (closed) {
      return fail("unexpected character after closing quote");
    } else if (c == options_.quote) {
      if (!value.empty()) { return fail("quote inside unquoted field"); }
      quoted = inside = true;
    } else { value += static_cast<char>(c); }
  }
}
int FileSqlReader::json_record(std::vector<std::string> &keys, std::vector<FileSqlCell> &row)
{
  keys.clear(); row.clear();
  std::string line;
  int c;
  while ((c = fgetc(file_)) != EOF && c != '\n') {
    line += static_cast<char>(c);
    if (line.size() > MAX_RECORD_BYTES) { return fail("record resource limit exceeded"); }
  }
  if (ferror(file_)) { return fail("read failed"); }
  if (line.empty() && c == EOF) { return OB_ITER_END; }
  ++record_;
  ObArenaAllocator allocator;
  ObIJsonBase *root = nullptr;
  int ret = ObJsonBaseFactory::get_json_base(&allocator, ObString(line.size(), line.data()),
                                            ObJsonInType::JSON_TREE, ObJsonInType::JSON_TREE, root);
  if (ret != OB_SUCCESS || root == nullptr || root->json_type() != ObJsonNodeType::J_OBJECT) {
    return fail("expected a flat JSON object");
  }
  auto *object = static_cast<ObJsonObject *>(root);
  if (object->element_count() > MAX_COLUMNS) { return fail("column resource limit exceeded"); }
  for (uint64_t i = 0; i < object->element_count(); ++i) {
    ObString key;
    if (object->get_key(i, key) != OB_SUCCESS) { return fail("invalid object key"); }
    keys.emplace_back(key.ptr(), key.length());
    if (std::count(keys.begin(), keys.end(), keys.back()) != 1) { return fail("duplicate JSON key"); }
    ObJsonNode *node = object->get_value(i);
    FileSqlCell cell;
    cell.is_null = node->json_type() == ObJsonNodeType::J_NULL;
    if (!cell.is_null) {
      if (node->json_type() == ObJsonNodeType::J_OBJECT || node->json_type() == ObJsonNodeType::J_ARRAY) {
        return fail("nested JSON values are not supported");
      } else if (node->json_type() == ObJsonNodeType::J_STRING) {
        cell.text.assign(node->get_data(), node->get_data_length());
        cell.declared_type = ObVarcharType;
        if (date(cell.text)) { cell.declared_type = infer_type(FileSqlCell{cell.text, false, ObMaxType}); }
      } else {
        ObJsonBuffer buffer(&allocator);
        if (node->print(buffer, false, false) != OB_SUCCESS) { return fail("invalid JSON scalar"); }
        cell.text.assign(buffer.ptr(), buffer.length());
      }
    }
    row.push_back(cell);
  }
  return OB_SUCCESS;
}
ObObjType FileSqlReader::infer_type(const FileSqlCell &cell)
{
  if (cell.is_null) { return ObNullType; }
  if (cell.declared_type != ObMaxType) { return cell.declared_type; }
  const std::string &s = cell.text;
  if (s == "true" || s == "false" || s == "TRUE" || s == "FALSE") { return ObTinyIntType; }
  int64_t value;
  if (integer(s, value)) { return ObIntType; }
  // Integer overflow is preserved as text rather than silently rounded to double.
  size_t digits_from = !s.empty() && (s[0] == '+' || s[0] == '-') ? 1 : 0;
  if (digits_from < s.size() && s.find_first_not_of("0123456789", digits_from) == std::string::npos) { return ObVarcharType; }
  char *end = nullptr;
  errno = 0;
  double number = std::strtod(s.c_str(), &end);
  if (!s.empty() && end == s.c_str() + s.size() && errno == 0 && std::isfinite(number)) { return ObDoubleType; }
  if (date(s)) {
    if (s.size() == 10) { return ObDateType; }
    if (s.size() == 19 && (s[10] == ' ' || s[10] == 'T') && s[13] == ':' && s[16] == ':') {
      std::string time = s.substr(11);
      bool valid = true;
      for (size_t i = 0; i < time.size(); ++i) { if (i != 2 && i != 5 && (time[i] < '0' || time[i] > '9')) { valid = false; } }
      if (valid && std::atoi(time.c_str()) < 24 && std::atoi(time.c_str() + 3) < 60 && std::atoi(time.c_str() + 6) < 60) {
        return ObDateTimeType;
      }
    }
  }
  return ObVarcharType;
}
ObObjType FileSqlReader::widen(ObObjType lhs, ObObjType rhs)
{
  if (lhs == ObNullType) { return rhs; }
  if (rhs == ObNullType || lhs == rhs) { return lhs; }
  if ((lhs == ObTinyIntType || lhs == ObIntType || lhs == ObDoubleType)
      && (rhs == ObTinyIntType || rhs == ObIntType || rhs == ObDoubleType)) {
    return lhs == ObDoubleType || rhs == ObDoubleType ? ObDoubleType : ObIntType;
  }
  if ((lhs == ObDateType || lhs == ObDateTimeType) && (rhs == ObDateType || rhs == ObDateTimeType)) { return ObDateTimeType; }
  return ObVarcharType;
}
int FileSqlReader::infer()
{
  if (options_.format == "parquet") {
    if (parquet_ == nullptr) { parquet_ = new (std::nothrow) FileSqlParquet(); }
    if (parquet_ == nullptr) { return OB_ALLOCATE_MEMORY_FAILED; }
    return parquet_->open(file_, size_, columns_) ? OB_SUCCESS : fail("invalid or unsupported Parquet file");
  }
  if (directory_ != nullptr) { return rewind(); }
  if (file_ == nullptr) { return OB_NOT_INIT; }
  std::vector<FileSqlCell> row;
  std::vector<std::string> keys;
  int ret = OB_SUCCESS;
  if (options_.format == "csv" && options_.header) {
    if ((ret = csv_record(row)) != OB_SUCCESS) { return ret == OB_ITER_END ? fail("empty CSV has no schema") : ret; }
    for (size_t i = 0; i < row.size(); ++i) {
      std::string name = row[i].text;
      if (i == 0 && name.compare(0, 3, "\xef\xbb\xbf") == 0) { name.erase(0, 3); }
      if (name.empty()) { name = "column" + std::to_string(i + 1); }
      std::string base = name;
      int duplicate = 1;
      while (std::any_of(columns_.begin(), columns_.end(), [&](const FileSqlColumn &c) { return c.name == name; })) {
        name = base + "__" + std::to_string(++duplicate);
      }
      columns_.push_back({name, ObNullType});
    }
  }
  while ((ret = options_.format == "csv" ? csv_record(row) : json_record(keys, row)) == OB_SUCCESS) {
    if (options_.format == "csv") {
      if (columns_.empty()) {
        for (size_t i = 0; i < row.size(); ++i) { columns_.push_back({"column" + std::to_string(i + 1), ObNullType}); }
      }
      if (row.size() != columns_.size()) { return fail("CSV field count does not match schema"); }
      for (size_t i = 0; i < row.size(); ++i) { columns_[i].type = widen(columns_[i].type, infer_type(row[i])); columns_[i].nullable |= row[i].is_null; }
    } else {
      for (size_t i = 0; i < keys.size(); ++i) {
        auto found = std::find_if(columns_.begin(), columns_.end(), [&](const FileSqlColumn &c) { return c.name == keys[i]; });
        if (found == columns_.end()) { columns_.push_back({keys[i], infer_type(row[i]), record_ > 1 || row[i].is_null}); }
        else { found->type = widen(found->type, infer_type(row[i])); found->nullable |= row[i].is_null; }
      }
      for (auto &column : columns_) { if (std::find(keys.begin(), keys.end(), column.name) == keys.end()) { column.nullable = true; } }
      if (columns_.size() > MAX_COLUMNS) { return fail("column resource limit exceeded"); }
    }
  }
  if (ret != OB_ITER_END) { return ret; }
  if (columns_.empty()) { return fail("file has no columns"); }
  return rewind();
}
int FileSqlReader::rewind()
{
#ifndef _WIN32
  if (directory_ != nullptr) { rewinddir(static_cast<DIR *>(directory_)); record_ = 0; return OB_SUCCESS; }
#endif
  int ret = check_unchanged();
  if (ret != OB_SUCCESS) { return ret; }
  if (parquet_ != nullptr) { return parquet_->rewind() ? OB_SUCCESS : fail("cannot rewind Parquet"); }
  if (fseek(file_, 0, SEEK_SET) != 0) { return fail("cannot rewind file"); }
  clearerr(file_); record_ = 0;
  if (options_.format == "csv" && options_.header) { std::vector<FileSqlCell> ignored; return csv_record(ignored); }
  return OB_SUCCESS;
}
int FileSqlReader::next(std::vector<FileSqlCell> &row)
{
#ifndef _WIN32
  if (directory_ != nullptr) {
    size_t slash = path_.find_last_of('/');
    std::string parent = path_.substr(0, slash + 1), pattern = path_.substr(slash + 1);
    dirent *entry = nullptr;
    while ((entry = readdir(static_cast<DIR *>(directory_))) != nullptr) {
      if (fnmatch(pattern.c_str(), entry->d_name, FNM_PERIOD) == 0) {
        std::string candidate = parent + entry->d_name;
        struct stat st;
        if (lstat(candidate.c_str(), &st) == 0 && S_ISREG(st.st_mode)) {
          row.assign(1, FileSqlCell{candidate, false, ObVarcharType}); ++record_; return OB_SUCCESS;
        }
      }
    }
    return OB_ITER_END;
  }
#endif
  int ret = check_unchanged();
  if (ret != OB_SUCCESS) { return ret; }
  if (parquet_ != nullptr) { return parquet_->next(row); }
  if (options_.format == "csv") {
    ret = csv_record(row);
    if (ret == OB_SUCCESS && row.size() != columns_.size()) { return fail("CSV field count changed"); }
  } else {
    std::vector<std::string> keys;
    std::vector<FileSqlCell> values;
    ret = json_record(keys, values);
    if (ret == OB_SUCCESS) {
      row.assign(columns_.size(), FileSqlCell());
      for (size_t i = 0; i < keys.size(); ++i) {
        auto found = std::find_if(columns_.begin(), columns_.end(), [&](const FileSqlColumn &c) { return c.name == keys[i]; });
        if (found == columns_.end()) { return fail("JSON schema changed"); }
        row[found - columns_.begin()] = values[i];
      }
    }
  }
  return ret;
}
bool FileSqlReader::is_descriptor(const std::string &value) { return value.compare(0, PREFIX.size(), PREFIX) == 0; }
std::string FileSqlReader::descriptor() const
{
  std::ostringstream out;
  out << PREFIX << hex(path_) << '|' << options_.format << '|' << options_.header << '|'
      << int(static_cast<unsigned char>(options_.delimiter)) << '|' << int(static_cast<unsigned char>(options_.quote)) << '|'
      << int(static_cast<unsigned char>(options_.escape)) << '|' << hex(options_.null_text) << '|'
      << size_ << '|' << device_ << '|' << inode_ << '|' << mtime_ << '|' << mtime_ns_;
  for (const auto &column : columns_) { out << '|' << hex(column.name) << '|' << int(column.type) << '|' << column.nullable; }
  return out.str();
}
int FileSqlReader::open_descriptor(const std::string &descriptor)
{
  if (!is_descriptor(descriptor)) { return OB_INVALID_ARGUMENT; }
  std::vector<std::string> fields;
  size_t from = PREFIX.size();
  for (;;) {
    size_t to = descriptor.find('|', from);
    fields.push_back(descriptor.substr(from, to == std::string::npos ? to : to - from));
    if (to == std::string::npos) { break; }
    from = to + 1;
  }
  if (fields.size() < 15 || (fields.size() - 12) % 3 != 0 || fields.size() > 12 + 3 * MAX_COLUMNS) { return OB_INVALID_ARGUMENT; }
  int64_t numbers[12] = {};
  for (size_t i : {size_t(2),size_t(3),size_t(4),size_t(5),size_t(7),size_t(8),size_t(9),size_t(10),size_t(11)}) {
    if (!integer(fields[i], numbers[i])) { return OB_INVALID_ARGUMENT; }
  }
  FileSqlOptions options; std::string path;
  options.format = fields[1]; options.header = numbers[2];
  if (numbers[2] < 0 || numbers[2] > 1 || numbers[3] < 1 || numbers[3] > 255
      || numbers[4] < 0 || numbers[4] > 255 || numbers[5] < 0 || numbers[5] > 255) { return OB_INVALID_ARGUMENT; }
  options.delimiter = numbers[3]; options.quote = numbers[4]; options.escape = numbers[5];
  if (!unhex(fields[0], path) || !unhex(fields[6], options.null_text)) { return OB_INVALID_ARGUMENT; }
  int ret = open(path, options);
  if (ret != OB_SUCCESS) { return ret; }
  if (size_ != numbers[7] || device_ != numbers[8] || inode_ != numbers[9]
      || mtime_ != numbers[10] || mtime_ns_ != numbers[11]) { return OB_STATE_NOT_MATCH; }
  if (options_.format == "parquet" && (ret = infer()) != OB_SUCCESS) { return ret; }
  columns_.clear();
  for (size_t i = 12; i < fields.size(); i += 3) {
    std::string name; int64_t type;
    if (!unhex(fields[i], name) || !integer(fields[i + 1], type) || type < 0 || type >= ObMaxType) { return OB_INVALID_ARGUMENT; }
    if (fields[i + 2] != "0" && fields[i + 2] != "1") { return OB_INVALID_ARGUMENT; }
    columns_.push_back({name, static_cast<ObObjType>(type), fields[i + 2] == "1"});
  }
  return rewind();
}
} }
