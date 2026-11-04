# Assumption Ledger

ASK mode: never. Effort: lite.

| ID | Under-determined by the request | Chosen | Class | Source |
| --- | --- | --- | --- | --- |
| A-001 | Which optimization lands first? | Only persistent single-row GPU search dispatch, compared with 89cc68b0; other optimizations are deferred. | semantic | user |
| A-002 | Callback ownership and completion | Synchronous run: the caller retains job storage until its callback completes; serialize concurrent submissions and preserve the existing adaptor registry lock. | interface | default |
| A-003 | Worker startup failure | Report dispatch failure through the existing failed-job path; never execute the GPU callback on the small caller stack and never manufacture a successful result. | semantic | default |
| A-004 | Worker lifetime | Lazily create one process-local 32 MiB-stack worker, reused across searches and indices, then stop and join on destruction. It stores no index, graph, query, or results after completion. | interface | default |
| A-005 | Meaning of local checks | CPU concurrency/lifecycle checks and code checks only; no claimed AMD build, Recall, QPS improvement, or platform score for the candidate before formal testing. | semantic | default |
| A-006 | Reuse attribution | Cite the Apache-2.0 public persistent-worker reference 13079cc; implement an isolated worker with explicit serialized submissions and clean shutdown. | interface | default |
