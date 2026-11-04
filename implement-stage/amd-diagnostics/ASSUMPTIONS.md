# Assumptions

ASK mode: never

- A-001 (interface, default): emit bounded `[AMD_DIAG]` stage messages to existing stderr, not SQL stdout. No separate upload service or telemetry is introduced. They remain available only where the operator/evaluator retains stderr.
- A-002 (semantic, default): synthetic smoke success is local functionality evidence, not formal Recall/GPU-profiler/throughput/resource compliance or a score. GPU build/search markers establish bridge API completion, not an independent profiler audit.
- A-003 (interface, default): the runner builds with the published CMake flags, selects its own bridge in LD_LIBRARY_PATH, starts a private instance on a checked port, and retains evidence under the selected work directory. It terminates only its own child; on success it removes only that instance's store unless requested otherwise, and retains failed stores for diagnosis.
- A-004 (interface, default): markers do not require OB_BUILD_CUVS_TRACE=ON. Log search completion at most once per index; errors remain visible. Diagnostic I/O may slightly affect timings; do not claim this is a performance optimization.
- A-005 (interface, default): collection accepts an explicit local run directory and returns only known diagnostic/error lines, with bounded output. It does not read credentials, arbitrary paths via SQL, or platform-private files.
- A-006 (semantic, default): this Mac cannot execute ROCm. Local unit tests cover diagnostic reporting and failure handling only; real AMD execution remains unverified for the new branch until run in Jupyter or by the platform.
