# Assumptions (ASK never, effort lite)

- Semantic/user: return to the best 19.67-point parent; no memfd mechanism.
- Interface/default: one transfer-block-size policy for both save and load: min(graph_bytes, 4 MiB), replacing 64 KiB. Added temporary host memory at most about 4 MiB per in-flight operation.
- Semantic/default: serialized bytes, timing boundary, rows/IDs/Recall and GPU algorithm unchanged; fewer host I/O calls are a mechanism hypothesis, not proven wall-time savings.
- Semantic/default: fake bridge tests validate host serialization and failures, not real GPU persistence or performance. Keep a separate official result per candidate.
