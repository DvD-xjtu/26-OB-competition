# UTF-8 IK traversal experiment

Reference is `9f45ebb09662f5a9e315dcb78af354fbdbc25909`.
This branch is an experimental checkpoint. It has not demonstrated a
repeatable improvement in the official nine-metric benchmark.

## Mechanism and correctness

IK character preparation and result emission each validated the first
character and decoded it again for classification. `read_first_char`
combines those operations for UTF8MB4_BIN and UTF8MB4_GENERAL_CI using the
existing range-checked UTF-8 decoder. A failed decode uses the original
validation/classification path, preserving existing invalid-input errors.
Other collations use the original path as well.

The decoder's category tests match the existing UTF-8 classification code.
Supplementary characters, embedded NUL and mixed-script long documents are
included in regression inputs. The implementation does not retain document
content or query results across calls.

Both reference and candidate were fully built with the same local arm64
Clang CMake RelWithDebInfo configuration. Verification passed:

- 645 TOKENIZE input/mode comparisons with canonicalized token arrays.
- 234 MATCH aggregate, score, ranking, DML and transaction comparisons.
- Original `fts_index/tokenize_function` mysqltest expected output.
- Standalone decoder differential check over 26,777,216 byte sequences.
  Whenever the fast decoder accepted input, its length and codepoint matched
  the original validation-then-decoding path. Rejected inputs fall back to
  the original code. This byte test does not replace full SQL regression.

## Profiling and performance

Diagnostic-only instrumentation on the reference measured character scan /
processor advancement as 85.84% of three IK batch stages, arbitration as
5.27%, and emission as 8.89%. These are instrumented elapsed-time fractions,
not uninstrumented CPU percentages. Further 1-in-64-character samples
indicated CJK processing was the largest of the four processor buckets.
Timer overhead makes small processor comparisons approximate. Character
preparation and output both perform the repeated decode addressed here.

Normal-build reports are under `unittest/storage/fts/validation/20261104`.
Each full run used the original benchmark, 20,000 rows, batch 500, 3,000
TOKENIZE repetitions, 200 query repetitions, 3 samples and 30 warmups, with
SKIP_LOAD=0 and a dedicated instance. The build finished before timing.

First pair: IK title/content build 2.554 to 2.242s, IK content build 1.944
to 1.834s, IK TOKENIZE 0.0746 to 0.0766ms. Second pair: corresponding values
2.247 to 2.554s, 1.849 to 1.836s, and 0.0718 to 0.1180ms. The second
candidate TOKENIZE median was 0.0761ms with stdev 0.0611ms. These complete
results, including regressions, are retained. All benchmark hit counts match.

A separate diagnostic SQL used BENCHMARK(10000, TOKENIZE(...)) with the same
IK text. BENCHMARK clears expression evaluation flags before each iteration
in `ob_expr_benchmark.cpp`, reducing repeated SQL parsing and client overhead.
After two warmups, five measured statements had median 0.253296s for the
reference and 0.236372s for the candidate, a 6.68% reduction. This is a
whole-function diagnostic and does not contribute to competition scoring.
It does not establish a nine-metric or cross-environment gain.

Official scoring scripts, baseline and input data were not modified. No
diagnostic instrumentation is included in the production patch. Profiling
patches and detailed logs remain in the local outputs directory. The next
performance gate is a repeatable improvement in the original full benchmark
on a less variable machine, alongside clarification of platform scoring
inputs. This candidate should not be described as a validated score increase.
