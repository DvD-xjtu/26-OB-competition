"""Reference comparison for aggregate retrieval versus scored/ranked queries.
Run capture on the original binary and compare on the optimized binary.
Uses and rebuilds the dedicated fts_aggregate_regression database.
"""
import json
import os
import sys
from pathlib import Path
import pymysql

connection = pymysql.connect(unix_socket=os.environ['FTS_TEST_SOCKET'], user='root', charset='utf8mb4', autocommit=True)
results = []
with connection.cursor() as cursor:
    cursor.execute('create database if not exists fts_aggregate_regression')
    cursor.execute('use fts_aggregate_regression')
    cursor.execute('drop table if exists docs')
    cursor.execute('create table docs(id bigint primary key, content varchar(1000))')
    rows = [(i, 'common ' + ['alpha alpha beta', 'beta gamma', 'delta alpha', 'none'][i % 4]) for i in range(1, 101)]
    rows += [(101, ''), (102, None), (103, 'the a an and'), (104, '中文数据库 alpha alpha common'), (105, 'CAFÉ café Café'), (106, 'alpha ' * 120)]
    rows += [(i, 'common term' + str(i) + ' alpha' * (i % 7)) for i in range(107, 307)]
    cursor.executemany('insert into docs values(%s,%s)', rows)
    cursor.execute('alter table docs add fulltext index ft(content) with parser beng')
    for phase in range(3):
        if phase == 1:
            cursor.execute("update docs set content='common gamma changed' where id between 10 and 20")
            cursor.execute('delete from docs where id between 40 and 60')
        if phase == 2:
            cursor.execute('begin')
            cursor.execute("insert into docs values(999,'common alpha private')")
        for text in ['alpha beta', 'common', 'absent', '', 'the', 'gamma changed']:
            match = 'match(content) against(%s)'
            cases = [
                ('select count(*), sum(id), min(id), max(id), count(distinct content) from docs where ' + match, (text,)),
                ('select count(*) from docs where ' + match + ' and id > 15', (text,)),
                ('select count(*) from docs where (' + match + ' or id=101)', (text,)),
                ('select count(*) from docs where not (' + match + ')', (text,)),
                ('select round(sum(' + match + '),8) from docs', (text,)),
                ('select id, round(' + match + ',8) as score from docs where ' + match + ' order by score desc,id limit 7', (text,text)),
                ('select count(*) from (select id from docs where ' + match + ' limit 7) selected', (text,)),
                ('select count(*) from docs where match(content) against(%s in boolean mode)', (text,)),
            ]
            for threshold in [0, 0.01, 1, 100, 0]:
                cases.append(('select count(*) from docs where ' + match + ' > %s', (text,threshold)))
            for query, parameters in cases:
                try:
                    cursor.execute(query, parameters)
                except Exception:
                    print('FAILED', phase, query, parameters, flush=True)
                    raise
                results.append([phase,query,list(parameters),cursor.fetchall()])
        if phase == 2:
            cursor.execute('rollback')
reference = Path(sys.argv[2])
serialized = json.loads(json.dumps(results, default=str))
if sys.argv[1] == 'capture':
    reference.write_text(json.dumps(serialized), encoding='utf-8')
else:
    expected = json.loads(reference.read_text(encoding='utf-8'))
    assert len(serialized) == len(expected)
    for index,(actual,wanted) in enumerate(zip(serialized,expected)):
        assert actual == wanted, ('changed retrieval',index,actual,wanted)
print('PASS',len(results),'aggregate, score, ranking, threshold, DML and transaction cases')
