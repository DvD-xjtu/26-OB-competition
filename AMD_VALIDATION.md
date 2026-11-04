# AMD CAGRA tuned candidate

This candidate uses the official frozen V5 commit `634888d9b037153fa143d2c913ba4b25503e1d62` and the per-index query workspace from our earlier commit `c8969b3839ad2880916d40c7a5e3dd0842644fb0`.

The parameter choices reproduce the public tuning hypothesis in [juanzhi-gcb/seekdb commit 10efa0c](https://github.com/juanzhi-gcb/seekdb/commit/10efa0c9f2c84e9959d9154f602d9950421ee13b). With graph degree 128, the bridge selects intermediate degree 128 and 24 NN-Descent iterations through 128 dimensions, then intermediate degree 160 and 32 iterations above 128 dimensions. Query width rises to 32 while the candidate-list floor stays at 512. The bridge continues to call the fixed hipVS CAGRA search implementation. This branch uses our V5 snapshot and worker implementations. Its results must be measured independently of the reference repository.

## Reproduction

Build the bridge and seekdb with the published contest commands, with `OB_BUILD_CUVS=ON` and `OB_BUILD_CUVS_TRACE=OFF`. In a separate AMD development environment, verify which bridge the observer loads before timing.

For a paired comparison, use the same fixed hipVS build, SQL parameters and data in fresh instances. Compare the frozen V5 bridge, our workspace-only bridge at `c8969b38`, and this branch. To isolate graph tuning and search compensation, evaluate the tuned graph first at width 4, then at width 32. Measure from offline `CREATE VECTOR INDEX` through the first completed query. Check both Top-10 and Top-100 with 4,096 individual SQL probes per group, exact ground truth, and valid distinct IDs. Record QPS, peak VRAM, CPU VSAG behavior and whether restart loads the GPU snapshot. Record any recall or throughput regression alongside acceleration.

## Evidence status

The earlier team measurements in `amd-cagra-submit-2026` cover the uniform 40-iteration candidate on synthetic data. They do not measure this configuration. The public reference repository reports its own result and does not establish a score for this branch. This branch awaits a real AMD compile and paired runtime validation. The existing platform execution failure also remains unresolved.
