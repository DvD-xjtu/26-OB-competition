"""Validate DDL and DML postings spanning four possible vector boundaries."""
import itertools
import os
import string
import uuid

import pymysql


def check(conn):
    letters = ("q" + "".join(chars) + "suffix" for chars in itertools.product(string.ascii_lowercase, repeat=3))
    words = list(itertools.islice(letters, 601))
    texts = {
        7: None, 9: "", 11: " and the the ", 21: " ".join(words[:255]),
        31: " ".join(words[:256]), 43: " ".join(words[:257]), 67: " ".join(words),
        71: "rankmark " * 8 + " otherterm", 75: "rankmark " + "otherterm " * 8,
        90: "tailsentinel",
    }
    tmp = "fts_batch_" + uuid.uuid4().hex
    checks = 0
    with conn.cursor() as cur:
        cur.execute("CREATE DATABASE " + tmp + " DEFAULT CHARSET utf8mb4")
        try:
            cur.execute("USE " + tmp)
            for parser in ("beng", "ik"):
                tables = ("ddl_" + parser, "dml_" + parser)
                for table in tables:
                    cur.execute(f"CREATE TABLE {table} (pk BIGINT PRIMARY KEY, body TEXT)")
                    if table == tables[1]:
                        cur.execute(f"ALTER TABLE {table} ADD FULLTEXT INDEX ft(body) WITH PARSER {parser}")
                    cur.executemany(f"INSERT INTO {table} VALUES (%s,%s)", list(texts.items()))
                    if table == tables[0]:
                        cur.execute(f"ALTER TABLE {table} ADD FULLTEXT INDEX ft(body) WITH PARSER {parser}")
                for phase in range(2):
                    source = dict(texts)
                    if phase:
                        for table in tables:
                            cur.execute(f"UPDATE {table} SET body='replacementonly' WHERE pk=67")
                            cur.execute(f"DELETE FROM {table} WHERE pk=31")
                        source.pop(31)
                        source[67] = "replacementonly"
                    for term in words + ["tailsentinel", "replacementonly"]:
                        expected = sorted(k for k, text in source.items() if term in (text or "").split())
                        for table in tables:
                            cur.execute(f"SELECT pk FROM {table} WHERE MATCH(body) AGAINST(%s) ORDER BY pk", (term,))
                            actual = [row[0] for row in cur]
                            assert actual == expected, (parser, table, phase, term, expected, actual)
                            checks += 1
                    for table in tables:
                        for term, expected in (("rankmark", [71, 75]), ("otherterm", [75, 71])):
                            cur.execute(f"SELECT pk FROM {table} WHERE MATCH(body) AGAINST(%s) "
                                        "ORDER BY MATCH(body) AGAINST(%s) DESC, pk", (term, term))
                            assert [r[0] for r in cur] == expected, (parser, table, phase, term)
                            checks += 1
                # On a heap, the internal integer document ID also has to locate
                # the correct base row. A COUNT over the inverted index cannot test this.
                heap = 'heap_' + parser
                cur.execute(f"CREATE TABLE {heap} (id BIGINT, title VARCHAR(64), body TEXT) "
                            "DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci")
                cur.executemany(f"INSERT INTO {heap} VALUES (%s,%s,%s)",
                                [(1, 'alpha cafe', 'café deep Résumé'), (2, 'ALPHA CAFe', 'CAFE résumé résumé 中文 索引'),
                                 (3, None, None), (4, '', ' '), (5, 'other', 'unrelated')])
                cur.execute(f"ALTER TABLE {heap} ADD FULLTEXT INDEX ft(title,body) WITH PARSER {parser}")
                for expected in ([1, 2], [2]):
                    cur.execute(f"SELECT id FROM {heap} WHERE MATCH(title,body) AGAINST('CAFE') ORDER BY id")
                    assert [row[0] for row in cur] == expected, (parser, heap, expected)
                    if len(expected) == 2:
                        cur.execute(f"DELETE FROM {heap} WHERE id=1")
                    checks += 1
        finally:
            cur.execute("DROP DATABASE " + tmp)
    print(f"Passed {checks} cross-batch posting and frequency queries", flush=True)


if __name__ == "__main__":
    with pymysql.connect(host=os.getenv("FTS_TEST_HOST", "127.0.0.1"),
                         port=int(os.getenv("FTS_TEST_PORT", "2881")),
                         unix_socket=os.getenv("FTS_TEST_SOCKET"),
                         user="root", charset="utf8mb4", autocommit=True) as conn:
        check(conn)

