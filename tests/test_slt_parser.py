"""sqllogictest 文件解析单元测试。"""

import os
import tempfile
import unittest

from sqldb0.runner.slt_parser import (parse_test_file, SLTParseError,
                                      StatementRecord, QueryRecord,
                                      ControlRecord)


def _parse(text):
    with tempfile.NamedTemporaryFile("w", suffix=".test", delete=False) as f:
        f.write(text)
        path = f.name
    try:
        return parse_test_file(path)
    finally:
        os.unlink(path)


class TestParser(unittest.TestCase):
    def test_statement_ok(self):
        recs = _parse("statement ok\nCREATE TABLE t1(a INTEGER)\n")
        self.assertEqual(len(recs), 1)
        r = recs[0]
        self.assertIsInstance(r, StatementRecord)
        self.assertEqual(r.expect, "ok")
        self.assertEqual(r.sql, "CREATE TABLE t1(a INTEGER)")

    def test_statement_error(self):
        recs = _parse("statement error\nDROP TABLE nope\n")
        self.assertEqual(recs[0].expect, "error")

    def test_statement_count(self):
        recs = _parse("statement count 3\nINSERT INTO t1 VALUES(1),(2),(3)\n")
        r = recs[0]
        self.assertEqual(r.expect, "count")
        self.assertEqual(r.count, 3)

    def test_query_basic(self):
        recs = _parse("query I rowsort\nSELECT a FROM t1\n----\n1\n2\n3\n")
        r = recs[0]
        self.assertIsInstance(r, QueryRecord)
        self.assertEqual(r.type_string, "I")
        self.assertEqual(r.sort_mode, "rowsort")
        self.assertEqual(r.sql, "SELECT a FROM t1")
        self.assertEqual(r.expected, ["1", "2", "3"])

    def test_query_default_sort(self):
        recs = _parse("query IT\nSELECT a, b FROM t1\n----\n1\nx\n")
        self.assertEqual(recs[0].sort_mode, "nosort")

    def test_query_label(self):
        recs = _parse("query I rowsort label-xyz\nSELECT a FROM t1\n----\n1\n")
        self.assertEqual(recs[0].label, "label-xyz")

    def test_query_no_results(self):
        recs = _parse("query I\nSELECT a FROM t1 WHERE 0\n")
        self.assertIsNone(recs[0].expected)

    def test_query_column_counts(self):
        recs = _parse("query I\nSELECT a FROM t1\n---- 1\n1\n")
        self.assertEqual(recs[0].column_counts, [1])

    def test_query_hash_result(self):
        recs = _parse("query I\nSELECT a FROM t1\n----\n"
                      "3 values hashing to abc123\n")
        self.assertEqual(recs[0].expected_hash, "3 values hashing to abc123")

    def test_hash_threshold(self):
        recs = _parse("hash-threshold 8\nstatement ok\nSELECT 1\n")
        r = recs[0]
        self.assertIsInstance(r, ControlRecord)
        self.assertEqual(r.kind, "hash-threshold")
        self.assertEqual(r.value, 8)

    def test_halt(self):
        recs = _parse("halt\nstatement ok\nSELECT 1\n")
        self.assertEqual(recs[0].kind, "halt")

    def test_comments_ignored(self):
        recs = _parse("# comment\nstatement ok\nSELECT 1\n# mid\n")
        self.assertEqual(len(recs), 1)

    def test_conditionals(self):
        recs = _parse("skipif mssql\nstatement ok\nSELECT 1\n\n"
                      "onlyif sqlite\nquery I\nSELECT 1\n----\n1\n")
        self.assertEqual(recs[0].conditionals, [("skipif", "mssql")])
        self.assertEqual(recs[1].conditionals, [("onlyif", "sqlite")])

    def test_multiline_sql(self):
        recs = _parse("statement ok\nCREATE TABLE t1(\n  a INTEGER,\n  b TEXT\n)\n")
        self.assertEqual(recs[0].sql,
                        "CREATE TABLE t1(\n  a INTEGER,\n  b TEXT\n)")

    def test_unknown_record(self):
        with self.assertRaises(SLTParseError):
            _parse("frobnicate\nSELECT 1\n")

    def test_blank_lines_separate_records(self):
        recs = _parse("statement ok\nSELECT 1\n\n\nstatement ok\nSELECT 2\n")
        self.assertEqual(len(recs), 2)


if __name__ == "__main__":
    unittest.main()
