# Build Note

| Rung | Acceptance | Tier | Status |
| --- | --- | --- | --- |
| F0 | Existing ObCuvsJob callback executed through its original pthread path with a fake bridge: `python3 tools/hipvs_bridge/test_query_worker.py --baseline` | MUST | passed |
| F1 | Real worker CPU dispatch, concurrency, stack, failure and shutdown checks: `python3 tools/hipvs_bridge/test_query_worker.py` | MUST | passed |
| F2 | Adaptor integration checks and `git diff --check` | MUST | passed |

## Run record

Base confirmed clean at 89cc68b0. New branch: amd-cagra-worker-2026.

F0: baseline test exited 0 on macOS/Clang. The unmodified production callback ran with a fake bridge on a 32 MiB pthread, returned the expected outputs, and published its built-index state. No GPU result is implied. Fix attempts: 0.

F1: normal, AddressSanitizer and ThreadSanitizer tests exited 0. Eight concurrent callers submitted 4,000 distinct jobs to one worker. Tests checked outputs, same worker thread, 32 MiB stack, callback error propagation, stale-index refusal, thread-creation failure/retry, and repeated destruction/join. Fix attempts: 0.

F2: the original adaptor callback now dispatches through a function-local worker. The CPU test compiles/calls that production wrapper and checks its startup failure/retry and thread reuse. Baseline, normal, AddressSanitizer and ThreadSanitizer checks passed after integration. `git diff --check` and the frozen V5 ancestry check passed. Bridge source SHA-256 remains f37bf54e8ab2e32306cd73fceaf0503a2e6862e4fc9d47fcb4aa1a3b68cb0d92. No full observer or ROCm compilation was available locally. Code fix attempts: 0. One documentation patch was retried after its old-text match failed; it did not change production code.

## Deferred

Snapshot deduplication, DDL scan parallelization, and additional graph tuning remain separate experiments. Real ROCm compilation and official paired testing require the platform.

## Blockers

The skill's required reviewer model gpt-5.6-sol is not available in this session. Record SWEEP_UNAVAILABLE rather than substituting another model or claiming a review pass.
