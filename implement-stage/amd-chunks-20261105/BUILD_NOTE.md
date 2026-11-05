# Build note

F0: best parent 924db864 selected cleanly; rejected memfd branch remains available.
F1: production save/load blocks raised to min(graph_bytes,4 MiB). Both exact parent and candidate passed identical >4 MiB FP32/ID roundtrip and boundary truncation/error cases under AddressSanitizer; existing fake bridge accessor cases passed.
F2: whole adaptor syntax with actual project headers passed, using the documented host Apple Clang adjustment. DDL 100-policy and worker 4000-job ThreadSanitizer checks passed. Diff confirms no memfd, graph/search/bridge/worker/DDL changes. Formal performance and Linux/ROCm pending.
Required reviewer gpt-5.6-sol unavailable; no independent pass. Linux/ROCm runtime and score deferred to formal evaluation.
