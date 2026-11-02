import json
import sys
from pathlib import Path
import pymysql
sys.path.insert(0, 'tools/deploy/mysql_test/test_suite/ai_function/include')
from ai_enhancement_mock import embedding

connection = pymysql.connect(host='127.0.0.1', port=2881, user='root', autocommit=True)
with connection.cursor() as cursor:
    cursor.execute('CREATE DATABASE IF NOT EXISTS competition_test')
    cursor.execute('USE competition_test')
    pending = ''
    count = 0
    path = Path('tools/deploy/mysql_test/test_suite/ai_function/t/ai_function_enhancement.test')
    for line in path.read_text().splitlines():
        if not line.strip() or line.lstrip().startswith(('#', '--', 'connection ')):
            continue
        pending += line + '\n'
        if not line.rstrip().endswith(';'):
            continue
        statement, pending = pending, ''
        try:
            cursor.execute(statement)
            if cursor.description:
                print(cursor.fetchall(), flush=True)
            count += 1
        except pymysql.MySQLError as error:
            if 'DROP_AI_' in statement and error.args[0] in (11118, 11112):
                continue
            print(statement, flush=True)
            raise
    print('Public SQL statements passed:', count, flush=True)
    cursor.execute('DROP TABLE IF EXISTS embedding_mapping')
    for kind, name in [('MODEL','reg_embed'),('MODEL_ENDPOINT','reg_embed_ep'),('MODEL','reg_rerank'),('MODEL_ENDPOINT','reg_rerank_ep')]:
        try:
            cursor.execute('CALL DBMS_AI_SERVICE.DROP_AI_' + kind + '(%s)', (name,))
        except pymysql.MySQLError as error:
            if error.args[0] not in (11118,11112):
                raise
    cursor.execute("CALL DBMS_AI_SERVICE.CREATE_AI_MODEL('reg_embed', '{\"type\":\"dense_embedding\",\"model_name\":\"test-embedding\"}')")
    cursor.execute("CALL DBMS_AI_SERVICE.CREATE_AI_MODEL_ENDPOINT('reg_embed_ep', '{\"ai_model_name\":\"reg_embed\",\"scope\":\"all\",\"url\":\"http://127.0.0.1:8000/v1/embeddings\",\"access_key\":\"mock-key\",\"provider\":\"openai\"}')")
    cursor.execute('CREATE TABLE embedding_mapping (id INT PRIMARY KEY, content TEXT)')
    rows = [(i, None if i % 7 == 0 else 'Document number ' + str(i)) for i in range(150)]
    cursor.executemany('INSERT INTO embedding_mapping VALUES (%s,%s)', rows)
    cursor.execute("SELECT id, ai_embed('reg_embed',content,4) FROM embedding_mapping ORDER BY id")
    result = cursor.fetchall()
    assert len(result) == len(rows)
    for (i, actual), (_, content) in zip(result, rows):
        if content is None:
            assert actual is None, (i, actual)
        else:
            assert json.loads(actual) == embedding(content, 4), (i, actual)
    print('150-row reversed response and NULL mapping passed', flush=True)
    cursor.execute("CALL DBMS_AI_SERVICE.CREATE_AI_MODEL(%s,%s)", ('reg_rerank', json.dumps({'type':'rerank','model_name':'test-reranker'})))
    cursor.execute("CALL DBMS_AI_SERVICE.CREATE_AI_MODEL_ENDPOINT(%s,%s)", ('reg_rerank_ep', json.dumps({'ai_model_name':'reg_rerank','scope':'all','url':'http://127.0.0.1:8000/v1/rerank','access_key':'mock-key','provider':'siliconflow'})))
    docs = ['needle' if i % 3 == 0 else 'unrelated' for i in range(45)]
    expected = sorted(range(len(docs)), key=lambda i: (-(i % 3 == 0), i))
    cursor.execute("SELECT ai_rerank('reg_rerank','needle',%s)", (json.dumps(docs),))
    ranked = json.loads(cursor.fetchone()[0])
    assert [x['index'] for x in ranked] == expected, ranked
    objects = [{'id': str(i), 'text': text} for i, text in enumerate(docs)]
    cursor.execute("SELECT ai_rerank('reg_rerank','needle',%s,'text')", (json.dumps(objects),))
    ranked = json.loads(cursor.fetchone()[0])
    assert [x['id'] for x in ranked] == [str(i) for i in expected], ranked
    assert all(x['text'] == docs[int(x['id'])] for x in ranked)
    print('45-document cross-batch strings/objects reranking passed', flush=True)
