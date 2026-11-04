"""SQL oracle for compact/group and sliced COUNT(*), NULL and DISTINCT semantics."""
import os
import uuid

import pymysql

def check(conn):
    rows=[(i,(i*7)%23,None if i%5==0 else (i*11)%37) for i in range(5120)]
    bounds=[(0,5119),(1,5118),(43,63),(63,64),(64,65),(127,128),(255,256),
            (253,513),(777,2099),(5119,5119),(5200,5217)]
    masks=[("1=1",lambda i:True),("MOD(id, 11) IN (0,2,9)",lambda i: i%11 in (0,2,9)),
           ("MOD(id, 251)=3",lambda i:i%251==3),("v IS NULL",lambda i:i%5==0),
           ("1=0",lambda i:False)]
    db="count_bitmap_"+uuid.uuid4().hex
    cases=0
    with conn.cursor() as c:
        c.execute("CREATE DATABASE "+db)
        try:
            c.execute("USE "+db)
            c.execute("CREATE TABLE records(id INT PRIMARY KEY,gid INT NOT NULL,v INT NULL)")
            c.executemany("INSERT INTO records VALUES(%s,%s,%s)", rows)
            for lo,hi in bounds:
                for clause,filt in masks:
                    source=[row for row in rows if lo<=row[0]<=hi and filt(row[0])]
                    def counts(items):
                        nonnull=[r[2] for r in items if r[2] is not None]
                        return len(items),len(nonnull),len(set(nonnull))
                    condition=f" FROM records WHERE id BETWEEN %s AND %s AND ({clause})"
                    c.execute("SELECT COUNT(*),COUNT(v),COUNT(DISTINCT v)"+condition,(lo,hi))
                    assert c.fetchone()==counts(source),(lo,hi,clause,counts(source))
                    cases+=1
                    # Isolate the argument-free scalar aggregate from the DISTINCT plan.
                    c.execute("SELECT COUNT(*)"+condition,(lo,hi))
                    assert c.fetchone()==(len(source),),(lo,hi,clause)
                    cases+=1
                    grouped={}
                    for item in source:grouped.setdefault(item[1],[]).append(item)
                    expected=[(g,*counts(grouped[g])) for g in sorted(grouped) if len(grouped[g])>=3]
                    c.execute("SELECT gid,COUNT(*),COUNT(v),COUNT(DISTINCT v)"+condition+
                              " GROUP BY gid HAVING COUNT(*) >= 3 ORDER BY gid",(lo,hi))
                    assert list(c)==expected,(lo,hi,clause)
                    cases+=1
        finally:
            c.execute("DROP DATABASE "+db)
    print("Passed",cases,"bitmap COUNT, NULL, DISTINCT, GROUP BY and HAVING cases",flush=True)
    return cases


if __name__ == "__main__":
    settings = dict(user="root", charset="utf8mb4", autocommit=True)
    if os.environ.get("FTS_TEST_SOCKET"):
        settings["unix_socket"] = os.environ["FTS_TEST_SOCKET"]
    else:
        settings.update(host=os.environ.get("FTS_TEST_HOST", "127.0.0.1"),
                        port=int(os.environ["FTS_TEST_PORT"]))
    with pymysql.connect(**settings) as connection:
        check(connection)
