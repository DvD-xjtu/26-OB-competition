# Vector auxiliary DDL scan parallelism

Base: 4c135dd0516f3ac4b22ffa75cc269dde916fc6bf. User reports official build=2.276x/query=2.779x/gates=pass, score 16.48. The preceding worker run was 1.881x/2.631x/pass; these are separate same-platform rounds, not an independent causal timing study.

Target: increase default generated vector-auxiliary-table build SQL scan parallelism to at most eight and the configured CPU count. Keep all rows, IDs, ordering expressions, snapshots, GPU graph/search parameters, worker, CPU backend and timer boundaries. Do not change user/evaluator SQL inputs.

Acceptance: full ob_ddl_common_rs_impl.cpp host syntax compilation using actual project headers; extracted production policy checks over vector/nonvector types, CPU bounds and existing parallelism; existing snapshot and worker regressions. Linux/ROCm full build, parallel SQL execution, GPU integrity/Recall/resource gates and official score remain platform checks.
