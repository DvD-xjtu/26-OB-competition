"""Physical FTS-index oracle for DDL-versus-DML construction tests.

MATCH scores are not an exact cross-storage oracle: seekdb's average-document-
length estimator scans a major SSTable only. A bulk-built index has that data,
whereas a just-inserted index can still use the default average of 10. These
helpers instead compare all actual postings, including their document lengths.
"""

def quoted(name):
    return "`" + name.replace("`", "``") + "`"


def postings(cursor, table):
    cursor.execute("set session ob_enable_index_direct_select=1")
    cursor.execute(
        "select t.table_id from oceanbase.__all_table t "
        "join oceanbase.__all_database d on t.database_id=d.database_id "
        "where d.database_name=database() and t.table_name=%s and t.index_type=0", (table,))
    found = cursor.fetchall()
    assert len(found) == 1, (table, "base table not uniquely found", found)
    cursor.execute(
        "select index_type,table_name from oceanbase.__all_table "
        "where data_table_id=%s and index_type in (12,13,14)", (found[0][0],))
    indexes = dict(cursor.fetchall())
    assert set(indexes) == {12,13,14}, (table, "expected doc mapping and both FTS indexes", indexes)
    cursor.execute("select * from " + quoted(indexes[12]))
    names = [column[0] for column in cursor.description]
    key_column = names.index("id")
    doc_column = next(i for i,name in enumerate(names) if name.startswith("__doc_id"))
    document_keys = {row[doc_column]:row[key_column] for row in cursor.fetchall()}
    outputs = []
    for index_type in (13,14):
        cursor.execute("select * from " + quoted(indexes[index_type]))
        names = [column[0] for column in cursor.description]
        doc = next(i for i,name in enumerate(names) if name.startswith("__doc_id"))
        word = next(i for i,name in enumerate(names) if name.startswith("__word_segment"))
        freq = next(i for i,name in enumerate(names) if name.startswith("__word_count"))
        length = next(i for i,name in enumerate(names) if name.startswith("__doc_length"))
        outputs.append(sorted((document_keys[row[doc]],row[word],row[freq],row[length])
                              for row in cursor.fetchall()))
    assert outputs[0] == outputs[1], (table, "inverted and forward postings differ")
    return outputs[0]


def assert_build_indexes_equal(cursor):
    bulk = postings(cursor,"bulk_docs")
    incremental = postings(cursor,"dml_docs")
    assert bulk == incremental, ("bulk/DML postings differ", len(bulk), len(incremental))
    return len(bulk)
