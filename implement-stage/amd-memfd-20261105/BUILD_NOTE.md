# Build note

F0: parent/source inspected, tmpfile staging confirmed. Parent has user-reported formal pass.
F1: production constructor uses Linux syscall memfd with tmpfile fallback. Existing snapshot tests and Linux-branch CPU emulation passed with AddressSanitizer, including failure handling and descriptor closure. No real Linux syscall tested.
F2: complete adaptor source syntax passed using actual V5 project headers with the previously documented Apple Clang warning adjustment; worker ThreadSanitizer and DDL policy regressions passed. No graph, search, persisted format or DDL policy changes.
Deferred: real Linux kernel/ROCm/GPU run, formal resources and score. Required reviewer gpt-5.6-sol unavailable; record SWEEP_UNAVAILABLE rather than independent pass.
