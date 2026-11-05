# Memory-backed snapshot staging

Base: 924db86436e91344eef51d82fec0be1ded9066a5. User reports official build=2.923x/query=2.703x/gates=pass, score 19.67. Only change temporary snapshot staging to a Linux memfd; keep persisted bytes, final persistence and all build/load work in the timed path. No graph/search/worker/DDL parallelism changes. Preserve tmpfile fallback. CPU format and descriptor lifecycle tests plus complete-source compilation are local gates; actual Linux/ROCm run, resource limits and score remain unverified until platform testing.
