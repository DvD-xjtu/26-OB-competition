"""Compare COUNT-only MATCH to observed document identities across stream boundaries and MVCC."""
import argparse
import os
import uuid
import pymysql

def check(connection, observer=None, check_plan=False):
    db = "fts_membership_" + uuid.uuid4().hex
    terms = ["", "the", None, "absentterm", "arctic", "arctic arctic", "lynx",
             "arctic lynx", "lynx zebra panda", "arctic lynx zebra panda",
             "arctic lynx zebra panda magma", "edgeone", "edgelow", "edgeexact", "edgeplus"]
    checks = 0
    def read(cur, sql, args):
        try:
            cur.execute(sql, args)
            return None, cur.fetchall()
        except pymysql.MySQLError as error:
            return error.args[0], None

    def verify(cur, term, modifier="", numeric=False):
        nonlocal checks
        pred = "MATCH(body) AGAINST(%s)"
        if numeric:
            pred += " > 0.00001"
        where = " FROM docs WHERE " + pred + modifier
        code,rows = read(cur,"SELECT id" + where + " ORDER BY id",(term,))
        count_code,counts = read(cur,"SELECT COUNT(*)" + where,(term,))
        assert code==count_code, (term,modifier,code,count_code)
        if code is not None and term is not None:
            raise AssertionError((term,modifier,code))
        if code is None:
            assert counts == ((len(rows),),),(term,modifier,len(rows),counts)
        checks += 1
        return None if code is not None else len(rows)

    with connection.cursor() as c:
        c.execute("CREATE DATABASE "+db+" DEFAULT CHARSET=utf8mb4")
        try:
            c.execute("USE "+db)
            c.execute("CREATE TABLE docs(id INT PRIMARY KEY, body TEXT NULL, marked INT NULL, FULLTEXT INDEX ft(body) WITH PARSER beng)")
            rows=[]
            for i in range(1,2050):
                tokens=[term for modulus,term in ((2,"arctic"),(3,"lynx"),(5,"zebra"),(7,"panda"),(11,"magma")) if i % modulus == 0]
                for upper,term in ((1,"edgeone"),(255,"edgelow"),(256,"edgeexact"),(257,"edgeplus")):
                    if i<=upper: tokens.append(term)
                if i%13==0:tokens += ["arctic","arctic","the"]
                rows.append((i," ".join(tokens) if tokens else None, i if i%4 else None))
            c.executemany("INSERT INTO docs VALUES (%s,%s,%s)",rows)
            for term in terms:
                verify(c,term)
            for term,expected in (("edgeone",1),("edgelow",255),("edgeexact",256),("edgeplus",257)):
                assert verify(c,term)==expected
            for term in ("missingtoken","arctic","arctic lynx panda"):
                verify(c,term,modifier=" AND marked IS NULL")
                verify(c,term,numeric=True)
            if check_plan:
                c.execute("EXPLAIN EXTENDED SELECT COUNT(*) FROM docs WHERE MATCH(body) AGAINST('arctic lynx')")
                plan="\n".join(str(col) for row in c for col in row).lower()
                assert "calc_relevance=false" in plan and "pushdown_match_filter(bool(" not in plan,plan
            before = verify(c,"edgelow")
            for finish in ("ROLLBACK", "COMMIT"):
                c.execute("START TRANSACTION")
                c.execute("DELETE FROM docs WHERE id=2")
                c.execute("UPDATE docs SET body='replacement' WHERE id=3")
                c.execute("INSERT INTO docs VALUES(5000,'edgelow onecommitted',NULL)")
                inside=verify(c,"edgelow")
                if observer is not None:
                    with observer.cursor() as ro:
                        ro.execute("USE "+db)
                        assert verify(ro,"edgelow")==before
                c.execute(finish)
                assert verify(c,"edgelow")== (before if finish=="ROLLBACK" else inside)
                if observer is not None:
                    with observer.cursor() as ro:
                        assert verify(ro,"edgelow")== (before if finish=="ROLLBACK" else inside)
        finally:
            connection.rollback()
            c.execute("DROP DATABASE "+db)
    print("Passed", checks, "membership count / ranked identity comparisons", flush=True)
    return checks


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-plan", action="store_true")
    args = parser.parse_args()
    settings = dict(user="root", charset="utf8mb4", autocommit=True)
    if os.environ.get("FTS_TEST_SOCKET"):
        settings["unix_socket"] = os.environ["FTS_TEST_SOCKET"]
    else:
        settings.update(host=os.environ.get("FTS_TEST_HOST", "127.0.0.1"),
                        port=int(os.environ["FTS_TEST_PORT"]))
    with pymysql.connect(**settings) as connection, pymysql.connect(**settings) as observer:
        check(connection, observer, args.check_plan)
