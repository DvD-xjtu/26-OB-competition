# Assumptions

ASK never; effort lite.

- A1 semantic/user: One new mechanism: vector auxiliary build scan parallelism. Preserve snapshot/worker gains and graph/search settings.
- A2 interface/default: Apply only to vec VID-rowkey, rowkey-VID and vector snapshot-data auxiliary schemas, and only when the original normalized parallelism is one. Respect existing requests above one.
- A3 interface/default: New default is min(8, max(1, configured cpu_count)); cpu_count=0 (automatic/unspecified) conservatively remains one. All ordering/projection/snapshot SQL remains unchanged.
- A4 semantic/default: More scan threads must preserve all input rows and external ID semantics; local syntax/policy tests do not prove this runtime property. Reject a candidate that fails official gates; never shrink input or weaken Recall to compensate.
- A5 interface/default: Reference Apache-2.0 public juanzhi-gcb/seekdb 5be047b for auxiliary scan parallelism, but do not overwrite already-parallel builds.
- A6 semantic/default: User-provided score belongs to the parent only. No predicted full-score result for this candidate.
