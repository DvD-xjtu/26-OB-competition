"""Check omitted TOKENIZE options against explicit defaults and error behavior.
Usage: FTS_TEST_SOCKET=... python tokenize_default_options.py [capture|compare reference.json]
Run capture on the pre-change server and compare on the candidate for exact errors
and explicit custom-option controls. No database objects are created or modified.
"""
import json
import os
import sys
from pathlib import Path

import pymysql


def canonical(value):
    if isinstance(value, dict):
        return {key: canonical(item) for key, item in sorted(value.items())}
    if isinstance(value, list):
        return sorted((canonical(item) for item in value), key=lambda item: json.dumps(item, sort_keys=True))
    return value


connection = pymysql.connect(
    unix_socket=os.environ["FTS_TEST_SOCKET"], user="root", charset="utf8mb4"
)
results = []
with connection.cursor() as cursor:
    def run(query, parameters=()):
        try:
            cursor.execute(query, parameters)
            value = cursor.fetchone()[0]
            outcome = ["ok", canonical(json.loads(value)) if value is not None else None]
        except pymysql.Error as error:
            if error.args[0] in (2003, 2006, 2013, 2055):
                raise
            outcome = ["error", error.args[0], error.args[1]]
        results.append([query, list(parameters), outcome])
        return outcome

    documents = [None, "", "a an the ABC alpha ALPHA 12", "中文 数据库 OceanBase 123 公斤", "hello\x00WORLD", "A" * 90]
    for parser in [None, "space", "beng", "ik", "ngram", "ngram2", " BENG ", "Ik", "", " ", "unknown"]:
        for document in documents:
            implicit = run("select tokenize(%s,%s)", (document, parser))
            explicit = run("select tokenize(%s,%s,%s)", (document, parser, "[]"))
            assert implicit == explicit, ("default options changed", document, parser, implicit, explicit)
    for document in documents:
        implicit = run("select tokenize(%s)", (document,))
        explicit = run("select tokenize(%s,%s,%s)", (document, None, "[]"))
        assert implicit == explicit, ("default parser changed", document, implicit, explicit)
    for parser in ["space", "beng", "ik"]:
        for expression in ["convert(%s using latin1)", "convert(%s using utf16)", "convert(%s using utf8mb4) collate utf8mb4_general_ci"]:
            implicit = run("select tokenize(" + expression + ",%s)", ("ABC alpha 123", parser))
            explicit = run("select tokenize(" + expression + ",%s,%s)", ("ABC alpha 123", parser, "[]"))
            assert implicit == explicit, ("collation behavior changed", expression, parser, implicit, explicit)
    # Explicit valid controls exercise output mode, token size and IK ambiguity.
    for parser, options in [
        ("beng", [{"output": "all"}]),
        ("beng", [{"additional_args": [{"min_token_size": 1}, {"max_token_size": 20}]}]),
        ("ik", [{"output": "all"}, {"additional_args": [{"ik_mode": "max_word"}]}]),
        ("ngram", [{"additional_args": [{"ngram_token_size": 1}]}]),
    ]:
        outcome = run("select tokenize(%s,%s,%s)", ("研究生命起源 ABC alpha alpha 12", parser, json.dumps(options)))
        assert outcome[0] == "ok", (parser, options, outcome)
    # Error controls must still reach the original parser/options validation.
    for parser, options in [
        ("beng", "{}"), ("ik", "null"), ("space", "[null]"), ("beng", "["),
        ("beng", '[{"output":"invalid"}]'),
        ("ik", '[{"case":"upper"}]'),
        ("beng", '[{"stopwords":"alpha"}]'),
        ("beng", '[{"additional_args":[{"min_token_size":0}]}]'),
        ("ik", '[{"additional_args":[{"ik_mode":"invalid"}]}]'),
    ]:
        outcome = run("select tokenize(%s,%s,%s)", ("alpha 中华人民共和国", parser, options))
        assert outcome[0] == "error", (parser, options, outcome)
    for query in ["select tokenize()", "select tokenize('alpha','beng','[]','extra')"]:
        assert run(query)[0] == "error", query
connection.close()
if len(sys.argv) > 1:
    reference = Path(sys.argv[2])
    if sys.argv[1] == "capture":
        reference.write_text(json.dumps(results, ensure_ascii=False), encoding="utf-8")
    elif sys.argv[1] == "compare":
        expected = json.loads(reference.read_text(encoding="utf-8"))
        assert len(results) == len(expected), (len(results), len(expected))
        for index, (actual, wanted) in enumerate(zip(results, expected)):
            assert actual == wanted, ("TOKENIZE defaults/options changed", index, actual, wanted)
    else:
        raise ValueError("expected capture or compare")
print("PASS", len(results), "TOKENIZE default, explicit option, collation and error checks")
