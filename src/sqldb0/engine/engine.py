"""引擎核心:目录(catalog)、表/视图/索引、表达式求值与语句执行。"""

import re

from .parser import (SQLError, parse_sql, Literal, ColumnRef, Star, Unary,
                     Binary, FunctionCall, CaseExpr, SelectItem, OrderItem,
                     CreateTable, DropTable, CreateIndex, DropIndex,
                     CreateView, DropView, Insert, Update, Delete, Select)
from .values import render_value, value_type_char, type_matches

# 类型串字符 -> 内部类型
_TYPE_MAP = {
    "INTEGER": "INTEGER", "INT": "INTEGER", "BOOL": "INTEGER",
    "BOOLEAN": "INTEGER",
    "TEXT": "TEXT", "VARCHAR": "TEXT", "CHAR": "TEXT",
    "REAL": "REAL", "FLOAT": "REAL", "DOUBLE": "REAL",
    "DECIMAL": "REAL", "NUMERIC": "REAL",
    "BLOB": "BLOB",
}


class Result:
    """语句执行结果。查询返回 columns+rows;DML 返回 affected。"""

    __slots__ = ("columns", "rows", "affected")

    def __init__(self, columns=None, rows=None, affected=None):
        self.columns = columns or []
        self.rows = rows or []
        self.affected = affected


class Column:
    __slots__ = ("name", "type_name", "primary_key", "not_null", "unique",
                 "default")

    def __init__(self, name, type_name, primary_key=False, not_null=False,
                 unique=False, default=None):
        self.name = name
        self.type_name = type_name
        self.primary_key = primary_key
        self.not_null = not_null
        self.unique = unique
        self.default = default


class Table:
    def __init__(self, name, columns):
        self.name = name
        self.columns = columns
        self.rows = []

    def column_index(self, name):
        for i, c in enumerate(self.columns):
            if c.name.lower() == name.lower():
                return i
        raise SQLError(f"no such column: {name}")


class View:
    def __init__(self, name, select):
        self.name = name
        self.select = select


class Index:
    def __init__(self, name, table, columns):
        self.name = name
        self.table = table
        self.columns = columns


class Database:
    def __init__(self):
        self.tables = {}
        self.views = {}
        self.indexes = {}

    def resolve(self, name):
        """按名解析表或视图。"""
        if name.lower() in self.tables:
            return ("table", self.tables[name.lower()])
        if name.lower() in self.views:
            return ("view", self.views[name.lower()])
        raise SQLError(f"no such table: {name}")


# ---------------------------------------------------------------------------
# 表达式求值
# ---------------------------------------------------------------------------

def _truthy(v):
    """SQL 三值逻辑:NULL 视为未知(False)。"""
    return v is not None and bool(v)


def _is_null(v):
    return v is None


def _coerce_arith(a, b):
    """数值运算前的类型提升:任一为浮点则整体浮点。"""
    if isinstance(a, float) or isinstance(b, float):
        return float(a), float(b)
    return a, b


def _like(pattern, value):
    """LIKE 匹配:% 任意串,_ 单字符,大小写不敏感(ASCII)。"""
    if not isinstance(value, str) or not isinstance(pattern, str):
        return False
    regex = []
    for ch in pattern:
        if ch == "%":
            regex.append(".*")
        elif ch == "_":
            regex.append(".")
        else:
            regex.append(re.escape(ch))
    return re.fullmatch("".join(regex), value, re.IGNORECASE) is not None


def _compare(a, b):
    """返回 -1/0/1;类型不兼容时按渲染文本比较。"""
    if a is None or b is None:
        return None
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return (a > b) - (a < b)
    if isinstance(a, str) and isinstance(b, str):
        return (a > b) - (a < b)
    if isinstance(a, bytes) and isinstance(b, bytes):
        return (a > b) - (a < b)
    ra, rb = render_value(a), render_value(b)
    return (ra > rb) - (ra < rb)


class Evaluator:
    """对单行求值表达式;聚合函数由执行器预计算后注入。"""

    def __init__(self, row, schema, aggregates=None):
        self.row = row
        self.schema = schema  # [(col_name, col_index), ...]
        self.aggregates = aggregates or {}  # 聚合函数名 -> 值

    def eval(self, node):
        if isinstance(node, Literal):
            return node.value
        if isinstance(node, ColumnRef):
            return self._column(node)
        if isinstance(node, Unary):
            return self._unary(node)
        if isinstance(node, Binary):
            return self._binary(node)
        if isinstance(node, FunctionCall):
            return self._function(node)
        if isinstance(node, CaseExpr):
            return self._case(node)
        raise SQLError(f"cannot evaluate node {type(node).__name__}")

    def _column(self, node):
        for name, idx in self.schema:
            if name.lower() == node.name.lower():
                if node.table and node.table.lower() != name.split(".")[0].lower():
                    continue
                return self.row[idx]
        raise SQLError(f"no such column: {node.name}")

    def _unary(self, node):
        v = self.eval(node.expr)
        if node.op == "NOT":
            return 0 if _truthy(v) else 1
        if node.op == "-":
            if v is None:
                return None
            return -v
        raise SQLError(f"unsupported unary operator {node.op}")

    def _binary(self, node):
        op = node.op
        if op == "AND":
            left = self.eval(node.left)
            if not _truthy(left):
                return 0
            return 1 if _truthy(self.eval(node.right)) else 0
        if op == "OR":
            left = self.eval(node.left)
            if _truthy(left):
                return 1
            return 1 if _truthy(self.eval(node.right)) else 0
        if op == "IS NULL":
            return 1 if _is_null(self.eval(node.left)) else 0
        if op == "IS NOT NULL":
            return 0 if _is_null(self.eval(node.left)) else 1
        if op == "IN":
            left = self.eval(node.left)
            for arg in node.right:
                if _compare(left, self.eval(arg)) == 0:
                    return 1
            return 0
        if op == "LIKE":
            return 1 if _like(self.eval(node.right), self.eval(node.left)) else 0
        if op == "BETWEEN":
            lo, hi = node.right
            v = self.eval(node.left)
            c1, c2 = _compare(v, self.eval(lo)), _compare(v, self.eval(hi))
            return 1 if (c1 is not None and c2 is not None and c1 >= 0 and c2 <= 0) else 0
        if op == "||":
            a, b = self.eval(node.left), self.eval(node.right)
            if a is None or b is None:
                return None
            return str(a) + str(b)
        left = self.eval(node.left)
        right = self.eval(node.right)
        if op in ("=", "=="):
            return 1 if _compare(left, right) == 0 else 0
        if op in ("!=", "<>"):
            return 1 if _compare(left, right) != 0 else 0
        if op == "<":
            c = _compare(left, right)
            return 1 if c is not None and c < 0 else 0
        if op == "<=":
            c = _compare(left, right)
            return 1 if c is not None and c <= 0 else 0
        if op == ">":
            c = _compare(left, right)
            return 1 if c is not None and c > 0 else 0
        if op == ">=":
            c = _compare(left, right)
            return 1 if c is not None and c >= 0 else 0
        if op == "+":
            if left is None or right is None:
                return None
            a, b = _coerce_arith(left, right)
            return a + b
        if op == "-":
            if left is None or right is None:
                return None
            a, b = _coerce_arith(left, right)
            return a - b
        if op == "*":
            if left is None or right is None:
                return None
            a, b = _coerce_arith(left, right)
            return a * b
        if op == "/":
            if left is None or right is None:
                return None
            if right == 0:
                return None
            if isinstance(left, int) and isinstance(right, int):
                return int(left / right)
            return left / right
        if op == "%":
            if left is None or right is None:
                return None
            if right == 0:
                return None
            return left % right
        raise SQLError(f"unsupported operator {op}")

    def _function(self, node):
        name = node.name
        if id(node) in self.aggregates:
            return self.aggregates[id(node)]
        args = [self.eval(a) for a in node.args]
        return _scalar_function(name, args)

    def _case(self, node):
        if node.operand is not None:
            target = self.eval(node.operand)
            for when, then in node.whens:
                if _compare(target, self.eval(when)) == 0:
                    return self.eval(then)
        else:
            for when, then in node.whens:
                if _truthy(self.eval(when)):
                    return self.eval(then)
        if node.else_expr is not None:
            return self.eval(node.else_expr)
        return None


def _scalar_function(name, args):
    def need(n):
        if len(args) < n:
            raise SQLError(f"wrong number of arguments to {name}()")
    if name == "ABS":
        need(1)
        return abs(args[0]) if args[0] is not None else None
    if name == "LOWER":
        need(1)
        return args[0].lower() if args[0] is not None else None
    if name == "UPPER":
        need(1)
        return args[0].upper() if args[0] is not None else None
    if name == "LENGTH":
        need(1)
        return len(args[0]) if args[0] is not None else None
    if name == "COALESCE":
        need(1)
        for a in args:
            if a is not None:
                return a
        return None
    if name == "IFNULL":
        need(2)
        return args[0] if args[0] is not None else args[1]
    if name == "NULLIF":
        need(2)
        return None if _compare(args[0], args[1]) == 0 else args[0]
    if name == "ROUND":
        need(1)
        if args[0] is None:
            return None
        nd = int(args[1]) if len(args) > 1 and args[1] is not None else 0
        return round(args[0], nd)
    if name == "SUBSTR":
        need(2)
        s, start = args[0], int(args[1])
        length = int(args[2]) if len(args) > 2 and args[2] is not None else None
        if s is None:
            return None
        idx = start - 1 if start > 0 else max(len(s) + start, 0)
        return s[idx:idx + length] if length is not None else s[idx:]
    if name == "TRIM":
        need(1)
        return args[0].strip() if args[0] is not None else None
    if name == "LTRIM":
        need(1)
        return args[0].lstrip() if args[0] is not None else None
    if name == "RTRIM":
        need(1)
        return args[0].rstrip() if args[0] is not None else None
    if name == "REPLACE":
        need(3)
        if args[0] is None:
            return None
        return args[0].replace(args[1], args[2])
    if name == "TYPEOF":
        need(1)
        return value_type_char(args[0]) if args[0] is not None else "NULL"
    if name == "MIN":
        need(1)
        return min((a for a in args if a is not None), default=None)
    if name == "MAX":
        need(1)
        return max((a for a in args if a is not None), default=None)
    raise SQLError(f"no such function: {name}")


# ---------------------------------------------------------------------------
# 聚合
# ---------------------------------------------------------------------------

def _aggregate_value(name, values, distinct):
    if distinct:
        seen, uniq = set(), []
        for v in values:
            key = render_value(v)
            if key not in seen:
                seen.add(key)
                uniq.append(v)
        values = uniq
    if name == "COUNT":
        # COUNT(col) 不计 NULL;COUNT(*) 由调用方直接返回行数
        return len([v for v in values if v is not None])
    if name == "SUM":
        nums = [v for v in values if v is not None]
        if not nums:
            return None
        return sum(nums)
    if name == "MIN":
        return min((v for v in values if v is not None), default=None)
    if name == "MAX":
        return max((v for v in values if v is not None), default=None)
    if name == "AVG":
        nums = [v for v in values if v is not None]
        if not nums:
            return None
        return sum(nums) / len(nums)
    raise SQLError(f"no such aggregate: {name}")


# ---------------------------------------------------------------------------
# 引擎
# ---------------------------------------------------------------------------

class Engine:
    """SQL 引擎:维护一个 Database,执行语句与查询。"""

    def __init__(self):
        self.db = Database()

    # -- 对外 API -----------------------------------------------------------
    def statement(self, sql):
        """执行语句,返回受影响行数;失败抛 SQLError。

        SELECT 作为语句执行时视为成功(返回 0)。
        """
        stmt = parse_sql(sql)
        if isinstance(stmt, Select):
            self._execute_select(stmt)
            return 0
        return self._execute(stmt)

    def query(self, sql):
        """执行查询,返回 (columns, rows);失败抛 SQLError。"""
        stmt = parse_sql(sql)
        if not isinstance(stmt, Select):
            raise SQLError("expected a SELECT query")
        return self._execute_select(stmt)

    def execute(self, sql):
        """执行任意语句,返回 Result。"""
        stmt = parse_sql(sql)
        if isinstance(stmt, Select):
            columns, rows = self._execute_select(stmt)
            return Result(columns=columns, rows=rows)
        affected = self._execute(stmt)
        return Result(affected=affected)

    # -- 语句执行 -----------------------------------------------------------
    def _execute(self, stmt):
        if isinstance(stmt, CreateTable):
            return self._create_table(stmt)
        if isinstance(stmt, DropTable):
            return self._drop_table(stmt)
        if isinstance(stmt, CreateIndex):
            return self._create_index(stmt)
        if isinstance(stmt, DropIndex):
            return self._drop_index(stmt)
        if isinstance(stmt, CreateView):
            return self._create_view(stmt)
        if isinstance(stmt, DropView):
            return self._drop_view(stmt)
        if isinstance(stmt, Insert):
            return self._insert(stmt)
        if isinstance(stmt, Update):
            return self._update(stmt)
        if isinstance(stmt, Delete):
            return self._delete(stmt)
        raise SQLError(f"unsupported statement {type(stmt).__name__}")

    def _create_table(self, stmt):
        key = stmt.name.lower()
        if key in self.db.tables:
            if stmt.if_not_exists:
                return 0
            raise SQLError(f"table {stmt.name} already exists")
        columns = [Column(c.name, _TYPE_MAP.get(c.type_name, "TEXT"),
                          c.primary_key, c.not_null, c.unique, c.default)
                   for c in stmt.columns]
        self.db.tables[key] = Table(stmt.name, columns)
        return 0

    def _drop_table(self, stmt):
        key = stmt.name.lower()
        if key not in self.db.tables:
            if stmt.if_exists:
                return 0
            raise SQLError(f"no such table: {stmt.name}")
        del self.db.tables[key]
        for idx in [i for i in self.db.indexes
                    if self.db.indexes[i].table.lower() == key]:
            del self.db.indexes[idx]
        return 0

    def _create_index(self, stmt):
        key = stmt.name.lower()
        if key in self.db.indexes:
            if stmt.if_not_exists:
                return 0
            raise SQLError(f"index {stmt.name} already exists")
        if stmt.table.lower() not in self.db.tables:
            raise SQLError(f"no such table: {stmt.table}")
        self.db.indexes[key] = Index(stmt.name, stmt.table, stmt.columns)
        return 0

    def _drop_index(self, stmt):
        key = stmt.name.lower()
        if key not in self.db.indexes:
            if stmt.if_exists:
                return 0
            raise SQLError(f"no such index: {stmt.name}")
        del self.db.indexes[key]
        return 0

    def _create_view(self, stmt):
        key = stmt.name.lower()
        if key in self.db.views:
            if stmt.if_not_exists:
                return 0
            raise SQLError(f"view {stmt.name} already exists")
        self.db.views[key] = View(stmt.name, stmt.select)
        return 0

    def _drop_view(self, stmt):
        key = stmt.name.lower()
        if key not in self.db.views:
            if stmt.if_exists:
                return 0
            raise SQLError(f"no such view: {stmt.name}")
        del self.db.views[key]
        return 0

    def _insert(self, stmt):
        key = stmt.table.lower()
        if key not in self.db.tables:
            raise SQLError(f"no such table: {stmt.table}")
        table = self.db.tables[key]
        if stmt.columns:
            col_idx = [table.column_index(c) for c in stmt.columns]
        else:
            col_idx = list(range(len(table.columns)))
        for row_exprs in stmt.rows:
            if len(row_exprs) != len(col_idx):
                raise SQLError("INSERT has wrong number of values")
            row = [None] * len(table.columns)
            for expr, idx in zip(row_exprs, col_idx):
                row[idx] = _eval_literal(expr)
            self._validate_row(table, row)
            table.rows.append(row)
        return len(stmt.rows)

    def _validate_row(self, table, row):
        for i, col in enumerate(table.columns):
            v = row[i]
            if v is None:
                if col.not_null or col.primary_key:
                    raise SQLError(f"NOT NULL constraint failed: {col.name}")
                continue
            if col.type_name == "INTEGER" and not isinstance(v, int):
                raise SQLError(f"datatype mismatch: {col.name}")
            if col.type_name == "REAL" and not isinstance(v, (int, float)):
                raise SQLError(f"datatype mismatch: {col.name}")
            if col.type_name == "TEXT" and not isinstance(v, str):
                raise SQLError(f"datatype mismatch: {col.name}")
            if col.unique or col.primary_key:
                for other in table.rows:
                    if other[i] == v:
                        raise SQLError(f"UNIQUE constraint failed: {col.name}")

    def _update(self, stmt):
        key = stmt.table.lower()
        if key not in self.db.tables:
            raise SQLError(f"no such table: {stmt.table}")
        table = self.db.tables[key]
        schema = [(c.name, i) for i, c in enumerate(table.columns)]
        targets = [(table.column_index(col), expr) for col, expr in stmt.assignments]
        affected = 0
        for row in table.rows:
            if stmt.where is not None and not _truthy(Evaluator(row, schema).eval(stmt.where)):
                continue
            for idx, expr in targets:
                row[idx] = Evaluator(row, schema).eval(expr)
            affected += 1
        return affected

    def _delete(self, stmt):
        key = stmt.table.lower()
        if key not in self.db.tables:
            raise SQLError(f"no such table: {stmt.table}")
        table = self.db.tables[key]
        schema = [(c.name, i) for i, c in enumerate(table.columns)]
        before = len(table.rows)
        table.rows = [row for row in table.rows
                      if stmt.where is not None and not _truthy(Evaluator(row, schema).eval(stmt.where))]
        return before - len(table.rows)

    # -- SELECT 执行 ---------------------------------------------------------
    def _execute_select(self, stmt):
        if stmt.from_table is None:
            rows = [()]
            schema = []
        else:
            kind, obj = self.db.resolve(stmt.from_table)
            if kind == "table":
                rows = [tuple(r) for r in obj.rows]
                schema = [(c.name, i) for i, c in enumerate(obj.columns)]
            else:
                columns, rows = self._execute_select(obj.select)
                schema = [(name, i) for i, name in enumerate(columns)]

        # 列引用校验(空表时也要报未知列)
        for node in _select_exprs(stmt):
            _validate_columns(node, schema)

        # WHERE
        if stmt.where is not None:
            rows = [r for r in rows if _truthy(Evaluator(r, schema).eval(stmt.where))]

        # 聚合检测
        agg_calls = _collect_aggregates(stmt.items, stmt.having, stmt.order_by)
        if agg_calls or stmt.group_by:
            return self._execute_aggregate(stmt, rows, schema, agg_calls)

        # 普通投影
        out_columns, out_rows = [], []
        for r in rows:
            ev = Evaluator(r, schema)
            row_out = []
            for item in stmt.items:
                if isinstance(item.expr, Star):
                    for name, idx in schema:
                        row_out.append(r[idx])
                else:
                    row_out.append(ev.eval(item.expr))
            out_rows.append(row_out)
        if stmt.items and all(isinstance(i.expr, Star) for i in stmt.items):
            out_columns = [name for name, _ in schema]
        else:
            for item in stmt.items:
                if isinstance(item.expr, Star):
                    out_columns.extend(name for name, _ in schema)
                else:
                    out_columns.append(item.alias or _expr_name(item.expr))

        # DISTINCT
        if stmt.distinct:
            seen, uniq = set(), []
            for r in out_rows:
                key = tuple(render_value(v) for v in r)
                if key not in seen:
                    seen.add(key)
                    uniq.append(r)
            out_rows = uniq

        # ORDER BY
        if stmt.order_by:
            out_rows = _sort_rows(out_rows, stmt.order_by, out_columns)

        # LIMIT / OFFSET
        out_rows = _apply_limit(out_rows, stmt.limit, stmt.offset)
        return out_columns, out_rows

    def _execute_aggregate(self, stmt, rows, schema, agg_calls):
        if stmt.group_by:
            groups = {}
            for r in rows:
                ev = Evaluator(r, schema)
                key = tuple(render_value(ev.eval(g)) for g in stmt.group_by)
                groups.setdefault(key, []).append(r)
            group_keys = list(groups.keys())
        else:
            groups = {(): rows}
            group_keys = [()]

        out_columns, out_rows = [], []
        for gkey in group_keys:
            group_rows = groups[gkey]
            agg_values = {}
            for node_id, (name, arg_expr, distinct) in agg_calls.items():
                agg_values[node_id] = _compute_aggregate(
                    name, group_rows, schema, arg_expr, distinct)
            if stmt.having is not None:
                ev = Evaluator(group_rows[0] if group_rows else (), schema, agg_values)
                if not _truthy(ev.eval(stmt.having)):
                    continue
            row_out = []
            for item in stmt.items:
                if isinstance(item.expr, Star):
                    for name, idx in schema:
                        row_out.append(group_rows[0][idx] if group_rows else None)
                else:
                    ev = Evaluator(group_rows[0] if group_rows else (), schema, agg_values)
                    row_out.append(ev.eval(item.expr))
            out_rows.append(row_out)
        if stmt.items and all(isinstance(i.expr, Star) for i in stmt.items):
            out_columns = [name for name, _ in schema]
        else:
            for item in stmt.items:
                if isinstance(item.expr, Star):
                    out_columns.extend(name for name, _ in schema)
                else:
                    out_columns.append(item.alias or _expr_name(item.expr))
        if stmt.distinct:
            seen, uniq = set(), []
            for r in out_rows:
                key = tuple(render_value(v) for v in r)
                if key not in seen:
                    seen.add(key)
                    uniq.append(r)
            out_rows = uniq
        if stmt.order_by:
            out_rows = _sort_rows(out_rows, stmt.order_by, out_columns)
        out_rows = _apply_limit(out_rows, stmt.limit, stmt.offset)
        return out_columns, out_rows


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------

def _select_exprs(stmt):
    """收集 SELECT 中需要列校验的表达式。"""
    nodes = [item.expr for item in stmt.items]
    if stmt.where is not None:
        nodes.append(stmt.where)
    if stmt.group_by:
        nodes.extend(stmt.group_by)
    if stmt.having is not None:
        nodes.append(stmt.having)
    if stmt.order_by:
        nodes.extend(o.expr for o in stmt.order_by)
    return nodes


def _validate_columns(node, schema):
    """校验表达式中的列引用都能在 schema 中解析。"""
    if isinstance(node, ColumnRef):
        for name, _idx in schema:
            if name.lower() == node.name.lower():
                return
        raise SQLError(f"no such column: {node.name}")
    if isinstance(node, Unary):
        _validate_columns(node.expr, schema)
    elif isinstance(node, Binary):
        _validate_columns(node.left, schema)
        _validate_columns(node.right, schema)
    elif isinstance(node, FunctionCall):
        for a in node.args:
            _validate_columns(a, schema)
    elif isinstance(node, CaseExpr):
        if node.operand is not None:
            _validate_columns(node.operand, schema)
        for w, t in node.whens:
            _validate_columns(w, schema)
            _validate_columns(t, schema)
        if node.else_expr is not None:
            _validate_columns(node.else_expr, schema)


def _eval_literal(expr):
    """INSERT VALUES 中的表达式:仅支持字面量(含 NULL/数字/字符串)。"""
    if isinstance(expr, Literal):
        return expr.value
    raise SQLError("INSERT VALUES only supports literals")


def _expr_name(expr):
    if isinstance(expr, ColumnRef):
        return expr.name
    if isinstance(expr, FunctionCall):
        return expr.name
    return ""


def _collect_aggregates(items, having, order_by):
    """收集聚合调用,返回 {id(node): (name, arg_expr, distinct)}。

    COUNT(*) 的 arg_expr 为 None。
    """
    calls = {}

    def walk(node):
        if isinstance(node, FunctionCall):
            if node.name in ("COUNT", "SUM", "MIN", "MAX", "AVG"):
                if node.args and isinstance(node.args[0], Star):
                    calls[id(node)] = (node.name, None, node.distinct)
                else:
                    calls[id(node)] = (node.name, node.args[0], node.distinct)
            for a in node.args:
                walk(a)
        elif isinstance(node, Binary):
            walk(node.left)
            walk(node.right)
        elif isinstance(node, Unary):
            walk(node.expr)
        elif isinstance(node, CaseExpr):
            if node.operand:
                walk(node.operand)
            for w, t in node.whens:
                walk(w)
                walk(t)
            if node.else_expr:
                walk(node.else_expr)

    for item in items:
        walk(item.expr)
    if having:
        walk(having)
    if order_by:
        for o in order_by:
            walk(o.expr)
    return calls


def _compute_aggregate(name, rows, schema, arg_expr, distinct):
    """对一组行计算聚合值。arg_expr 为 None 表示 COUNT(*)。"""
    if arg_expr is None:
        return len(rows)
    values = []
    for r in rows:
        ev = Evaluator(r, schema)
        values.append(ev.eval(arg_expr))
    return _aggregate_value(name, values, distinct)


def _sort_rows(rows, order_by, columns):
    def key_fn(r):
        keys = []
        for o in order_by:
            if isinstance(o.expr, ColumnRef):
                idx = _find_column(columns, o.expr.name)
                v = r[idx] if idx is not None else None
            else:
                v = None
            keys.append((v is None, render_value(v)))
        return keys

    result = sorted(rows, key=key_fn)
    for o in reversed(order_by):
        if o.desc:
            result = sorted(result, key=key_fn, reverse=True)
    return result


def _find_column(columns, name):
    for i, c in enumerate(columns):
        if c.lower() == name.lower():
            return i
    return None


def _apply_limit(rows, limit, offset):
    if offset is not None:
        off = _const_int(offset)
        rows = rows[off:]
    if limit is not None:
        lim = _const_int(limit)
        rows = rows[:lim]
    return rows


def _const_int(expr):
    if isinstance(expr, Literal) and isinstance(expr.value, int):
        return expr.value
    raise SQLError("LIMIT/OFFSET must be integer literals")
