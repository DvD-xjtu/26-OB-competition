# Larger snapshot transfer blocks

Base: 924db86436e91344eef51d82fec0be1ded9066a5, user-reported official 19.67 points/build=2.923x/query=2.703x/gates=pass. Do not inherit memfd candidate a3186f01 (user-reported 18.668/build=2.702x/query=2.492x/pass); the negative result remains recorded.

Only increase host snapshot staging transfer blocks from 64 KiB to 4 MiB, allocating no more than the graph length. Preserve tmpfile, format, data, GPU parameters, worker, DDL policy, final persistence and timing boundaries. Checks: large multi-block host format tests on parent/candidate, whole adaptor source syntax and existing worker/DDL regressions. This host lacks ROCm; GPU runtime/resources and score need platform validation.
