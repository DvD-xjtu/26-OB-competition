# AMD V5 candidate

Base: `634888d9b037153fa143d2c913ba4b25503e1d62` (official V5).

Candidate changes reuse GPU query/output buffers within a live index and serialize calls to that workspace. Workspace is released with the index. No graph or query-result cache is reused across indexes or evaluation rounds. CAGRA construction and search parameters are unchanged. Distance-copy failures now return an error instead of claiming success.

This is a query-path optimization candidate, not a claim of full-score build acceleration. It has not been compiled with ROCm/hipVS or run on the required W7900D. Current local machine has no `hipcc`; no GPU timings, Recall, or resource claims have been made.

Required validation: official offline build; persistence write/read test; alternating top-k and query batch sizes; concurrent callers; allocation/copy failure handling; CPU `lib=vsag` regression; official paired SIFT250K/Hidden250K Recall, query regression and VRAM gates. Retained workspace peaks must be measured against the 1.25x VRAM limit. Full build optimization remains outstanding.
