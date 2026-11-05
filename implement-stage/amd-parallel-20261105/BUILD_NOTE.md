# Build note

F0: generated SQL uses normalized parallelism in an existing parallel DML hint, retaining snapshot and ordering expressions. Baseline whole-file host syntax passed with real V5 headers and local dependency paths. Four existing Apple Clang diagnostic categories were disabled identically for parent/candidate (unnecessary-virtual-specifier, nontrivial-memcall, cast-function-type-mismatch, explicit-specialization-storage-class); no evaluator compile flags change.
F1: adjusted normalized serial default only for the three vector auxiliary schemas, preserving requests above one. 100 extracted production policy cases passed. Whole-source candidate syntax passed using the same flags as F0. No generated row/ID/sort/snapshot SQL changed.
F2: snapshot AddressSanitizer and worker 4,000-task ThreadSanitizer tests passed, as did git diff --check. Bridge, snapshot and worker implementations are unchanged. Remote verification recorded in the external project status after push.

Deferred: further GPU graph tuning and unrelated fulltext paths. No Linux/ROCm or parallel SQL runtime is available on this Mac.

Required reviewer gpt-5.6-sol unavailable; SWEEP_UNAVAILABLE, no substituted independent pass.
