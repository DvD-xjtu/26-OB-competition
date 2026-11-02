// Run: c++ -std=c++17 -Isrc unittest/sql/ai_column/test_retry_predicate.cpp -o /tmp/ai-retry-predicate && /tmp/ai-retry-predicate
#include "sql/engine/cmd/ai_column_retry_predicate.h"
#include <cassert>
#include <iostream>
using oceanbase::sql::AiColumnRetryPredicate;
int main()
{
  const std::string state = "`__ai_20_state`";
  const std::string status = "(CASE " + state + " WHEN 1 THEN 'READY' WHEN 2 THEN 'FAILED' ELSE 'PENDING' END)";
  auto rewrite = [&](const std::string &s, bool no_escape = false) {
    return AiColumnRetryPredicate::rewrite(s, state, no_escape);
  };
  assert(rewrite("") == "1");
  assert(rewrite("status = 'FAILED' and category = 'news'") == status + " = 'FAILED' and category = 'news'");
  assert(rewrite("StAtUs='READY' and id in (1,3)") == status + "='READY' and id in (1,3)");
  assert(rewrite("`status`='active' and id=1") == "`status`='active' and id=1");
  assert(rewrite("status_code='status' AND previous_status='READY'") == "status_code='status' AND previous_status='READY'");
  assert(rewrite("json_extract(content, '$.status')=status") == "json_extract(content, '$.status')=" + status);
  assert(rewrite("'sta''tus'=status") == "'sta''tus'=" + status);
  assert(rewrite("`sta``tus`=status") == "`sta``tus`=" + status);
  assert(rewrite("'status\\\'status'=status") == "'status\\\'status'=" + status);
  assert(rewrite("'status\\'=status", true) == "'status\\'=" + status);
  assert(rewrite("/* status */ status='FAILED' -- status\n AND id=1") == "/* status */ " + status + "='FAILED' -- status\n AND id=1");
  assert(rewrite("status='FAILED' # status\n AND id=1") == status + "='FAILED' # status\n AND id=1");
  assert(rewrite("category='状态 status' AND status='PENDING'") == "category='状态 status' AND " + status + "='PENDING'");
  std::cout << "PASS 13 retry predicate cases\n";
}
