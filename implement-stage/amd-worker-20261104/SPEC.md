# Persistent CAGRA query worker

Target: replace per-query pthread creation with a reusable 32 MiB-stack worker for the existing single-row GPU search path.

Base: `89cc68b0f371056a1e7a4667e15929ced13d4b25` (`amd-cagra-tuned-2026`). The user reports official build=2.033x, query=1.319x, gates=pass for this base; this is user-provided platform evidence.

Inputs: the existing synchronous `ObCuvsJob` and unchanged hipVS bridge. Outputs: the same job results and IDs; a new worker-only submission branch, with tests and attribution.

Success commands: `python3 tools/hipvs_bridge/test_query_worker.py` and `git diff --check`. The CPU tests verify dispatch, completion visibility, thread reuse, concurrency, stack size, startup failure, and shutdown. They do not validate GPU behavior or performance. Formal acceptance remains the platform's paired Recall/QPS/GPU/resource gates.

Scope: no changes to graph/search parameters, bridge, SQL, snapshot format, DDL scheduling, batch API, or timing boundaries. No local GPU run is available on this macOS host.
