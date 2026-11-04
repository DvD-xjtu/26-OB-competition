# Build Note

| Rung | Acceptance | Tier | Status |
| --- | --- | --- | --- |
| F0 | Existing ObCuvsJob callback executed through its original pthread path with a fake bridge: `python3 tools/hipvs_bridge/test_query_worker.py --baseline` | MUST | passed |
| F1 | Real worker CPU dispatch, concurrency, stack, failure and shutdown checks: `python3 tools/hipvs_bridge/test_query_worker.py` | MUST | pending |
| F2 | Adaptor integration checks and `git diff --check` | MUST | pending |

## Run record

Base confirmed clean at 89cc68b0. New branch: amd-cagra-worker-2026.

F0: baseline test exited 0 on macOS/Clang. The unmodified production callback ran with a fake bridge on a 32 MiB pthread, returned the expected outputs, and published its built-index state. No GPU result is implied. Fix attempts: 0.

## Deferred

Snapshot deduplication, DDL scan parallelization, and additional graph tuning remain separate experiments. Real ROCm compilation and official paired testing require the platform.

## Blockers

The skill's required reviewer model gpt-5.6-sol is not available in this session. Record SWEEP_UNAVAILABLE rather than substituting another model or claiming a review pass.
