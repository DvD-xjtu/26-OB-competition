# AI COLUMN submission status

Branch: `seekdb-ai-column-2026`.
Base: `34d4a551c3eb8c015fffd598cf1495f73633069b` (`seekdb-fts-2026`).

## Current objective
Implement competition task 3 in the native SQL/schema/DML/background paths, while retaining the existing AI functions, file SQL, and FTS changes. The user performs platform submission.

## Implemented
- CREATE/ALTER ADD AI column syntax, typed completion prompts, model-type/dependency validation, persisted column metadata, physical hidden state/request/snapshot columns, and native metadata/task tables.
- Transactional INSERT/UPDATE/DELETE invalidation and task enqueue, dependency/input/config snapshots, direct result-write protection, request/version checks, and ordinary vector-index maintenance.
- Background HTTP dispatch with durable lease/retry states and grouped terminal publication in one transaction. Deterministic target conversion failures publish NULL/FAILED.
- RETRY AI COLUMN with ordinary SQL predicates and STATUS pseudo-column handling.
- Session strict-read variable and error 11120 for referenced unfinished AI columns.

## Verified evidence
- Targeted source compilation passed for the schema, DDL resolver, DML runtime/codegen, RETRY executor, worker/service, physical plan and strict-read integration during development.
- Standalone argument-splitting regression: 38 cases passed.
- Standalone RETRY predicate regression: 13 cases passed.
- `git diff --check` passed before submission.

## Remaining validation and stop position
The full native build and database mysqltests have NOT been reported as passing. The user requested pushing the implementation without waiting for local full compilation. The next decision is based on the competition platform's actual build/test logs. No performance gain or task-3 score is claimed.

Official regression entry points: `tools/deploy/mysql_test/test_suite/ai_column/t/{ai_column_ddl,ai_column_t1_dml,ai_column_worker,ai_column_vector_index,ai_column_retry_strict}.test`. Official test inputs, expected results, benchmark inputs and scoring files are unchanged.

Known supported-expression boundary: AI input/config expressions cannot reference another AI column, subquery, parameter or qualified column name. Unsupported definitions fail during DDL rather than producing an unusable task.
