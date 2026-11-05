# Build note

Base checked clean, source CPU bound and existing explicit-request preservation inspected.
Passed: complete DDL source syntax with real project headers and the same four documented Mac diagnostic adjustments; 160 production policy cases around CPU counts 0/1/2/8/11/12/13/24 and explicit parallelism 0/1/2/16; snapshot AddressSanitizer and bridge accessor tests; worker ThreadSanitizer with 4,000 contended jobs; git diff --check.

Production diff against 2559231 is exactly the cap 8 to 12 and its comment. Bridge, adaptor, worker, CMake, graph/search parameters and SQL expressions have no changes. Full DDL syntax log: external outputs/amd-parallel-check/parallel12.compile.log. No Linux/ROCm full build, actual parallel SQL execution, GPU timing, resource measurement or new official score. Required reviewer model gpt-5.6-sol unavailable; no independent pass. Stop after remote delivery for formal platform testing.
