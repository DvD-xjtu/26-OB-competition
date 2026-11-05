# Assumptions

ASK: never; effort: lite.

- A1 semantic/user: Only snapshot deduplication; keep successful worker and graph/search settings.
- A2 interface/default: Write OBCUVS03, read both OBCUVS02 and OBCUVS03. Older binaries cannot read the new format; no downgrade compatibility is claimed.
- A3 interface/default: Add seekdb_cuvs_copy_dataset C ABI; validate dense FP32 shape/type and copy using the frozen CAGRA dataset accessor. Use dataset deleter when provided. Host buffer remains available for inserts/rebuilds.
- A4 semantic/default: Any graph load or dataset-copy failure rejects the snapshot and frees its GPU handle; never publish a partially restored entry.
- A5 semantic/default: CPU tests and host syntax compilation do not establish ROCm build, GPU correctness, resources, performance or a formal score.
- A6 interface/default: Reference public Apache-2.0 juanzhi-gcb/seekdb 5be047b and f115d606 for single-copy snapshot and dataset accessor; add old-format reading and validation locally.
