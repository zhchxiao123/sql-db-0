"""sqllogictest runner 执行与报告单元测试。"""

import json
import os
import tempfile
import unittest

from sqldb0.engine import Engine
from sqldb0.runner.runner import run_file, run_path


def _write(text):
    with tempfile.NamedTemporaryFile("w", suffix=".test", delete=False) as f:
        f.write(text)
        return f.name


class TestRunner(unittest.TestCase):
    def setUp(self):
        self.engine = Engine()

    def test_all_pass(self):
        path = _write(
            "statement ok\nCREATE TABLE t1(a INTEGER)\n\n"
            "statement ok\nINSERT INTO t1 VALUES(1)\n\n"
            "query I rowsort\nSELECT a FROM t1\n----\n1\n")
        try:
            report = run_file(path, self.engine)
            self.assertEqual(report["summary"]["total"], 3)
            self.assertEqual(report["summary"]["passed"], 3)
            self.assertEqual(report["summary"]["failed"], 0)
        finally:
            os.unlink(path)

    def test_statement_error_expected(self):
        path = _write("statement error\nDROP TABLE nope\n")
        try:
            report = run_file(path, self.engine)
            self.assertEqual(report["summary"]["passed"], 1)
        finally:
            os.unlink(path)

    def test_statement_error_unexpected(self):
        path = _write("statement error\nSELECT 1\n")
        try:
            report = run_file(path, self.engine)
            self.assertEqual(report["summary"]["failed"], 1)
            self.assertIn("expected error", report["cases"][0]["detail"])
        finally:
            os.unlink(path)

    def test_statement_count_mismatch(self):
        path = _write("statement count 2\nINSERT INTO t1 VALUES(1)\n")
        try:
            self.engine.statement("CREATE TABLE t1(a INTEGER)")
            report = run_file(path, self.engine)
            self.assertEqual(report["summary"]["failed"], 1)
            self.assertIn("expected 2 rows affected, got 1",
                          report["cases"][0]["detail"])
        finally:
            os.unlink(path)

    def test_query_wrong_result(self):
        path = _write("query I\nSELECT 1\n----\n2\n")
        try:
            report = run_file(path, self.engine)
            self.assertEqual(report["summary"]["failed"], 1)
            self.assertIn("wrong result", report["cases"][0]["detail"])
        finally:
            os.unlink(path)

    def test_query_rowsort(self):
        path = _write("query I rowsort\nSELECT a FROM t1\n----\n1\n2\n3\n")
        try:
            self.engine.statement("CREATE TABLE t1(a INTEGER)")
            self.engine.statement("INSERT INTO t1 VALUES(3), (1), (2)")
            report = run_file(path, self.engine)
            self.assertEqual(report["summary"]["passed"], 1)
        finally:
            os.unlink(path)

    def test_query_valuesort(self):
        path = _write("query I valuesort\nSELECT a FROM t1\n----\n1\n2\n3\n")
        try:
            self.engine.statement("CREATE TABLE t1(a INTEGER)")
            self.engine.statement("INSERT INTO t1 VALUES(3), (1), (2)")
            report = run_file(path, self.engine)
            self.assertEqual(report["summary"]["passed"], 1)
        finally:
            os.unlink(path)

    def test_skipif(self):
        path = _write("skipif sqldb0\nquery I\nSELECT 1\n----\n1\n")
        try:
            report = run_file(path, self.engine)
            self.assertEqual(report["summary"]["skipped"], 1)
        finally:
            os.unlink(path)

    def test_onlyif_other_engine(self):
        path = _write("onlyif sqlite\nquery I\nSELECT 1\n----\n1\n")
        try:
            report = run_file(path, self.engine)
            self.assertEqual(report["summary"]["skipped"], 1)
        finally:
            os.unlink(path)

    def test_onlyif_this_engine(self):
        path = _write("onlyif sqldb0\nquery I\nSELECT 1\n----\n1\n")
        try:
            report = run_file(path, self.engine)
            self.assertEqual(report["summary"]["passed"], 1)
        finally:
            os.unlink(path)

    def test_halt_stops(self):
        path = _write("statement ok\nSELECT 1\n\nhalt\n\n"
                      "statement error\nSELECT 2\n")
        try:
            report = run_file(path, self.engine)
            self.assertEqual(report["summary"]["total"], 1)
        finally:
            os.unlink(path)

    def test_hash_threshold(self):
        path = _write("hash-threshold 2\n\n"
                      "query I\nSELECT a FROM t1\n----\n"
                      "3 values hashing to 00000000000000000000000000000000\n")
        try:
            self.engine.statement("CREATE TABLE t1(a INTEGER)")
            self.engine.statement("INSERT INTO t1 VALUES(1), (2), (3)")
            report = run_file(path, self.engine)
            # 哈希不匹配 -> 失败
            self.assertEqual(report["summary"]["failed"], 1)
        finally:
            os.unlink(path)

    def test_label_consistency(self):
        path = _write(
            "query I rowsort label-0\nSELECT a FROM t1\n----\n1\n2\n\n"
            "query I rowsort label-0\nSELECT a FROM t1\n----\n1\n2\n")
        try:
            self.engine.statement("CREATE TABLE t1(a INTEGER)")
            self.engine.statement("INSERT INTO t1 VALUES(1), (2)")
            report = run_file(path, self.engine)
            self.assertEqual(report["summary"]["passed"], 2)
        finally:
            os.unlink(path)

    def test_label_mismatch(self):
        path = _write(
            "query I rowsort label-0\nSELECT a FROM t1\n----\n1\n2\n\n"
            "statement ok\nINSERT INTO t1 VALUES(3)\n\n"
            "query I rowsort label-0\nSELECT a FROM t1\n----\n1\n2\n3\n")
        try:
            self.engine.statement("CREATE TABLE t1(a INTEGER)")
            self.engine.statement("INSERT INTO t1 VALUES(1), (2)")
            report = run_file(path, self.engine)
            self.assertEqual(report["summary"]["failed"], 1)
            self.assertIn("does not agree", report["cases"][2]["detail"])
        finally:
            os.unlink(path)

    def test_type_mismatch(self):
        path = _write("query I\nSELECT 'abc'\n----\nabc\n")
        try:
            report = run_file(path, self.engine)
            self.assertEqual(report["summary"]["failed"], 1)
            self.assertIn("type mismatch", report["cases"][0]["detail"])
        finally:
            os.unlink(path)

    def test_run_path_directory(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "a.test"), "w") as f:
                f.write("query I\nSELECT 1\n----\n1\n")
            with open(os.path.join(d, "b.test"), "w") as f:
                f.write("query I\nSELECT 1\n----\n2\n")
            with open(os.path.join(d, "ignore.txt"), "w") as f:
                f.write("not a test")
            report = run_path(d, self.engine)
            self.assertEqual(report["summary"]["files"], 2)
            self.assertEqual(report["summary"]["passed"], 1)
            self.assertEqual(report["summary"]["failed"], 1)

    def test_report_is_json_serializable(self):
        path = _write("query I\nSELECT 1\n----\n1\n")
        try:
            report = run_path(path, self.engine)
            json.dumps(report)
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
