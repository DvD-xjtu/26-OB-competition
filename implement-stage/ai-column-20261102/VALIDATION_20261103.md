# AI COLUMN runtime fixes and validation (2026-11-03)

Validated on macOS arm64, release build, dedicated fresh seekdb instance on 127.0.0.1:33882, memory_limit=4G, datafile_size=2G, log_disk_size=2G. Base branch: seekdb-ai-column-only-2026 at 480894e. The same fix commit is also applied to seekdb-ai-column-2026; that branch additionally contains FTS optimizations and has not received this exact runtime test run.

## Failures reproduced and fixed

1. Client login failed with error 1193. The AI variable was registered at index720, but get_amount() returned720 instead of721, omitting it during bootstrap. Generated initialization and its generator now use ALL_SYS_VARS_COUNT. Fresh-instance login and SELECT @@ai_column_strict_read return success/0. An already-created incomplete instance is not repaired by this change; use a fresh competition test instance.
2. DDL failed with syntax error1064 while persisting quoted AI expressions. Dedicated AI metadata writes now use the existing hex-escaped SQL splicer representation for name, normalized expression and definition JSON.
3. First DML failed4016 because native nested SQL ended an outer statement while nested_count remained1. Explicit nested sessions with a parent execution context are now classified as nested SQL, preserving caller transaction and statement lifecycle.
4. RETRY failed4014: execution used a resolver-owned schema guard after its lifetime. RETRY now obtains and owns a runtime schema guard for the entire execution.

## Unchanged official mysqltest results

Each case was executed through deps/3rd/u01/obclient/bin/mysqltest with --no-defaults --host=127.0.0.1 --port=33882 --user=root --database=test, the original test file and original r/mysql expected result. Working directory: tools/deploy. All five returned exit0 and ok:

- ai_column.ai_column_ddl
- ai_column.ai_column_t1_dml
- ai_column.ai_column_worker
- ai_column.ai_column_vector_index
- ai_column.ai_column_retry_strict

Full native CMake build passed. Additional unchanged regressions ai_function.ai_prompt, ai_function.ai_model_ddl and foreign_key.dml_147 passed. The model DDL test needed the normal host/port/admin fixture variables and admin GRANT OPTION.

An additional ai_model_endpoint_ddl attempt failed at the existing unsupported max_concurrency endpoint option (11115). This is outside the five AI COLUMN cases and no success is claimed for it. File SQL full regression and a combined FTS+AI runtime run were not performed in this validation.

Official test inputs, expected outputs, benchmark/scoring files were not modified. These are local functional results, not a platform score or fault-recovery/performance certification. Next action: submit seekdb-ai-column-only-2026 to the competition platform and use its actual logs/results.
