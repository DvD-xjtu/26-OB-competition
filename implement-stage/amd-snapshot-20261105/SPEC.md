# Single-copy GPU snapshot

Base: 7c9f56afa3942209f6734931b3285f17538bc92e. User reports official build=1.881x, query=2.631x, gates=pass, score=14.055 for this worker parent. Preserve this evidence separately from the new candidate.

Target: store FP32 vectors once inside the hipVS serialized index instead of also writing them to the outer seekdb snapshot. Restore the host buffer from the loaded GPU dataset. Preserve IDs, graph/search parameters, first-query timing, worker and CPU backend. No DDL parallelism change.

Outputs: new snapshot branch with versioned reader and bridge copy_dataset symbol; CPU format tests and full adaptor compilation checks. Official acceptance still requires Linux/ROCm build and paired GPU/Recall/QPS/resource gates.

Checks: test_snapshot.py; test_query_worker.py --compile-commands; test_query_worker.py; git diff --check. A fake bridge only tests host format/control flow and is never performance evidence.
