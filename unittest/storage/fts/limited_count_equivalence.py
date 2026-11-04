"""Compare limited FTS counts and order-sensitive controls to a prior binary.

capture/compare REFERENCE; FTS_TEST_SOCKET selects a dedicated local server.
The dedicated fts_limited_count_regression database is rebuilt on each run.
"""
import json
import os
from pathlib import Path
import sys
import pymysql

connection = pymysql.connect(unix_socket=os.environ["FTS_TEST_SOCKET"],
                             user="root", charset="utf8mb4", autocommit=True)
results = []
with connection.cursor() as cursor:
    cursor.execute("create database if not exists fts_limited_count_regression")
    cursor.execute("use fts_limited_count_regression")
    cursor.execute("drop table if exists docs")
    cursor.execute("create table docs(id bigint primary key, body varchar(1000), "
                   "fulltext index ft(body) with parser beng)")
    cursor.executemany("insert into docs values(%s,%s)",
                       [(i, "alpha " * (i % 7 + 1) + ["beta", "gamma", "other"][i % 3])
                        for i in range(1, 81)] + [(81, None), (82, "")])
    for phase in range(3):
        if phase == 1:
            cursor.execute("delete from docs where id between 20 and 30")
            cursor.execute("update docs set body='gamma changed' where id % 5=0")
        elif phase == 2:
            cursor.execute("begin")
            cursor.execute("insert into docs values(99,'alpha private beta')")
        for text in ["alpha beta", "absent", "", "the"]:
            predicate = cursor.mogrify("match(body) against(%s)", (text,))
            for limit, offset in [(0, 0), (1, 0), (20, 0), (20, 15), (200, 0), (5, 200)]:
                inner = "select id from docs where " + predicate + f" limit {limit} offset {offset}"
                queries = [
                    "select count(*) from (" + inner + ") selected",
                    "select count(id), sum(id), min(id), max(id) from (" + inner + ") selected",
                    "select count(*) from (" + inner + ") selected where id>40",
                    "select count(*) from (select distinct body from docs where " + predicate
                    + f" limit {limit} offset {offset}) selected",
                    "select count(*) from (select id from docs where " + predicate
                    + f" order by id desc limit {limit} offset {offset}) selected",
                ]
                for query in queries:
                    cursor.execute(query)
                    results.append([phase, query, cursor.fetchall()])
            # A projected numeric score must retain BM25 even when the outer
            # query only counts; keep the restriction explicit in plan checks.
            query = "select count(*) from (select id," + predicate + " score from docs where " + predicate + " limit 20) selected"
            cursor.execute(query)
            results.append([phase, query, cursor.fetchall()])
        if phase == 2:
            cursor.execute("rollback")
    if sys.argv[1] == "compare":
        cursor.execute("explain extended select count(*) from (select id from docs "
                       "where match(body) against('alpha beta') limit 20) selected")
        plan = "\n".join(str(row[0]) for row in cursor.fetchall())
        assert "calc_relevance=false" in plan, plan
        assert "is_index_back=false" in plan, plan
        # An order-sensitive aggregate and an outer filter must retain ranking.
        for projection, suffix in [("sum(id)", ""), ("count(*)", " where id>40")]:
            cursor.execute("explain extended select " + projection + " from (select id from docs "
                           "where match(body) against('alpha beta') limit 20) selected" + suffix)
            plan = "\n".join(str(row[0]) for row in cursor.fetchall())
            assert "calc_relevance=true" in plan, plan
serialized = json.loads(json.dumps(results, default=str))
reference = Path(sys.argv[2])
if sys.argv[1] == "capture":
    reference.write_text(json.dumps(serialized), encoding="utf-8")
else:
    expected = json.loads(reference.read_text(encoding="utf-8"))
    assert len(serialized) == len(expected)
    for i, (actual, wanted) in enumerate(zip(serialized, expected)):
        assert actual == wanted, (i, actual, wanted)
print("PASS", len(results), "limited count, value/filter/order controls and transaction cases")
