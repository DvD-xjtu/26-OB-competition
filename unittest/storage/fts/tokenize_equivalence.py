"""Capture a reference before a tokenizer change, then compare the new server.
Usage: tokenize_equivalence.py capture|compare /path/to/reference.json
Connects to a dedicated local server using FTS_TEST_SOCKET.
"""
import json
import os
import random
import sys
import pymysql

rng = random.Random(817)
pieces = ['中华人民共和国', '研究生命起源', '南京市长江大桥', '数据库', 'OceanBase', 'ABC-def',
          'eMail@example.com', '123.45', '一百二十三公斤', '２０２６', 'テスト', '한글', '😀', '\t', ' ', '。', 'äÖß']
documents = ['', ' ', 'a', '人际关系', '中华人民共和国人民大会堂', ''.join(pieces)]
documents += [''.join(rng.choices(pieces, k=rng.randrange(1, 120))) for _ in range(100)]
ascii_chars = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 !@#$%^&*()-_=+[]{};:,.<>/?\\|\t\n\r\v\f'
documents += [''.join(rng.choices(ascii_chars, k=rng.randrange(1, 2000))) for _ in range(100)]
documents += ['hello\x00WORLD trailing', 'A' * 9000, 'UPPER lower MiXeD', '\t\r\n...---___']
documents += [('中文数据库 OceanBase 123 公斤。' * 1500), ('abcXYZ +test ' * 2000)]
connection = pymysql.connect(unix_socket=os.environ['FTS_TEST_SOCKET'], user='root', charset='utf8mb4')
results = []
with connection.cursor() as cursor:
    for mode in ['smart', 'max_word', 'beng']:
        options = json.dumps([{'output': 'all'}] if mode == 'beng' else [{'output': 'all'}, {'additional_args': [{'ik_mode': mode}]}])
        for document in documents:
            cursor.execute('select tokenize(%s, %s, %s) as tokens', (document, 'beng' if mode == 'beng' else 'ik', options))
            value = cursor.fetchone()[0]
            def canonical(value):
                if isinstance(value, dict):
                    return {key: canonical(item) for key, item in sorted(value.items())}
                if isinstance(value, list):
                    return sorted((canonical(item) for item in value), key=lambda item: json.dumps(item, sort_keys=True))
                return value
            results.append(canonical(json.loads(value)) if value else value)
from pathlib import Path
reference = Path(sys.argv[2])
if sys.argv[1] == 'capture':
    reference.write_text(json.dumps(results, ensure_ascii=False), encoding='utf-8')
else:
    expected = json.loads(reference.read_text(encoding='utf-8'))
    assert len(results) == len(expected)
    for index, (actual, wanted) in enumerate(zip(results, expected)):
        assert actual == wanted, ('changed tokenization', index, actual, wanted)
print('PASS', len(results), 'document/mode cases including token frequencies and long segmented inputs')
