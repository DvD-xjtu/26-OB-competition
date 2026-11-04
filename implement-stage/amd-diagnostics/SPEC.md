# AMD diagnostic build

Base: `6f0ddaa42e4512ec12b19bf5a9e51f0d5ef12614`, a direct descendant of frozen V5.

Goal: identify the last completed build/runtime stage without changing SQL results, CAGRA parameters or the formal evaluator. Implement a local runner that preserves logs and a report on failure. Never promise that private platform logs become downloadable: code cannot observe clone failures or expose files from a backend that provides no artifact channel.

Scope: bridge/CMake stage markers and a standalone synthetic smoke runner/collector, usable with the fixed TRACE=OFF build. No model/input/ID logging, network callbacks, signal handlers, new dependencies, performance claims or score computation. The runner is a development aid, not the formal benchmark.
