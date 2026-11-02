#pragma once

#include <cctype>
#include <string>
#include <utility>
#include <vector>

namespace oceanbase { namespace share {

struct AiColumnSqlText
{
  static std::string trim(const std::string &s)
  {
    size_t first = 0, last = s.size();
    while (first < last && whitespace(s[first])) { ++first; }
    while (last > first && whitespace(s[last - 1])) { --last; }
    return s.substr(first, last - first);
  }

  // Extract top-level argument boundaries from an expression already checked by
  // the SQL parser. Preserve each argument's SQL, including its comments. This
  // helper does not resolve expressions or replace the native SQL grammar.
  // On failure, leave the caller's outputs unchanged.
  static bool arguments(const std::string &sql, std::string &name,
                        std::vector<std::string> &args, bool no_backslash_escapes = false)
  {
    size_t pos = 0;
    if (!skip_trivia(sql, pos) || pos == sql.size() || !identifier_start(sql[pos])) { return false; }
    const size_t name_start = pos++;
    while (pos < sql.size() && identifier_part(sql[pos])) { ++pos; }
    std::string function = sql.substr(name_start, pos - name_start);
    for (char &c : function) {
      if (c >= 'A' && c <= 'Z') { c += 'a' - 'A'; }
    }
    if (!skip_trivia(sql, pos) || pos == sql.size() || sql[pos] != '(') { return false; }
    const size_t open = pos++;
    size_t start = open + 1, depth = 1;
    bool has_argument = false, trailing_line_comment = false;
    std::vector<std::string> parsed;
    while (pos < sql.size()) {
      const char c = sql[pos];
      if (whitespace(c)) { ++pos; continue; }
      const size_t before_comment = pos;
      if (!skip_comment(sql, pos)) { return false; }
      if (pos != before_comment) {
        if (c == '#' || c == '-') { trailing_line_comment = true; }
        continue;
      }
      if (c == '\'' || c == '"' || c == '`') {
        has_argument = true; trailing_line_comment = false;
        if (!skip_quoted(sql, pos, no_backslash_escapes)) { return false; }
      } else if (c == '(') {
        has_argument = true; trailing_line_comment = false;
        ++depth; ++pos;
      } else if (c == ')') {
        ++pos;
        if (--depth == 0) {
          if (has_argument) { parsed.push_back(argument(sql, start, pos - 1 - start, trailing_line_comment)); }
          else if (!parsed.empty()) { return false; } // trailing empty argument
          if (!skip_trivia(sql, pos) || pos != sql.size()) { return false; }
          name = std::move(function); args = std::move(parsed);
          return true;
        }
        trailing_line_comment = false;
      } else if (c == ',' && depth == 1) {
        if (!has_argument) { return false; }
        parsed.push_back(argument(sql, start, pos - start, trailing_line_comment));
        start = ++pos; has_argument = false; trailing_line_comment = false;
      } else {
        has_argument = true; trailing_line_comment = false;
        ++pos;
      }
    }
    return false;
  }

private:
  static std::string argument(const std::string &sql, size_t start, size_t length, bool trailing_line_comment)
  {
    std::string value = trim(sql.substr(start, length));
    // Keep the line terminator when this expression is later followed by FROM
    // or another SQL token; otherwise the final comment would consume it.
    if (trailing_line_comment) { value += '\n'; }
    return value;
  }
  static bool whitespace(char c) { return std::isspace(static_cast<unsigned char>(c)) != 0; }
  static bool identifier_start(char c)
  {
    return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || c == '_';
  }
  static bool identifier_part(char c)
  {
    return identifier_start(c) || (c >= '0' && c <= '9') || c == '$';
  }
  // Return false for incomplete block comments. MySQL -- comments require a
  // whitespace/control character after the second dash; --x is an expression.
  static bool skip_comment(const std::string &sql, size_t &pos)
  {
    if (sql[pos] == '#' || (sql[pos] == '-' && pos + 2 < sql.size()
        && sql[pos + 1] == '-' && (whitespace(sql[pos + 2])
            || std::iscntrl(static_cast<unsigned char>(sql[pos + 2]))))) {
      while (pos < sql.size() && sql[pos] != '\n' && sql[pos] != '\r') { ++pos; }
    } else if (sql[pos] == '/' && pos + 1 < sql.size() && sql[pos + 1] == '*') {
      const size_t end = sql.find("*/", pos + 2);
      if (end == std::string::npos) { return false; }
      pos = end + 2;
    }
    return true;
  }
  static bool skip_trivia(const std::string &sql, size_t &pos)
  {
    while (pos < sql.size()) {
      if (whitespace(sql[pos])) { ++pos; continue; }
      const size_t before = pos;
      if (!skip_comment(sql, pos)) { return false; }
      if (before == pos) { break; }
    }
    return true;
  }
  static bool skip_quoted(const std::string &sql, size_t &pos, bool no_backslash_escapes)
  {
    const char quote = sql[pos++];
    while (pos < sql.size()) {
      const char c = sql[pos++];
      if (c == '\\' && quote != '`' && !no_backslash_escapes) {
        if (pos == sql.size()) { return false; }
        ++pos;
      } else if (c == quote) {
        if (pos < sql.size() && sql[pos] == quote) { ++pos; }
        else { return true; }
      }
    }
    return false;
  }
};

} }
