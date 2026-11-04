"""Check streamed FTS DDL rows against ordinary DML-built indexes.

Exercises thousands of generated rows, out-of-row LOB input, encoded string
primary keys, and index rebuild after updates. Uses fts_stream_regression only.
"""
import os
import pymysql
from index_build_postings import assert_build_indexes_equal

connection = pymysql.connect(
    unix_socket=os.environ["FTS_TEST_SOCKET"], user="root",
    charset="utf8mb4", autocommit=True,
)
rows = [("doc%05d_中文_abcdefgh" % i, "anchor alpha token%d" % (i % 7)) for i in range(1300)]
rows += [
    ("long_中文", "anchor " + " ".join("streamterm%d" % i for i in range(3500))),
    ("lob_中文", "anchor gamma " * 12000),
    ("mixed_中文", "anchor 数据库中文查询 " * 3000),
    ("empty_中文", ""), ("null_中文", None),
]
queries = ["anchor", "alpha", "gamma", "streamterm0", "streamterm1750 streamterm3499", "数据库", "absent"]
checks = 0
score_difference_cases = 0
posting_checks = 0
with connection.cursor() as cursor:
    cursor.execute("create database if not exists fts_stream_regression")
    cursor.execute("use fts_stream_regression")
    for parser in ("ik", "beng"):
        for table in ("bulk_docs", "dml_docs"):
            cursor.execute("drop table if exists " + table)
            cursor.execute("create table " + table + "(id varchar(96) primary key, content mediumtext) charset=utf8mb4")
        cursor.executemany("insert into bulk_docs values(%s,%s)", rows)
        cursor.execute("create fulltext index ft on bulk_docs(content) with parser " + parser)
        cursor.execute("create fulltext index ft on dml_docs(content) with parser " + parser)
        cursor.executemany("insert into dml_docs values(%s,%s)", rows)
        for phase in range(3):
            if phase == 1:
                for table in ("bulk_docs", "dml_docs"):
                    cursor.execute("update " + table + " set content='anchor newword 中文' where id in (%s,%s)", ("long_中文", "lob_中文"))
                    cursor.execute("delete from " + table + " where id=%s", ("doc00000_中文_abcdefgh",))
            if phase == 2:
                cursor.execute("drop index ft on bulk_docs")
                cursor.execute("create fulltext index ft on bulk_docs(content) with parser " + parser)
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
                if query == "anchor":
                    expected = 1303 if phase == 0 else 1302
                    assert len(results[0][0]) == expected, (parser, phase, len(results[0][0]), expected)
                checks += 1
print("PASS", checks, "streamed index long-document, LOB, string-key and rebuild comparisons")

print("PASS", posting_checks, "complete inverted/forward postings comparisons (PK,word,frequency,length)")
print("INFO", score_difference_cases, "queries have differing BM25 scores across major-SSTable/DML-memtable layouts; numerical score equality is not asserted here")
