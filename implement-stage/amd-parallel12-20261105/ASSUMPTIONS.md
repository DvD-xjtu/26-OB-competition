# Assumptions (ASK never, effort lite)

- Semantic/user: retain the 19.808-point parent, one-factor optimization toward build>=3x while keeping all gates.
- Interface/default: use min(12,max(1,GCONF.cpu_count)) for the same three vector auxiliary schemas at normalized parallelism one. CPU count zero stays one, existing requests above one remain unchanged.
- Semantic/default: DDL parallelism 12 is not a guarantee of only 12 total threads; the existing PX scheduler and formal CPU/memory quotas govern execution. Higher scheduling/memory overhead can negate gains; reject regression rather than weaken quality.
- Semantic/default: one paired platform round is not evidence of stable improvement outside run-to-run variance. Local checks cannot establish score or runtime equivalence.
