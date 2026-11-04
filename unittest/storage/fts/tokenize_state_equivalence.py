"""Compare BENG's default path with explicit defaults and verify optional SQL NULL.

Use a local disposable seekdb instance through FTS_TEST_SOCKET or
FTS_TEST_HOST/FTS_TEST_PORT. Inputs intentionally alternate across calls.
"""
import os

import pymysql


def check(connection):
    tests = 0
    texts = ["", None, "ALPHA alpha beta", "the THE about", "café cafe CAFE", "中文 ABC",
             "x\x00y", "word\nword", "x" * 512, "y" * 513, "alpha " * 84]
    texts = texts + texts[::-1] + ["database performance audit"] * 4
    with connection.cursor() as cursor:
        for collation in ("utf8mb4_bin", "utf8mb4_general_ci"):
            for text in texts:
                expression = f"CAST(%s AS CHAR CHARACTER SET utf8mb4) COLLATE {collation}"
                cursor.execute(f"SELECT TOKENIZE({expression},'beng') AS tokens", (text,))
                actual = cursor.fetchone()[0]
                cursor.execute(f"SELECT TOKENIZE({expression},'beng','[]') AS tokens", (text,))
                assert actual == cursor.fetchone()[0], (collation, text)
                tests += 1
        cursor.execute("SET @fts_argument_counter=0")
        for expected in range(1, 5):
            cursor.execute("SELECT TOKENIZE(CONCAT('word',@fts_argument_counter:=@fts_argument_counter+1),'beng') AS tokens")
            cursor.fetchone()
            cursor.execute("SELECT @fts_argument_counter")
            assert cursor.fetchone()[0] == expected
            tests += 1
        for parser in ("beng", "ik", "space"):
            for text in ("", None, "A café alphabet 中文 42 kg.", "single repeated repeated"):
                cursor.execute("SELECT TOKENIZE(CAST(%s AS CHAR CHARACTER SET utf8mb4),%s),"
                               "TOKENIZE(CAST(%s AS CHAR CHARACTER SET utf8mb4),%s,NULL),"
                               "TOKENIZE(CAST(%s AS CHAR CHARACTER SET utf8mb4),%s,'[]')",
                               (text, parser, text, parser, text, parser))
                omitted, sql_null, explicit = cursor.fetchone()
                assert omitted == sql_null == explicit, (parser, text)
                tests += 1
        for options in ("null", "false", "3", "{}", '[{"unknown-option":1}]'):
            try:
                cursor.execute("SELECT TOKENIZE('abc','beng',%s)", (options,))
            except pymysql.MySQLError as error:
                assert error.args[0] == 1210, (options, error.args)
            else:
                raise AssertionError(("Expected invalid parser properties", options))
            tests += 1
    print(f"Passed {tests} tokenizer execution-state checks", flush=True)


if __name__ == "__main__":
    with pymysql.connect(unix_socket=os.getenv("FTS_TEST_SOCKET"),
                         host=os.getenv("FTS_TEST_HOST", "127.0.0.1"),
                         port=int(os.getenv("FTS_TEST_PORT", "2881")), user="root",
                         charset="utf8mb4", autocommit=True) as connection:
        check(connection)
