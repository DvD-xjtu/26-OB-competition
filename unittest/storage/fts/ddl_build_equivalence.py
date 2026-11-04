"""Compare DDL backfill with insert-time indexing on the same seekdb instance.

FTS_TEST_SOCKET specifies a private local test server. The test creates and
removes only its own randomly named database.
"""
import os
import uuid

import pymysql


def verify(cursor, parser):
    tables = [f"{parser}_built", f"{parser}_inserted"]
    rows = [
        (1, "database 索引", "alpha alpha beta 全文索引 分词器"),
        (2, "beta", "gamma gamma gamma"),
        (3, "", ""),
        (4, None, None),
        (5, "the", "a the a the"),
        (6, "存储", "跨文档词频测试 database"),
        (7, "delta", "largeword " * 3000 + "uniqueend"),
        (8, "last", "afterlarge"),
        (9, "ranking", "ranktoken ranktoken ranktoken"),
        (10, "ranking", "ranktoken wordone wordtwo"),
    ]
    for table in tables:
        cursor.execute(f"CREATE TABLE {table}(id BIGINT PRIMARY KEY, title VARCHAR(256), body TEXT)")
    cursor.execute(f"CREATE FULLTEXT INDEX ft ON {tables[1]}(title, body) WITH PARSER {parser}")
    for table in tables:
        cursor.executemany(f"INSERT INTO {table} VALUES (%s,%s,%s)", rows)
    cursor.execute(f"CREATE FULLTEXT INDEX ft ON {tables[0]}(title, body) WITH PARSER {parser}")

    cases = 0
    for phase in range(2):
        if phase:
            for table in tables:
                cursor.execute(f"UPDATE {table} SET body='beta alpha updated' WHERE id=7")
                cursor.execute(f"DELETE FROM {table} WHERE id=2")
        for term in ("alpha beta", "uniqueend", "afterlarge", "数据库", "全文索引", "updated", "the", "absent", "ranktoken"):
            results = []
            for table in tables:
                match = "MATCH(title, body) AGAINST(%s)"
                cursor.execute(f"SELECT id FROM {table} WHERE {match} ORDER BY {match} DESC, id",
                               (term, term))
                results.append(cursor.fetchall())
            # Bulk-built and incremental indexes can have different BM25
            # statistics after a write. Compare membership, then separately
            # check term frequency order for documents of equal length.
            assert sorted(results[0]) == sorted(results[1]), (parser, phase, term, results)
            if term == "afterlarge" and parser == "beng":
                assert [row[0] for row in results[0]] == [8], results
            if term == "ranktoken" and parser == "beng":
                assert all([row[0] for row in group] == [9, 10] for group in results), results
            cases += 1
    return cases


def check_connection(conn):
    database = "ddl_posting_check_" + uuid.uuid4().hex
    with conn.cursor() as cursor:
        cursor.execute(f"CREATE DATABASE {database} DEFAULT CHARSET utf8mb4")
        try:
            cursor.execute(f"USE {database}")
            count = sum(verify(cursor, parser) for parser in ("beng", "ik"))
        finally:
            cursor.execute(f"DROP DATABASE {database}")
    print(f"Passed {count} DDL/DML result comparisons.")


if __name__ == "__main__":
    with pymysql.connect(unix_socket=os.environ["FTS_TEST_SOCKET"], user="root",
                         charset="utf8mb4", autocommit=True) as connection:
        check_connection(connection)
