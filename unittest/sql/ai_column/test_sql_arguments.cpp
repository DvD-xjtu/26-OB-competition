// Run: c++ -std=c++17 -Wall -Wextra -Werror -Isrc unittest/sql/ai_column/test_sql_arguments.cpp -o /tmp/ai-sql-arguments && /tmp/ai-sql-arguments
#include "share/ai_column/ai_column_sql.h"
#include <cassert>
#include <iostream>

using oceanbase::share::AiColumnSqlText;

int main()
{
  int cases = 0;
  auto valid = [&](const std::string &sql, const std::string &expected_name,
                   const std::vector<std::string> &expected, bool no_escape = false) {
    std::string name = "old";
    std::vector<std::string> args = {"old"};
    assert(AiColumnSqlText::arguments(sql, name, args, no_escape));
    assert(name == expected_name);
    assert(args == expected);
    ++cases;
  };
  auto invalid = [&](const std::string &sql, bool no_escape = false) {
    std::string name = "old";
    std::vector<std::string> args = {"old"};
    assert(!AiColumnSqlText::arguments(sql, name, args, no_escape));
    assert(name == "old" && args == std::vector<std::string>{"old"});
    ++cases;
  };
  valid(" AI_COMPLETE ( 'm', content ) ", "ai_complete", {"'m'", "content"});
  valid("AI_COMPLETE('m', concat(content, ',', json_extract(meta, '$.a[0]')))",
        "ai_complete", {"'m'", "concat(content, ',', json_extract(meta, '$.a[0]'))"});
  valid("ai_embed('模型', concat('中文，内容', `标,题`), 4)",
        "ai_embed", {"'模型'", "concat('中文，内容', `标,题`)", "4"});
  valid("/* ,( */ AI_COMPLETE /* ) */ ('m' /* , ) */, concat(a, b)) /*tail*/ -- end\n",
        "ai_complete", {"'m' /* , ) */", "concat(a, b)"});
  valid("ai_complete('m', a -- , )\n + b # , )\r\n)",
        "ai_complete", {"'m'", "a -- , )\n + b # , )\n"});
  valid("f(a--b, c)", "f", {"a--b", "c"});
  valid("f('a''b,c', \"a\"\"b,c\", `a``b,c`)",
        "f", {"'a''b,c'", "\"a\"\"b,c\"", "`a``b,c`"});
  valid("f('a\\\',b', \"c\\\",d\")", "f", {"'a\\\',b'", "\"c\\\",d\""});
  valid("f('a\\', b)", "f", {"'a\\'", "b"}, true);
  invalid("f('a\\', b)");
  valid("f('a\\', 'b\\')", "f", {"'a\\'", "'b\\'"}, true);
  valid("f(`a\\`, b)", "f", {"`a\\`", "b"});
  valid("f()", "f", {});
  valid("f(/* comment */)", "f", {});
  valid("# prefix\nf(a) # suffix", "f", {"a"});
  valid("f((a + (b)), '/*not a comment*/,-- #')", "f", {"(a + (b))", "'/*not a comment*/,-- #'"});
  valid("f(a -- tail\n, b)", "f", {"a -- tail\n", "b"});
  valid("f(a # tail\n)", "f", {"a # tail\n"});
  valid("f((a # inner\n))", "f", {"(a # inner\n)"});
  invalid("");
  invalid("('m', content)");
  invalid("ai_complete");
  invalid("f(a");
  invalid("f(a))");
  invalid("f(a) extra");
  invalid("f(a); ");
  invalid("f(a,)");
  invalid("f(,a)");
  invalid("f(a,,b)");
  invalid("f(/* comment */,a)");
  invalid("f(a, /*comment*/)");
  invalid("f('unterminated)");
  invalid("f(\"unterminated)");
  invalid("f(`unterminated)");
  invalid("f(a /* unterminated)");
  invalid("f(a) /* unterminated");
  invalid("/* unterminated f(a)");
  invalid("f(a -- )");
  std::cout << "PASS " << cases << " SQL argument splitter cases\n";
}
