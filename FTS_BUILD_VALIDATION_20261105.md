# Encoded sorting for fulltext auxiliary index construction

Reference is `9f45ebb09662f5a9e315dcb78af354fbdbc25909`, the team's previously
scored implementation. This change enables the existing order-preserving
encoded sorter for eligible fulltext word/document auxiliary-table builds.
The generated internal build SQL previously explicitly disabled that sorter.

## Scope and rationale

Diagnostic task-state timings showed that auxiliary-table data completion
dominated construction, while schema preparation and publication were brief.
Sort diagnostics observed 381,900 to 813,664 expanded rows per auxiliary
table. Comparison sorting took roughly 0.11–0.59 seconds per sort in that
diagnostic run. Both word-first and document-first auxiliary indexes sort
the expanded token rows.

The change is in `ObDDLTaskUtil::generate_build_replica_sql`. It selects
`enable_newsort=true` only for non-heap fulltext word/document auxiliary
builds with nonempty ordering keys supported by the existing encoder.
Ordinary index builds and unsupported key types or collations retain the
previous false setting. VARCHAR eligibility checks the encoder's CHAR
type/collation predicate because its automatic selection whitelist omits
VARCHAR. The existing encoder has a distinct VARCHAR implementation and the
generated expression retains the actual VARCHAR type. No schema or datum
type is changed.

The existing sorter still owns memory accounting, spill/merge handling and
invalid-Unicode fallback. Eligibility selection changes, not those algorithms.
Diagnostic verification observed encoded=1 on the large fulltext sorts and
encoded=0 on the rowkey/document-id sorts. The diagnostic timings are not
used to claim end-to-end performance.

## Full benchmark

Same Mac arm64, Clang RelWithDebInfo build configuration and dedicated
default-config instances. No compilation ran during the timed tests. Other
desktop applications were active. Each original benchmark run used
ROWS=20000 BATCH=500 ROUNDS=3000 QUERY_ROUNDS=200 SAMPLES=3 WARMUP=30
SKIP_LOAD=0, with GNU Bash/date and the repository's obclient.

Two normal-build reference/candidate pairs ran in alternating order. All
nine metrics, sample variation and hit counts are preserved under
`unittest/storage/fts/validation/20261105/`.

First pair, reference to candidate:

- IK title/content construction: 2.151 to 1.943 seconds, 9.67% lower.
- IK content construction: 1.647 to 1.448 seconds, 12.08% lower.
- BENG construction: 0.936 to 0.839 seconds, 10.36% lower.

Second pair:

- IK title/content: 3.093 to 1.944 seconds, 37.15% lower.
- IK content: 1.650 to 1.456 seconds, 11.76% lower.
- BENG: 0.938 to 0.849 seconds, 9.49% lower.

The unusually slow second reference title/content build remains in the
report. The first-pair improvement is the more conservative estimate for
that metric. The minimum measured improvement across both pairs and all
three construction metrics is 9.49%.

After removing instrumentation and restricting eligibility to non-heap
plans with ordering keys, a final clean-build check measured construction
at 2.036 / 1.448 / 0.838 seconds. Query and TOKENIZE timings are recorded
but no improvement in those categories is attributed to this change.
All four benchmark hit counts matched 8001 / 11000 / 7332 / 20.

Official benchmark data, SQL, timing, scoring and baseline files were not
modified. The changed SQL is generated inside the database for auxiliary
index construction. No official platform score for this commit is available.
Local timings cannot guarantee a higher official score or establish a
cross-platform speedup.

## Correctness and reproduction

- Complete normal database build passed.
- 645 TOKENIZE input/mode cases matched the reference in both pairs and the
  final run.
- 234 aggregate, score, ranking, DML, deletion and rollback queries matched.
  `unittest/storage/fts/fts_build_equivalence.py` loads mixed-length and
  repeated-token documents, empty/null/stopword-only text, accented text
  and mixed CJK before ALTER TABLE builds the index. Capture a reference
  with its `capture` mode, then use `compare` on the candidate with the same
  FTS_TEST_SOCKET environment setting.
- Original `fts_index/create_fts_index_afterward` mysqltest passed against
  its unchanged expected-result file, including the final clean build.

Earlier bucket-reuse and row-streaming experiments were measured separately
and did not show a reliable construction improvement. Those changes are
not included. Diagnostic patches and logs are retained locally under
`outputs/fts-build-20261104/`; production source has no diagnostic timers.
