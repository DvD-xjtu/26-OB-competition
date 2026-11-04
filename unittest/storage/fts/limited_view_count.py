"""Exercise cardinality-only full-text views on a local, disposable seekdb instance.

Set FTS_TEST_SOCKET to a local MySQL socket. With the optimized binary, pass
--check-plan to also verify that the positive query takes the unscored path.
"""
import argparse
import os
import uuid

import pymysql


def run(connection, check_plan=False):
    database = "fts_limit_test_" + uuid.uuid4().hex
    cases = 0
    with connection.cursor() as cur:
        cur.execute("CREATE DATABASE " + database)
        try:
            cur.execute("USE " + database)
            cur.execute("CREATE TABLE docs (id INT PRIMARY KEY, txt VARCHAR(160), "
                        "tag INT, FULLTEXT INDEX ft(txt) WITH PARSER beng)")
            rows = [(i, ("alpha " * (i % 4) + "beta " * (i % 3) + "document").strip(),
                     i if i % 3 else None) for i in range(1, 81)]
            cur.executemany("INSERT INTO docs VALUES (%s,%s,%s)", rows)
            for phase in range(2):
                if phase:
                    cur.execute("UPDATE docs SET txt='unmatched' WHERE id BETWEEN 10 AND 32")
                    cur.execute("DELETE FROM docs WHERE id BETWEEN 60 AND 67")
                    rows = [(i, "unmatched" if 10 <= i <= 32 else text, tag)
                            for i, text, tag in rows if not 60 <= i <= 67]
                for term in ("alpha", "alpha beta", "missing"):
                    matching = {i for i, text, _ in rows if set(text.split()) & set(term.split())}
                    for limit, offset in ((0, 0), (1, 0), (7, 4), (20, 0), (5, 1000)):
                        query = ("SELECT COUNT(*) FROM (SELECT id FROM docs WHERE "
                                 "MATCH(txt) AGAINST(%s) LIMIT %s OFFSET %s) v")
                        cur.execute(query, (term, limit, offset))
                        expected = min(limit, max(0, len(matching) - offset))
                        assert cur.fetchone()[0] == expected, (phase, term, limit, offset)
                        cases += 1
                # Row identity and computed score matter to these consumers.
                ranked = ("SELECT tag, MATCH(txt) AGAINST('alpha beta') score FROM docs "
                          "WHERE MATCH(txt) AGAINST('alpha beta') ORDER BY score DESC,id LIMIT 7")
                cur.execute(ranked)
                top = cur.fetchall()
                cur.execute("SELECT COUNT(tag), MAX(score) FROM (" + ranked + ") v")
                assert cur.fetchone() == (sum(row[0] is not None for row in top),
                                          max(row[1] for row in top))
                cases += 1
                cur.execute("SELECT COUNT(*) FROM (" + ranked + ") v WHERE tag IS NOT NULL")
                assert cur.fetchone()[0] == sum(row[0] is not None for row in top)
                cases += 1
            if check_plan:
                def explain(sql):
                    cur.execute("EXPLAIN EXTENDED " + sql)
                    return "\n".join(str(field) for row in cur for field in row).lower()

                limited = "SELECT id FROM docs WHERE MATCH(txt) AGAINST('alpha beta') LIMIT 7"
                plan = explain("SELECT COUNT(*) FROM (" + limited + ") v")
                assert "calc_relevance=false" in plan and "sort_keys([match" not in plan, plan
                assert "is_index_back=false" in plan, plan
                cur.execute("SELECT COUNT(*) FROM (" + limited + ") v")
                assert cur.fetchone()[0] == 7
                for sql in (limited, "SELECT MAX(id) FROM (" + limited + ") v",
                            "SELECT COUNT(*) FROM (" + ranked + ") v"):
                    plan = explain(sql)
                    assert "calc_relevance=true" in plan and ("sort_keys([match" in plan or "|sort " in plan), plan
        finally:
            cur.execute("DROP DATABASE " + database)
    return cases


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-plan", action="store_true")
    args = parser.parse_args()
    with pymysql.connect(unix_socket=os.environ["FTS_TEST_SOCKET"], user="root",
                         charset="utf8mb4", autocommit=True) as connection:
        print("PASS", run(connection, args.check_plan), "limited-view correctness cases")
