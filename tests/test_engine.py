"""引擎单元测试。"""

import unittest

from sqldb0.engine import Engine, SQLError


class TestDDL(unittest.TestCase):
    def setUp(self):
        self.e = Engine()

    def test_create_and_drop_table(self):
        self.e.statement("CREATE TABLE t1(a INTEGER, b TEXT)")
        self.e.statement("DROP TABLE t1")
        with self.assertRaises(SQLError):
            self.e.statement("DROP TABLE t1")

    def test_drop_table_if_exists(self):
        self.e.statement("DROP TABLE IF EXISTS nope")

    def test_create_duplicate_table(self):
        self.e.statement("CREATE TABLE t1(a INTEGER)")
        with self.assertRaises(SQLError):
            self.e.statement("CREATE TABLE t1(a INTEGER)")
        self.e.statement("CREATE TABLE IF NOT EXISTS t1(a INTEGER)")

    def test_create_index_and_drop(self):
        self.e.statement("CREATE TABLE t1(a INTEGER)")
        self.e.statement("CREATE INDEX t1i1 ON t1(a)")
        self.e.statement("DROP INDEX t1i1")
        with self.assertRaises(SQLError):
            self.e.statement("DROP INDEX t1i1")

    def test_create_view_and_drop(self):
        self.e.statement("CREATE TABLE t1(a INTEGER)")
        self.e.statement("CREATE VIEW v1 AS SELECT a FROM t1")
        cols, rows = self.e.query("SELECT a FROM v1")
        self.assertEqual(cols, ["a"])
        self.e.statement("DROP VIEW v1")
        with self.assertRaises(SQLError):
            self.e.statement("DROP VIEW v1")


class TestDML(unittest.TestCase):
    def setUp(self):
        self.e = Engine()
        self.e.statement("CREATE TABLE t1(a INTEGER, b TEXT)")

    def test_insert_affected(self):
        self.assertEqual(self.e.statement("INSERT INTO t1 VALUES(1, 'x')"), 1)
        self.assertEqual(
            self.e.statement("INSERT INTO t1 VALUES(2, 'y'), (3, 'z')"), 2)

    def test_insert_wrong_arity(self):
        with self.assertRaises(SQLError):
            self.e.statement("INSERT INTO t1 VALUES(1)")

    def test_insert_into_columns(self):
        self.e.statement("INSERT INTO t1(b) VALUES('only-b')")
        cols, rows = self.e.query("SELECT a, b FROM t1")
        self.assertEqual(rows, [[None, "only-b"]])

    def test_update(self):
        self.e.statement("INSERT INTO t1 VALUES(1, 'x'), (2, 'y')")
        self.assertEqual(
            self.e.statement("UPDATE t1 SET b = 'z' WHERE a = 1"), 1)
        cols, rows = self.e.query("SELECT b FROM t1 ORDER BY a")
        self.assertEqual(rows, [["z"], ["y"]])

    def test_delete(self):
        self.e.statement("INSERT INTO t1 VALUES(1, 'x'), (2, 'y')")
        self.assertEqual(self.e.statement("DELETE FROM t1 WHERE a = 1"), 1)
        cols, rows = self.e.query("SELECT a FROM t1")
        self.assertEqual(rows, [[2]])

    def test_not_null_constraint(self):
        self.e.statement("CREATE TABLE t2(x INTEGER NOT NULL)")
        with self.assertRaises(SQLError):
            self.e.statement("INSERT INTO t2 VALUES(NULL)")

    def test_unique_constraint(self):
        self.e.statement("CREATE TABLE t2(x INTEGER UNIQUE)")
        self.e.statement("INSERT INTO t2 VALUES(1)")
        with self.assertRaises(SQLError):
            self.e.statement("INSERT INTO t2 VALUES(1)")


class TestSelect(unittest.TestCase):
    def setUp(self):
        self.e = Engine()
        self.e.statement("CREATE TABLE t1(a INTEGER, b TEXT)")
        self.e.statement("INSERT INTO t1 VALUES(1, 'one'), (2, 'two'), "
                        "(3, NULL), (4, 'four')")

    def test_select_all(self):
        cols, rows = self.e.query("SELECT * FROM t1 ORDER BY a")
        self.assertEqual(cols, ["a", "b"])
        self.assertEqual(rows, [[1, "one"], [2, "two"], [3, None], [4, "four"]])

    def test_where(self):
        cols, rows = self.e.query("SELECT a FROM t1 WHERE a > 2")
        self.assertEqual(rows, [[3], [4]])

    def test_where_null(self):
        cols, rows = self.e.query("SELECT a FROM t1 WHERE b IS NULL")
        self.assertEqual(rows, [[3]])

    def test_order_by_desc(self):
        cols, rows = self.e.query("SELECT a FROM t1 ORDER BY a DESC")
        self.assertEqual(rows, [[4], [3], [2], [1]])

    def test_limit_offset(self):
        cols, rows = self.e.query("SELECT a FROM t1 ORDER BY a LIMIT 2 OFFSET 1")
        self.assertEqual(rows, [[2], [3]])

    def test_distinct(self):
        self.e.statement("INSERT INTO t1 VALUES(1, 'dup')")
        cols, rows = self.e.query("SELECT DISTINCT a FROM t1 ORDER BY a")
        self.assertEqual(rows, [[1], [2], [3], [4]])

    def test_arithmetic(self):
        cols, rows = self.e.query("SELECT a + 1, a * 2, a - 1 FROM t1 "
                                  "WHERE a = 1")
        self.assertEqual(rows, [[2, 2, 0]])

    def test_integer_division(self):
        cols, rows = self.e.query("SELECT 5 / 2")
        self.assertEqual(rows, [[2]])

    def test_float_division(self):
        cols, rows = self.e.query("SELECT 5.0 / 2")
        self.assertEqual(rows, [[2.5]])

    def test_like(self):
        cols, rows = self.e.query("SELECT a FROM t1 WHERE b LIKE '%w%'")
        self.assertEqual(rows, [[2]])

    def test_in(self):
        cols, rows = self.e.query("SELECT a FROM t1 WHERE a IN (1, 3)")
        self.assertEqual(rows, [[1], [3]])

    def test_between(self):
        cols, rows = self.e.query("SELECT a FROM t1 WHERE a BETWEEN 2 AND 3")
        self.assertEqual(rows, [[2], [3]])

    def test_case(self):
        cols, rows = self.e.query(
            "SELECT CASE WHEN a > 2 THEN 'big' ELSE 'small' END "
            "FROM t1 ORDER BY a")
        self.assertEqual(rows, [["small"], ["small"], ["big"], ["big"]])

    def test_concat(self):
        cols, rows = self.e.query("SELECT a || b FROM t1 WHERE a = 1")
        self.assertEqual(rows, [["1one"]])

    def test_functions(self):
        cols, rows = self.e.query("SELECT abs(-5), lower('ABC'), "
                                  "length('hello'), coalesce(NULL, 7)")
        self.assertEqual(rows, [[5, "abc", 5, 7]])

    def test_aggregates(self):
        cols, rows = self.e.query("SELECT count(*), sum(a), min(a), max(a), "
                                  "avg(a) FROM t1")
        self.assertEqual(rows, [[4, 10, 1, 4, 2.5]])

    def test_group_by(self):
        self.e.statement("CREATE TABLE t2(g TEXT, v INTEGER)")
        self.e.statement("INSERT INTO t2 VALUES('x', 1), ('x', 2), ('y', 3)")
        cols, rows = self.e.query("SELECT g, count(*), sum(v) FROM t2 "
                                  "GROUP BY g ORDER BY g")
        self.assertEqual(rows, [["x", 2, 3], ["y", 1, 3]])

    def test_having(self):
        self.e.statement("CREATE TABLE t2(g TEXT, v INTEGER)")
        self.e.statement("INSERT INTO t2 VALUES('x', 1), ('x', 2), ('y', 3)")
        cols, rows = self.e.query("SELECT g, count(*) FROM t2 GROUP BY g "
                                  "HAVING count(*) > 1")
        self.assertEqual(rows, [["x", 2]])

    def test_no_from(self):
        cols, rows = self.e.query("SELECT 1 + 1")
        self.assertEqual(rows, [[2]])

    def test_unknown_column(self):
        with self.assertRaises(SQLError):
            self.e.query("SELECT nope FROM t1")

    def test_unknown_table(self):
        with self.assertRaises(SQLError):
            self.e.query("SELECT a FROM nope")


class TestRendering(unittest.TestCase):
    def test_render(self):
        from sqldb0.engine.values import render_value
        self.assertEqual(render_value(None), "NULL")
        self.assertEqual(render_value(42), "42")
        self.assertEqual(render_value(1.5), "1.500")
        self.assertEqual(render_value(""), "(empty)")
        self.assertEqual(render_value("hi"), "hi")
        self.assertEqual(render_value("a\nb"), "a@b")


if __name__ == "__main__":
    unittest.main()
