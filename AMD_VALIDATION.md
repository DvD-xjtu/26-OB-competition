# AMD CAGRA persistent-query-worker candidate

## Current comparison

The parent experiment is `amd-cagra-tuned-2026` at `89cc68b0f371056a1e7a4667e15929ced13d4b25`. The user reports its official platform result as `build=2.033x, query=1.319x, gates=pass` (approximately 14.4/20). The clean V5 control previously completed with 4.145/20. These are user-provided platform results, not independently retrieved by this checkout.

This candidate changes only single-row GPU search dispatch: the existing `ObCuvsJob` now runs synchronously on one lazily created 32 MiB-stack pthread, reused between queries. Concurrent submissions are serialized through their own completion, and destruction stops and joins the worker. Failed thread startup returns through the existing failed-search path without running GPU work on the small SQL caller stack. No index or result cache is added; each query still calls the existing fixed hipVS CAGRA search.

Graph/search parameters, bridge source and ABI, snapshot bytes, offline DDL, index freshness, IDs, filtering, CPU backend and explicit batch API are unchanged from 89cc68b0. The first query starts the worker inside the existing timed path. Snapshot deduplication and parallel DDL scans are deferred to separate experiments.

The approach is inspired by the Apache-2.0 public [persistent-worker reference 13079cc](https://github.com/juanzhi-gcb/seekdb/commit/13079cc89904c76eaf027dd29998aca5a3045208). Its published gains do not establish this candidate's performance. The helper here adds explicit submission serialization, a stop/join lifecycle, and failure handling rather than copying the reference's global single-job mailbox.

## Local checks for this candidate

Run `python3 tools/hipvs_bridge/test_query_worker.py`, optionally with `--sanitize address` or `--sanitize thread`. The test extracts and compiles the actual adaptor callback and dispatch wrapper, includes the production worker header, and replaces the GPU bridge with fake outputs. Checks cover result visibility, one reused thread, 32 MiB stack, 4,000 contended jobs from eight callers, startup failure/retry, GPU-error propagation, stale-index refusal, and shutdown. The original per-query pthread control is retained with `--baseline`. These CPU checks passed on macOS/Clang; they do not establish ROCm compilation, GPU behavior, Recall, QPS or a score.

Build with the contest's fixed bridge/CMake commands and compare with 89cc68b0 on the formal platform. Record build/query ratios and every gate. If throughput fails to improve, retain the original candidate and investigate rather than claiming the reference's gains. Full scope and check records are in [the build note](implement-stage/amd-worker-20261104/BUILD_NOTE.md).

## Parent candidate

This candidate uses the official frozen V5 commit `634888d9b037153fa143d2c913ba4b25503e1d62` and the per-index query workspace from our earlier commit `c8969b3839ad2880916d40c7a5e3dd0842644fb0`.

The parameter choices reproduce the public tuning hypothesis in [juanzhi-gcb/seekdb commit 10efa0c](https://github.com/juanzhi-gcb/seekdb/commit/10efa0c9f2c84e9959d9154f602d9950421ee13b). With graph degree 128, the bridge selects intermediate degree 128 and 24 NN-Descent iterations through 128 dimensions, then intermediate degree 160 and 32 iterations above 128 dimensions. Query width rises to 32 while the candidate-list floor stays at 512. The bridge continues to call the fixed hipVS CAGRA search implementation. This branch uses our V5 snapshot and worker implementations. Its results must be measured independently of the reference repository.

## Parent reproduction

Build the bridge and seekdb with the published contest commands, with `OB_BUILD_CUVS=ON` and `OB_BUILD_CUVS_TRACE=OFF`. In a separate AMD development environment, verify which bridge the observer loads before timing.

For a paired comparison, use the same fixed hipVS build, SQL parameters and data in fresh instances. Compare the frozen V5 bridge, our workspace-only bridge at `c8969b38`, and this branch. To isolate graph tuning and search compensation, evaluate the tuned graph first at width 4, then at width 32. Measure from offline `CREATE VECTOR INDEX` through the first completed query. Check both Top-10 and Top-100 with 4,096 individual SQL probes per group, exact ground truth, and valid distinct IDs. Record QPS, peak VRAM, CPU VSAG behavior and whether restart loads the GPU snapshot. Record any recall or throughput regression alongside acceleration.

## Historical evidence status before the user's platform result

The earlier team measurements in `amd-cagra-submit-2026` cover the uniform 40-iteration candidate on synthetic data. They do not measure this configuration. The public reference repository reports its own result and does not establish a score for this branch. At parent implementation time, real AMD compilation and paired runtime validation were pending and platform execution failed. The user has since supplied the successful parent result above. That result applies to 89cc68b0, not to this new worker candidate.
