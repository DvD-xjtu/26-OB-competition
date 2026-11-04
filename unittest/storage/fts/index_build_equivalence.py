"""Compare bulk index construction with incrementally maintained FTS indexes.

The DDL scan reuses a per-document word map; ordinary DML uses a temporary map.
Comparing both routes detects stale words, frequencies, or document lengths after
empty inputs, changing bucket sizes, and rescan. Uses a dedicated test database.
"""
import os
import pymysql
from index_build_postings import assert_build_indexes_equal

connection = pymysql.connect(
    unix_socket=os.environ["FTS_TEST_SOCKET"], user="root",
    charset="utf8mb4", autocommit=True,
)
base = [
    None, "", "the and a", "alpha", "alpha alpha beta", "beta gamma",
    "中文数据检索，中文数据索引。", "数据库 database 混合检索 alpha",
    " ".join("term" + str(i) for i in range(450)),
    "alpha " * 500, "gamma", "", None,
]
rows = [(i + 1, text) for i, text in enumerate(base * 4)]
queries = ["alpha", "alpha beta", "gamma", "term1 term35 term449", "数据库",
           "中文 数据", "database alpha", "absent", "the", ""]
checks = 0
score_difference_cases = 0
posting_checks = 0
with connection.cursor() as cursor:
    cursor.execute("create database if not exists fts_build_regression")
    cursor.execute("use fts_build_regression")
    for parser in ("ik", "beng"):
        for table in ("bulk_docs", "dml_docs"):
            cursor.execute("drop table if exists " + table)
            cursor.execute("create table " + table + "(id bigint primary key, content text) charset=utf8mb4")
        cursor.executemany("insert into bulk_docs values(%s,%s)", rows)
        cursor.execute("create fulltext index ft on bulk_docs(content) with parser " + parser)
        cursor.execute("create fulltext index ft on dml_docs(content) with parser " + parser)
        cursor.executemany("insert into dml_docs values(%s,%s)", rows)
        for phase in range(3):
            if phase == 1:
                for table in ("bulk_docs", "dml_docs"):
                    cursor.execute("update " + table + " set content='fresh alpha 中文' where id in (2,9,13)")
                    cursor.execute("delete from " + table + " where id in (4,15,27)")
            if phase == 2:
                cursor.execute("begin")
                for table in ("bulk_docs", "dml_docs"):
                    cursor.execute("update " + table + " set content='gamma private' where id=5")
            assert_build_indexes_equal(cursor)
            posting_checks += 1
            for query in queries:
                results = []
                for table in ("bulk_docs", "dml_docs"):
                    cursor.execute(
                        "select id,round(match(content) against(%s),8) from " + table +
                        " where match(content) against(%s) order by id", (query, query))
                    scored = cursor.fetchall()
                    cursor.execute("select count(*) from " + table + " where match(content) against(%s)", (query,))
                    results.append((scored, cursor.fetchall()))
                assert tuple(row[0] for row in results[0][0]) == tuple(row[0] for row in results[1][0]), (parser, phase, query, "hit IDs differ")
                assert results[0][1] == results[1][1], (parser, phase, query, "aggregate count differs")
                # Native major-only average length estimates differ for a fresh
                # DML memtable. Preserve and report this observation separately.
                score_difference_cases += int(results[0][0] != results[1][0])
                checks += 1
            if phase == 2:
                cursor.execute("rollback")
print("PASS", checks, "bulk-build versus DML index comparisons")

print("PASS", posting_checks, "complete inverted/forward postings comparisons (PK,word,frequency,length)")
print("INFO", score_difference_cases, "queries have differing BM25 scores across major-SSTable/DML-memtable layouts; numerical score equality is not asserted here")
