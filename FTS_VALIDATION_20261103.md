# IK UTF-8 ASCII traversal candidate

Reference commit is `9f45ebb09662f5a9e315dcb78af354fbdbc25909`.
The candidate changes `TokenizeContext::prepare_next_char` for ASCII bytes
under UTF8MB4_BIN and UTF8MB4_GENERAL_CI. Each such byte is one complete
codepoint, so the existing Unicode category predicates can operate directly
on it. The general path first validates the character through a charset
function pointer and then decodes it again for classification. This change
removes those calls for this subset. The opportunity follows from the call
chain and charset implementation. A CPU percentage attributable to these
calls has not been established.

## Correctness

Both reference and candidate were built completely using the same local
CMake configuration, Clang, arm64, RelWithDebInfo and `-O2`.
Local compiler launchers suppress three compatibility warnings in existing
code. The launchers apply identically to both versions.

- TOKENIZE comparison passed 660 input/mode combinations, including smart
  and max_word, mixed CJK/ASCII, long segmented inputs, all 128 ASCII bytes,
  and UTF8MB4_BIN, GENERAL_CI and UNICODE_CI collations.
- MATCH comparison passed 234 aggregate, score, ranking, threshold, update,
  delete, insertion and rollback cases.
- The existing `fts_index/tokenize_function` mysqltest passed against its
  original expected-result file.
- Benchmark hit counts were 8001, 11000, 7332 and 20 in all completed runs.

Comparison uses `unittest/storage/fts/tokenize_equivalence.py` and
`aggregate_retrieval_equivalence.py`, capturing reference results and comparing
candidate results. Token arrays are canonicalized before comparison.

## Full benchmark evidence

Ran the original `tools/benchmark/fts_large_bench.sh` using GNU Bash 5.2.37,
GNU date 9.6 and the repository-provided obclient. Settings were ROWS=20000,
BATCH=500, ROUNDS=3000, QUERY_ROUNDS=200, SAMPLES=3, WARMUP=30, SKIP_LOAD=0.
The two versions used dedicated fresh instances, the same port, default
instance configuration and client parameters. Compilation finished before
each timed run. Other desktop applications remained active.

Raw reports are under `unittest/storage/fts/validation/20261103/`.
The first ASCII pair is baseline-repeat / ik-ascii. The second pair is
ascii-baseline / ascii-repeat. Report heads identify the reference parent
because candidate tests ran before committing this patch, with git_dirty=1.

Second-pair values, reference to candidate, are listed below.

- build_ik_all_sec 2.764 to 2.145
- build_ik_content_sec 1.936 to 1.877
- build_beng_en_sec 0.924 to 1.767
- tokenize_ik_avg_ms 0.0722 to 0.0731
- tokenize_beng_avg_ms 0.0456 to 0.0453
- query_cn_avg_ms 0.7618 to 0.7750
- query_beng_avg_ms 1.1532 to 1.1912
- query_mixed_avg_ms 0.8642 to 0.8505
- query_limit_avg_ms 1.1009 to 1.0891

IK build elapsed times decreased in both pairs, while IK TOKENIZE did not
show a repeatable reduction. Large variation in the BENG build and other
measurements prevents a reliable overall gain claim. This candidate is
functionally validated locally and remains an experiment for official CI.

Earlier experiments retained locally include the BENG packed-byte predicate,
whose small TOKENIZE difference was within sampling variation, and forward
IK chain lookup, whose first-run gains failed to reproduce. The current
patch starts from the reference and contains the ASCII traversal change.

Official scores remain subject to platform validation. The platform reports
provided by the team show inconsistent composite improvements across runs
relative to the displayed nine metrics under the stated fixed-baseline
formula. Local historical baseline scores cannot resolve that discrepancy.
