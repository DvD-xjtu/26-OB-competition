"""Capture on the reference binary, compare on the candidate using the same connection settings.

python tokenize_histogram_regression.py capture reference.json
python tokenize_histogram_regression.py compare reference.json
Set FTS_TEST_SOCKET, or FTS_TEST_HOST and FTS_TEST_PORT for a local TCP server.
"""
import argparse
import json
import os
from pathlib import Path

import pymysql


def run_queries(cursor):
    documents = [
        "", "the THE ThE", "CAFÉ cafe CAFE café", "Alpha alpha BETA Beta alpha",
        "42公斤 42公斤 一百公斤 数据库数据库", "l'été Straße café École，研究生命起源",
        " ".join(f"term{i} TERM{i}" for i in range(320)),
        ("数据库 abc123，十公斤 test；" * 180),
    ]
    options = [
        ("beng", None), ("ik", None), ("space", None), ("ngram", None), ("ngram2", None),
        ("beng", [{"output": "all"}]), ("ik", [{"output": "all"}]),
        ("ik", [{"additional_args": [{"ik_mode": "max_word"}]}]),
        ("beng", [{"additional_args": [{"min_token_size": 2}, {"max_token_size": 12}]}]),
        ("ik", [{"additional_args": [{"ik_mode": "unsupported"}]}]),
    ]
    rows = []
    for parser, args in options:
        for document in documents:
            sql = "SELECT TOKENIZE(%s,%s)" if args is None else "SELECT TOKENIZE(%s,%s,%s)"
            params = (document, parser) if args is None else (document, parser, json.dumps(args))
            try:
                cursor.execute(sql, params)
                value = cursor.fetchone()[0]
                # Preserve token array order and spelling, including repeated/overlapping tokens.
                rows.append({"value": json.loads(value) if value is not None else None})
            except pymysql.MySQLError as error:
                if args != options[-1][1]:
                    raise
                rows.append({"error": error.args[0]})
    return rows


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("action", choices=["capture", "compare"])
    cli.add_argument("path", type=Path)
    args = cli.parse_args()
    with pymysql.connect(unix_socket=os.getenv("FTS_TEST_SOCKET"),
                         host=os.getenv("FTS_TEST_HOST", "127.0.0.1"),
                         port=int(os.getenv("FTS_TEST_PORT", "2881")),
                         user="root", charset="utf8mb4") as conn, conn.cursor() as cursor:
        actual = run_queries(cursor)
    if args.action == "capture":
        args.path.write_text(json.dumps(actual, ensure_ascii=False), encoding="utf-8")
    else:
        expected = json.loads(args.path.read_text(encoding="utf-8"))
        if len(actual) != len(expected):
            raise ValueError("Unexpected number of cases in reference")
        for index, (before, after) in enumerate(zip(expected, actual)):
            if before != after:
                raise AssertionError(f"Different ordered token output or SQL error at case {index}")
    print(f"{args.action}: {len(actual)} cases")
