"""Check IK lexical-span reuse against the normal parser on a disposable seekdb.

Run with Python and PyMySQL: python ik_lexical_span_equivalence.py
Two independent pre-change controls produced the complete ordered fingerprints.
The collation accumulator uses unsigned long (LP64 on Linux x64, LLP64 on
Windows x64), so their hash-bucket iteration and JSON token orders can differ.
Default checks match all five fingerprints from a single control. For an
unrecognized platform, independently capture its old binary for comparison.
To compare two builds directly, run "capture /path/to/ref.json" on the old
server, then "compare /path/to/ref.json" on the new server. Set FTS_TEST_HOST,
FTS_TEST_PORT, FTS_TEST_SOCKET, FTS_TEST_DATABASE and FTS_TEST_USER as needed.
Use a database where the test may create and remove its own uniquely named table.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import uuid

import pymysql


OPTIONS = {
    "default": "[]",
    "all": '[{"output":"all"}]',
    "smart": '[{"additional_args":[{"ik_mode":"smart"}]}]',
    "max_word": '[{"additional_args":[{"ik_mode":"max_word"}]}]',
    "invalid": '[{"output":"invalid"}]',
}
CHALLENGE = [
    "", "   （）　", "数据库 IK-run", "CAFÉ cafe", "cafe CAFÉ", "国家研究生命起源",
    "三百二十五公斤", "ABC\x00def", "ß 㐀 鿿𠀀", "xyz " * 256, "xyz " * 257, "a b " * 190,
]
COLS = {"ik_literal": "ik", "beng_literal": "beng", "ik_generated": "ik", "beng_generated": "beng"}
LP64_CONTROL = {
    "prepared_and_warnings": "e57ba34dda208a75067070a80384b0614661c74c7fec2839d838825d46323259",
    "ik_literal": "1ba7e103abb3d33eba5b0324fd1c578ea95a04422ea4f7841987c3745dbb2bdd",
    "beng_literal": "5733059dd8d162459381413c0e847a80003033254d0a7bb80e30dcfb0d46b9c3",
    "ik_generated": "3a995d48af69166ff47d0a5fc9b9b22d9b9f14a7f70f91d8ca8297aac2cf455a",
    "beng_generated": "6c9b395116933f875fcd208e4580979e1a3f9365009be8d090d1e2d3de391e28",
}
LLP64_CONTROL = {
    "prepared_and_warnings": "d0ce2e516974bbed0b8a2206436608e63550478dcca16533b7a1e5c7c46a10f6",
    "ik_literal": "a20c318cda84aefb5c3bc207fd29855a6fc94b0a51035c12caf2b76175f5ff7f",
    "beng_literal": "e98f506398500750c76799dfacca78b3da9c399c3f5de9a33e84a30a767bd8c0",
    "ik_generated": "2b59f50a10778719d31f03ae77ba5ffc983550d59b9c94f98ee1fbdc276b410a",
    "beng_generated": "31c2b9468170d0afd18da222ad999ff00b7195427d0534d0873bd10b9e8d8f80"
}



# Historical LP64 fingerprint exposed for tools that captured a Linux reference.
REFERENCE = LP64_CONTROL


def connect():
    return pymysql.connect(host=os.getenv("FTS_TEST_HOST", "127.0.0.1"),
                           port=int(os.getenv("FTS_TEST_PORT", "2881")),
                           unix_socket=os.getenv("FTS_TEST_SOCKET"),
                           database=os.getenv("FTS_TEST_DATABASE", "test"),
                           user=os.getenv("FTS_TEST_USER", "root"), charset="utf8mb4",
                           autocommit=True, read_timeout=180)


def execute_bound(cursor, text, mode):
    cursor.execute("SET @x=%s,@p='ik',@opt=%s", (text, OPTIONS[mode]))
    try:
        cursor.execute("EXECUTE p USING @x,@p,@opt")
        answer = ["ok", cursor.fetchone()[0]]
    except pymysql.MySQLError as exc:
        answer = ["error", list(exc.args)]
    cursor.execute("SHOW WARNINGS")
    warnings = cursor.fetchall()
    if mode == "invalid":
        assert answer[0] == "error" and answer[1][0] == 1210, (text, mode, answer)
    else:
        assert answer[0] == "ok" and not warnings, (text, mode, answer, warnings)
    return answer, warnings


def prepared_and_warnings(primary, second):
    for cursor in (primary, second):
        cursor.execute("PREPARE p FROM 'SELECT TOKENIZE(?,?,?) AS t'")
        cursor.execute("SELECT CONNECTION_ID()")
    assert primary.fetchone() != second.fetchone(), "Two independent session scopes are required"
    digest = hashlib.sha256()
    for text in CHALLENGE:
        parsed = {}
        for mode in OPTIONS:
            first = None
            for index in range(5):
                cursor = second if index == 2 else primary
                answer, warnings = execute_bound(cursor, text, mode)
                outcome = json.dumps((answer, warnings), ensure_ascii=False).encode()
                if first is None:
                    first = outcome
                assert outcome == first, (text, mode, index, "fresh and repeated sessions differ")
                digest.update(outcome + b"\x00")
                if answer[0] == "ok":
                    parsed[mode] = json.loads(answer[1])
        assert parsed["default"] == parsed["smart"], text
        detail = parsed["all"]
        assert [next(iter(item)) for item in detail["tokens"]] == parsed["default"], text
        assert sum(next(iter(item.values())) for item in detail["tokens"]) == detail["doc_len"], text
        if "研究生命起源" in text:
            assert "研究生" in parsed["max_word"] and "研究生" not in parsed["smart"]
    for _ in range(3):
        for warning_first in (True, False):
            warning = "CAST('bad' AS UNSIGNED)"
            tokenizer = "TOKENIZE('内存 索引','ik')"
            expressions = (warning, tokenizer) if warning_first else (tokenizer, warning)
            primary.execute("SELECT " + ",".join(expressions))
            values = primary.fetchone()
            assert values[0 if warning_first else 1] == 0
            assert set(json.loads(values[1 if warning_first else 0])) == {"内存", "索引"}
            primary.execute("SHOW WARNINGS")
            warnings = primary.fetchall()
            assert len(warnings) == 1 and warnings[0][:2] == ("Warning", 1292), warnings
            digest.update(json.dumps((values, warnings), ensure_ascii=False).encode() + b"\x00")
    return digest.hexdigest()


def boundaries_and_expressions(cursor):
    for words in (127, 128, 129, 256, 257):
        for _ in range(4):
            answer, _ = execute_bound(cursor, "xyz " * words, "all")
            assert json.loads(answer[1]) == {"tokens": [{"xyz": words}], "doc_len": words}
    prefix = "xyz"
    for byte_count in (1023, 1024, 1025):
        text = prefix + " " * (byte_count - len(prefix.encode()))
        for _ in range(4):
            answer, _ = execute_bound(cursor, text, "default")
            assert json.loads(answer[1]) == [prefix], (byte_count, answer)
    for collation in ("utf8mb4_bin", "utf8mb4_general_ci", "utf8mb4_bin"):
        expr = f"CAST(%s AS CHAR CHARACTER SET utf8mb4) COLLATE {collation}"
        for i in range(5):
            text = ("测试 a", "测试 A")[i % 2]
            cursor.execute(f"SELECT TOKENIZE({expr},'ik')", (text,))
            assert "测试" in json.loads(cursor.fetchone()[0])
    cursor.execute("SET @n=0")
    for expected in range(1, 6):
        cursor.execute("SELECT TOKENIZE(IF((@n:=@n+1)>0,'研究生命起源',''), 'ik')")
        assert "生命" in json.loads(cursor.fetchone()[0])
        cursor.execute("SELECT @n")
        assert cursor.fetchone()[0] == expected, "Dynamic argument evaluation was skipped"


def column_checks(cursor, directory):
    bench = (directory / "fts_large_bench.sh").read_text(encoding="utf-8")
    fixed = {parser: re.search(r"^" + parser.upper() + r'_TEXT="([^"]+)"', bench, re.M)[1]
             for parser in ("ik", "beng")}
    make_row = runpy.run_path(str(directory / "fts_large_bench_gen.py"))["make_row"]
    table = "fts_ik_span_" + uuid.uuid4().hex
    fields = ",".join(name + " VARCHAR(1500) NOT NULL" for name in COLS)
    cursor.execute("SET ob_query_timeout=180000000")
    cursor.execute(f"CREATE TABLE {table} (id INT PRIMARY KEY,{fields}) "
                   "DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci")
    result = {}
    try:
        for first in range(0, 20000, 500):
            batch = []
            for i in range(first, first + 500):
                _, title, body, title_en, body_en = make_row(i)
                batch.append((i, fixed["ik"], fixed["beng"], title + " " + body, title_en + " " + body_en))
            cursor.executemany(f"INSERT INTO {table} VALUES (%s,%s,%s,%s,%s)", batch)
        cursor.execute("SELECT " + ",".join(f"COUNT(DISTINCT {col})" for col in COLS) + f" FROM {table}")
        assert tuple(cursor.fetchone()) == (1, 1, 20000, 20000)
        for col, parser in COLS.items():
            expr = f"CAST(TOKENIZE({col},'{parser}') AS CHAR)"
            cursor.execute(f"EXPLAIN EXTENDED SELECT SUM(OCTET_LENGTH({expr})) FROM {table}")
            plan = "\n".join(str(item) for row in cursor for item in row).lower()
            assert "tokenize" in plan and col in plan, (col, "Expected a dynamic column expression")
            cursor.execute(f"SELECT id,SHA2({expr},256) FROM {table} ORDER BY id")
            digest = hashlib.sha256()
            count = 0
            for row_id, signature in cursor:
                assert row_id == count and signature is not None
                count += 1
                digest.update(bytes.fromhex(signature))
            assert count == 20000
            result[col] = digest.hexdigest()
    finally:
        cursor.execute(f"DROP TABLE {table}")
    return result


def verify_fingerprints(result, expected=None):
    if expected is not None:
        assert result == expected, ("Raw fingerprints differ from the supplied control", result, expected)
    elif result != LP64_CONTROL and result != LLP64_CONTROL:
        raise AssertionError(("Unknown ordered fingerprint combination. Capture the pre-change "
                              "server on the same platform and use compare.", result))


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("action", choices=("check", "capture", "compare"), nargs="?", default="check")
    cli.add_argument("reference", type=Path, nargs="?")
    cli.add_argument("--benchmark-dir", type=Path,
                     default=Path(os.environ["FTS_BENCHMARK_PATH"]) if "FTS_BENCHMARK_PATH" in os.environ
                     else Path(__file__).resolve().parents[3] / "tools" / "benchmark")
    args = cli.parse_args()
    if args.action != "check" and args.reference is None:
        cli.error("capture and compare require a reference file")
    with connect() as primary, connect() as alternate, primary.cursor() as c, alternate.cursor() as d:
        result = {"prepared_and_warnings": prepared_and_warnings(c, d)}
        boundaries_and_expressions(c)
        result.update(column_checks(c, args.benchmark_dir))
    if args.action == "capture":
        args.reference.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    else:
        expected = (json.loads(args.reference.read_text(encoding="utf-8"))
                    if args.action == "compare" else None)
        verify_fingerprints(result, expected)
    print("Passed 306 prepared/warning cases, 52 boundary/collation/dynamic checks and 80,000 SQL rows.")


if __name__ == "__main__":
    main()
