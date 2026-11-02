#pragma once
#include <cctype>
#include <string>

namespace oceanbase { namespace sql {
struct AiColumnRetryPredicate
{
  // STATUS is recognized as a lexical identifier only in this predicate.
  // Quoted identifiers/strings and SQL comments retain their original bytes.
  static std::string rewrite(const std::string &in, const std::string &state,
                               bool no_backslash_escapes)
  {
    std::string out;
    const std::string status = "(CASE " + state
        + " WHEN 1 THEN 'READY' WHEN 2 THEN 'FAILED' ELSE 'PENDING' END)";
    for (size_t i = 0; i < in.size();) {
      const size_t begin = i;
      const char ch = in[i];
      if (ch == '\'' || ch == '"' || ch == '`') {
        ++i;
        while (i < in.size()) {
          if (in[i] == '\\' && ch != '`' && !no_backslash_escapes && i + 1 < in.size()) { i += 2; }
          else if (in[i++] == ch) {
            if (i < in.size() && in[i] == ch) { ++i; }
            else { break; }
          }
        }
        out.append(in, begin, i - begin);
      } else if (ch == '/' && i + 1 < in.size() && in[i + 1] == '*') {
        i += 2;
        while (i + 1 < in.size() && !(in[i] == '*' && in[i + 1] == '/')) { ++i; }
        i = i + 1 < in.size() ? i + 2 : in.size();
        out.append(in, begin, i - begin);
      } else if (ch == '#' || (ch == '-' && i + 2 < in.size() && in[i + 1] == '-'
                             && std::isspace(static_cast<unsigned char>(in[i + 2])))) {
        while (i < in.size() && in[i] != '\n') { ++i; }
        out.append(in, begin, i - begin);
      } else if (std::isalpha(static_cast<unsigned char>(ch)) || ch == '_' || ch == '$') {
        while (i < in.size() && (std::isalnum(static_cast<unsigned char>(in[i]))
               || in[i] == '_' || in[i] == '$')) { ++i; }
        std::string token = in.substr(begin, i - begin), lower = token;
        for (char &c : lower) { c = static_cast<char>(std::tolower(static_cast<unsigned char>(c))); }
        out += lower == "status" ? status : token;
      } else { out += in[i++]; }
    }
    return out.empty() ? "1" : out;
  }
};
} }
