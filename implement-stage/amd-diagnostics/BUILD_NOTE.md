# Build note

F0 MUST: explicit local log directory → bounded diagnostic JSON (`python3 tools/hipvs_bridge/test_diagnostics.py`).

F1 MUST: fixed build, bridge phase messages and a private synthetic smoke run, with a retained failure report. Check: the same local tests, Python compilation and shell syntax; actual ROCm execution is DEFERRED.

## Run record

F0 passed: `python3 tools/hipvs_bridge/test_diagnostics.py`, exit 0, 3 tests. The real CLI creates report.json in a temporary run directory; bounded collection and external-symlink exclusion are checked. No GPU behavior is simulated or claimed.

## Deferred

Actual AMD compilation/runtime, formal benchmark, platform log retrieval. No working authenticated browser connection; no access to backend files. No platform success claimed.

## Review

The skill requires a gpt-5.6-sol reviewer, which is not available among this session's agent models. Do not substitute a model or claim an independent review. Record SWEEP_UNAVAILABLE and perform a limited implementer review.
