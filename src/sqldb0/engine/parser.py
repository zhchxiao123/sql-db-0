"""SQL 词法与语法解析:把 SQL 文本解析为 AST。

支持语句:CREATE TABLE / DROP TABLE / CREATE INDEX / DROP INDEX /
CREATE VIEW / DROP VIEW / INSERT / UPDATE / DELETE / SELECT。
支持表达式:字面量、列引用、一元/二元运算、比较、逻辑、IN / LIKE /
BETWEEN / IS NULL / CASE / 函数调用(含聚合)。
"""

from .values import TYPE_INTEGER, TYPE_REAL, TYPE_TEXT, TYPE_BLOB


class SQLError(Exception):
    """SQL 语法或执行错误。"""


# ---------------------------------------------------------------------------
# 词法
# ---------------------------------------------------------------------------

KEYWORDS = {
    "SELECT", "FROM", "WHERE", "GROUP", "BY", "HAVING", "ORDER", "LIMIT",
    "OFFSET", "AS", "AND", "OR", "NOT", "IN", "LIKE", "BETWEEN", "IS",
    "NULL", "CASE", "WHEN", "THEN", "ELSE", "END", "DISTINCT", "ALL",
    "CREATE", "TABLE", "DROP", "INDEX", "VIEW", "IF", "EXISTS", "INSERT",
    "INTO", "VALUES", "UPDATE", "SET", "DELETE", "PRIMARY", "KEY", "UNIQUE",
    "DEFAULT", "ON", "ASC", "DESC", "TRUE", "FALSE", "JOIN", "INNER", "LEFT",
    "RIGHT", "FULL", "OUTER", "CROSS", "UNION", "INTERSECT", "EXCEPT",
    "INT", "VARCHAR", "CHAR", "FLOAT", "DOUBLE", "BOOLEAN", "BOOL", "DATE",
    "DECIMAL", "NUMERIC",
}


class Token:
    __slots__ = ("kind", "value", "pos")

    def __init__(self, kind, value, pos):
        self.kind = kind  # "KEYWORD" | "IDENT" | "NUMBER" | "STRING" | "OP" | "EOF"
        self.value = value
        self.pos = pos

    def __repr__(self):
        return f"Token({self.kind}, {self.value!r})"


def tokenize(sql):
    tokens = []
    i, n = 0, len(sql)
    while i < n:
        c = sql[i]
        if c.isspace():
            i += 1
            continue
        if c == "-" and i + 1 < n and sql[i + 1] == "-":
            while i < n and sql[i] != "\n":
                i += 1
            continue
        if c == "/" and i + 1 < n and sql[i + 1] == "*":
            i += 2
            while i + 1 < n and not (sql[i] == "*" and sql[i + 1] == "/"):
                i += 1
            i = min(i + 2, n)
            continue
        if c == "'":
            j, buf = i + 1, []
            while j < n:
                if sql[j] == "'":
                    if j + 1 < n and sql[j + 1] == "'":
                        buf.append("'")
                        j += 2
                        continue
                    j += 1
                    break
                buf.append(sql[j])
                j += 1
            tokens.append(Token("STRING", "".join(buf), i))
            i = j
            continue
        if c in ('"', "`", "["):
            close = '"' if c == '"' else ("`" if c == "`" else "]")
            j, buf = i + 1, []
            while j < n and sql[j] != close:
                if sql[j] == close and j + 1 < n and sql[j + 1] == close:
                    buf.append(close)
                    j += 2
                    continue
                buf.append(sql[j])
                j += 1
            tokens.append(Token("IDENT", "".join(buf), i))
            i = j + 1
            continue
        if c.isdigit() or (c == "." and i + 1 < n and sql[i + 1].isdigit()):
            j = i
            while j < n and (sql[j].isdigit() or sql[j] == "."):
                j += 1
            text = sql[i:j]
            tokens.append(Token("NUMBER", float(text) if "." in text else int(text), i))
            i = j
            continue
        if c.isalpha() or c == "_":
            j = i
            while j < n and (sql[j].isalnum() or sql[j] in "_$"):
                j += 1
            word = sql[i:j]
            up = word.upper()
            tokens.append(Token("KEYWORD" if up in KEYWORDS else "IDENT", up if up in KEYWORDS else word, i))
            i = j
            continue
        two = sql[i:i + 2]
        if two in ("<=", ">=", "!=", "<>", "||", "=="):
            tokens.append(Token("OP", two, i))
            i += 2
            continue
        if c in "=<>+-*/%(),.;":
            tokens.append(Token("OP", c, i))
            i += 1
            continue
        raise SQLError(f"syntax error: unexpected character {c!r} at position {i}")
    tokens.append(Token("EOF", "", n))
    return tokens


# ---------------------------------------------------------------------------
# AST 节点
# ---------------------------------------------------------------------------

class Node:
    __slots__ = ()


class Literal(Node):
    __slots__ = ("value",)

    def __init__(self, value):
        self.value = value


class ColumnRef(Node):
    __slots__ = ("table", "name")

    def __init__(self, table, name):
        self.table = table  # 可能为 None
        self.name = name


class Star(Node):
    __slots__ = ("table",)

    def __init__(self, table=None):
        self.table = table


class Unary(Node):
    __slots__ = ("op", "expr")

    def __init__(self, op, expr):
        self.op = op
        self.expr = expr


class Binary(Node):
    __slots__ = ("op", "left", "right")

    def __init__(self, op, left, right):
        self.op = op
        self.left = left
        self.right = right


class FunctionCall(Node):
    __slots__ = ("name", "args", "distinct")

    def __init__(self, name, args, distinct=False):
        self.name = name
        self.args = args
        self.distinct = distinct


class CaseExpr(Node):
    __slots__ = ("operand", "whens", "else_expr")

    def __init__(self, operand, whens, else_expr):
        self.operand = operand
        self.whens = whens  # [(when_expr, then_expr), ...]
        self.else_expr = else_expr


class SelectItem(Node):
    __slots__ = ("expr", "alias")

    def __init__(self, expr, alias=None):
        self.expr = expr
        self.alias = alias


class OrderItem(Node):
    __slots__ = ("expr", "desc")

    def __init__(self, expr, desc=False):
        self.expr = expr
        self.desc = desc


class ColumnDef(Node):
    __slots__ = ("name", "type_name", "primary_key", "not_null", "unique", "default")

    def __init__(self, name, type_name, primary_key=False, not_null=False,
                 unique=False, default=None):
        self.name = name
        self.type_name = type_name  # "INTEGER" | "TEXT" | "REAL" | "BLOB" | ...
        self.primary_key = primary_key
        self.not_null = not_null
        self.unique = unique
        self.default = default


class CreateTable(Node):
    __slots__ = ("name", "columns", "if_not_exists")

    def __init__(self, name, columns, if_not_exists=False):
        self.name = name
        self.columns = columns
        self.if_not_exists = if_not_exists


class DropTable(Node):
    __slots__ = ("name", "if_exists")

    def __init__(self, name, if_exists=False):
        self.name = name
        self.if_exists = if_exists


class CreateIndex(Node):
    __slots__ = ("name", "table", "columns", "if_not_exists")

    def __init__(self, name, table, columns, if_not_exists=False):
        self.name = name
        self.table = table
        self.columns = columns
        self.if_not_exists = if_not_exists


class DropIndex(Node):
    __slots__ = ("name", "if_exists")

    def __init__(self, name, if_exists=False):
        self.name = name
        self.if_exists = if_exists


class CreateView(Node):
    __slots__ = ("name", "select", "if_not_exists")

    def __init__(self, name, select, if_not_exists=False):
        self.name = name
        self.select = select
        self.if_not_exists = if_not_exists


class DropView(Node):
    __slots__ = ("name", "if_exists")

    def __init__(self, name, if_exists=False):
        self.name = name
        self.if_exists = if_exists


class Insert(Node):
    __slots__ = ("table", "columns", "rows")

    def __init__(self, table, columns, rows):
        self.table = table
        self.columns = columns  # 可能为 None(全列)
        self.rows = rows  # list[list[expr]]


class Update(Node):
    __slots__ = ("table", "assignments", "where")

    def __init__(self, table, assignments, where):
        self.table = table
        self.assignments = assignments  # [(col, expr), ...]
        self.where = where


class Delete(Node):
    __slots__ = ("table", "where")

    def __init__(self, table, where):
        self.table = table
        self.where = where


class Select(Node):
    __slots__ = ("distinct", "items", "from_table", "where", "group_by",
                 "having", "order_by", "limit", "offset")

    def __init__(self, distinct, items, from_table, where, group_by, having,
                 order_by, limit, offset):
        self.distinct = distinct
        self.items = items
        self.from_table = from_table  # 表名或视图名
        self.where = where
        self.group_by = group_by
        self.having = having
        self.order_by = order_by
        self.limit = limit
        self.offset = offset


# ---------------------------------------------------------------------------
# 语法解析
# ---------------------------------------------------------------------------

class Parser:
    def __init__(self, sql):
        self.tokens = tokenize(sql)
        self.pos = 0

    # -- token helpers ------------------------------------------------------
    def peek(self):
        return self.tokens[self.pos]

    def next(self):
        tok = self.tokens[self.pos]
        self.pos += 1
        return tok

    def expect_op(self, op):
        tok = self.next()
        if tok.kind != "OP" or tok.value != op:
            raise SQLError(f"syntax error: expected {op!r}, got {tok.value!r}")
        return tok

    def expect_keyword(self, kw):
        tok = self.next()
        if tok.kind != "KEYWORD" or tok.value != kw:
            raise SQLError(f"syntax error: expected {kw}, got {tok.value!r}")
        return tok

    def accept_keyword(self, kw):
        tok = self.peek()
        if tok.kind == "KEYWORD" and tok.value == kw:
            self.pos += 1
            return True
        return False

    def accept_op(self, op):
        tok = self.peek()
        if tok.kind == "OP" and tok.value == op:
            self.pos += 1
            return True
        return False

    def expect_ident(self):
        tok = self.next()
        if tok.kind not in ("IDENT", "KEYWORD"):
            raise SQLError(f"syntax error: expected identifier, got {tok.value!r}")
        return tok.value

    def at_end(self):
        return self.peek().kind == "EOF"

    # -- statements ---------------------------------------------------------
    def parse_statement(self):
        tok = self.peek()
        if tok.kind != "KEYWORD":
            raise SQLError(f"syntax error: expected statement, got {tok.value!r}")
        kw = tok.value
        if kw == "CREATE":
            return self.parse_create()
        if kw == "DROP":
            return self.parse_drop()
        if kw == "INSERT":
            return self.parse_insert()
        if kw == "UPDATE":
            return self.parse_update()
        if kw == "DELETE":
            return self.parse_delete()
        if kw == "SELECT":
            return self.parse_select()
        raise SQLError(f"syntax error: unsupported statement {kw!r}")

    def parse_create(self):
        self.expect_keyword("CREATE")
        if self.accept_keyword("TABLE"):
            return self.parse_create_table()
        if self.accept_keyword("INDEX"):
            return self.parse_create_index()
        if self.accept_keyword("VIEW"):
            return self.parse_create_view()
        raise SQLError("syntax error: expected TABLE/INDEX/VIEW after CREATE")

    def parse_if_not_exists(self):
        if self.accept_keyword("IF"):
            self.expect_keyword("NOT")
            self.expect_keyword("EXISTS")
            return True
        return False

    def parse_create_table(self):
        if_not_exists = self.parse_if_not_exists()
        name = self.expect_ident()
        self.expect_op("(")
        columns = []
        while True:
            col_name = self.expect_ident()
            type_name = self.parse_type_name()
            primary_key = not_null = unique = False
            default = None
            while True:
                if self.accept_keyword("PRIMARY"):
                    self.expect_keyword("KEY")
                    primary_key = True
                elif self.accept_keyword("NOT"):
                    self.expect_keyword("NULL")
                    not_null = True
                elif self.accept_keyword("UNIQUE"):
                    unique = True
                elif self.accept_keyword("DEFAULT"):
                    default = self.parse_expr()
                else:
                    break
            columns.append(ColumnDef(col_name, type_name, primary_key,
                                     not_null, unique, default))
            if self.accept_op(","):
                continue
            break
        self.expect_op(")")
        return CreateTable(name, columns, if_not_exists)

    def parse_type_name(self):
        tok = self.peek()
        if tok.kind == "KEYWORD" and tok.value in ("INTEGER", "INT", "TEXT",
                                                   "VARCHAR", "REAL", "FLOAT",
                                                   "DOUBLE", "BLOB", "BOOLEAN",
                                                   "BOOL", "CHAR", "DATE",
                                                   "DECIMAL", "NUMERIC"):
            self.pos += 1
            base = tok.value
        elif tok.kind == "IDENT":
            self.pos += 1
            base = tok.value.upper()
        else:
            raise SQLError(f"syntax error: expected column type, got {tok.value!r}")
        if self.accept_op("("):
            self.parse_expr()  # 长度/精度参数,忽略
            self.expect_op(")")
        return base

    def parse_create_index(self):
        if_not_exists = self.parse_if_not_exists()
        name = self.expect_ident()
        self.expect_keyword("ON")
        table = self.expect_ident()
        self.expect_op("(")
        columns = [self.expect_ident()]
        while self.accept_op(","):
            columns.append(self.expect_ident())
        self.expect_op(")")
        return CreateIndex(name, table, columns, if_not_exists)

    def parse_create_view(self):
        if_not_exists = self.parse_if_not_exists()
        name = self.expect_ident()
        self.expect_keyword("AS")
        select = self.parse_select()
        return CreateView(name, select, if_not_exists)

    def parse_drop(self):
        self.expect_keyword("DROP")
        if self.accept_keyword("TABLE"):
            if_exists = self.parse_if_exists()
            return DropTable(self.expect_ident(), if_exists)
        if self.accept_keyword("INDEX"):
            if_exists = self.parse_if_exists()
            return DropIndex(self.expect_ident(), if_exists)
        if self.accept_keyword("VIEW"):
            if_exists = self.parse_if_exists()
            return DropView(self.expect_ident(), if_exists)
        raise SQLError("syntax error: expected TABLE/INDEX/VIEW after DROP")

    def parse_if_exists(self):
        if self.accept_keyword("IF"):
            self.expect_keyword("EXISTS")
            return True
        return False

    def parse_insert(self):
        self.expect_keyword("INSERT")
        self.expect_keyword("INTO")
        table = self.expect_ident()
        columns = None
        if self.accept_op("("):
            columns = [self.expect_ident()]
            while self.accept_op(","):
                columns.append(self.expect_ident())
            self.expect_op(")")
        self.expect_keyword("VALUES")
        rows = []
        while True:
            self.expect_op("(")
            row = [self.parse_expr()]
            while self.accept_op(","):
                row.append(self.parse_expr())
            self.expect_op(")")
            rows.append(row)
            if self.accept_op(","):
                continue
            break
        return Insert(table, columns, rows)

    def parse_update(self):
        self.expect_keyword("UPDATE")
        table = self.expect_ident()
        self.expect_keyword("SET")
        assignments = []
        while True:
            col = self.expect_ident()
            self.expect_op("=")
            assignments.append((col, self.parse_expr()))
            if self.accept_op(","):
                continue
            break
        where = None
        if self.accept_keyword("WHERE"):
            where = self.parse_expr()
        return Update(table, assignments, where)

    def parse_delete(self):
        self.expect_keyword("DELETE")
        self.expect_keyword("FROM")
        table = self.expect_ident()
        where = None
        if self.accept_keyword("WHERE"):
            where = self.parse_expr()
        return Delete(table, where)

    # -- SELECT -------------------------------------------------------------
    def parse_select(self):
        self.expect_keyword("SELECT")
        distinct = False
        if self.accept_keyword("DISTINCT"):
            distinct = True
        elif self.accept_keyword("ALL"):
            pass
        items = []
        while True:
            items.append(self.parse_select_item())
            if self.accept_op(","):
                continue
            break
        from_table = None
        if self.accept_keyword("FROM"):
            from_table = self.expect_ident()
        where = None
        if self.accept_keyword("WHERE"):
            where = self.parse_expr()
        group_by = None
        if self.accept_keyword("GROUP"):
            self.expect_keyword("BY")
            group_by = [self.parse_expr()]
            while self.accept_op(","):
                group_by.append(self.parse_expr())
        having = None
        if self.accept_keyword("HAVING"):
            having = self.parse_expr()
        order_by = None
        if self.accept_keyword("ORDER"):
            self.expect_keyword("BY")
            order_by = []
            while True:
                expr = self.parse_expr()
                desc = False
                if self.accept_keyword("DESC"):
                    desc = True
                elif self.accept_keyword("ASC"):
                    desc = False
                order_by.append(OrderItem(expr, desc))
                if self.accept_op(","):
                    continue
                break
        limit = offset = None
        if self.accept_keyword("LIMIT"):
            limit = self.parse_expr()
            if self.accept_keyword("OFFSET"):
                offset = self.parse_expr()
            elif self.accept_op(","):
                offset = limit
                limit = self.parse_expr()
        return Select(distinct, items, from_table, where, group_by, having,
                      order_by, limit, offset)

    def parse_select_item(self):
        if self.peek().kind == "OP" and self.peek().value == "*":
            self.pos += 1
            return SelectItem(Star())
        if self.peek().kind == "IDENT" and self.peek().value == "*":
            self.pos += 1
            return SelectItem(Star())
        expr = self.parse_expr()
        alias = None
        if self.accept_keyword("AS"):
            alias = self.expect_ident()
        elif self.peek().kind == "IDENT" and not self._is_reserved(self.peek().value):
            alias = self.next().value
        return SelectItem(expr, alias)

    @staticmethod
    def _is_reserved(word):
        return word.upper() in KEYWORDS

    # -- expressions --------------------------------------------------------
    def parse_expr(self):
        return self.parse_or()

    def parse_or(self):
        left = self.parse_and()
        while self.accept_keyword("OR"):
            left = Binary("OR", left, self.parse_and())
        return left

    def parse_and(self):
        left = self.parse_not()
        while self.accept_keyword("AND"):
            left = Binary("AND", left, self.parse_not())
        return left

    def parse_not(self):
        if self.accept_keyword("NOT"):
            return Unary("NOT", self.parse_not())
        return self.parse_comparison()

    def parse_comparison(self):
        left = self.parse_additive()
        while True:
            tok = self.peek()
            if tok.kind == "OP" and tok.value in ("=", "==", "!=", "<>", "<",
                                                  "<=", ">", ">="):
                self.pos += 1
                left = Binary(tok.value, left, self.parse_additive())
            elif tok.kind == "KEYWORD" and tok.value == "IS":
                self.pos += 1
                neg = self.accept_keyword("NOT")
                self.expect_keyword("NULL")
                left = Binary("IS NOT NULL" if neg else "IS NULL", left, Literal(None))
            elif tok.kind == "KEYWORD" and tok.value == "IN":
                self.pos += 1
                self.expect_op("(")
                args = []
                if not self.accept_op(")"):
                    args.append(self.parse_expr())
                    while self.accept_op(","):
                        args.append(self.parse_expr())
                    self.expect_op(")")
                left = Binary("IN", left, args)
            elif tok.kind == "KEYWORD" and tok.value == "LIKE":
                self.pos += 1
                left = Binary("LIKE", left, self.parse_additive())
            elif tok.kind == "KEYWORD" and tok.value == "BETWEEN":
                self.pos += 1
                lo = self.parse_additive()
                self.expect_keyword("AND")
                hi = self.parse_additive()
                left = Binary("BETWEEN", left, (lo, hi))
            else:
                break
        return left

    def parse_additive(self):
        left = self.parse_multiplicative()
        while True:
            tok = self.peek()
            if tok.kind == "OP" and tok.value in ("+", "-"):
                self.pos += 1
                left = Binary(tok.value, left, self.parse_multiplicative())
            elif tok.kind == "OP" and tok.value == "||":
                self.pos += 1
                left = Binary("||", left, self.parse_multiplicative())
            else:
                break
        return left

    def parse_multiplicative(self):
        left = self.parse_unary()
        while True:
            tok = self.peek()
            if tok.kind == "OP" and tok.value in ("*", "/", "%"):
                self.pos += 1
                left = Binary(tok.value, left, self.parse_unary())
            else:
                break
        return left

    def parse_unary(self):
        if self.accept_op("-"):
            return Unary("-", self.parse_unary())
        if self.accept_op("+"):
            return self.parse_unary()
        return self.parse_primary()

    def parse_primary(self):
        tok = self.peek()
        if tok.kind == "NUMBER":
            self.pos += 1
            return Literal(tok.value)
        if tok.kind == "STRING":
            self.pos += 1
            return Literal(tok.value)
        if tok.kind == "KEYWORD":
            if tok.value == "NULL":
                self.pos += 1
                return Literal(None)
            if tok.value == "TRUE":
                self.pos += 1
                return Literal(1)
            if tok.value == "FALSE":
                self.pos += 1
                return Literal(0)
            if tok.value == "CASE":
                return self.parse_case()
            if tok.value == "NOT":
                return Unary("NOT", self.parse_not())
        if tok.kind == "OP" and tok.value == "(":
            self.pos += 1
            expr = self.parse_expr()
            self.expect_op(")")
            return expr
        if tok.kind in ("IDENT", "KEYWORD"):
            # 函数调用或列引用
            name = self.next().value
            if self.accept_op("("):
                distinct = False
                if self.accept_keyword("DISTINCT"):
                    distinct = True
                args = []
                if not self.accept_op(")"):
                    if self.accept_op("*"):
                        args.append(Star())
                    else:
                        args.append(self.parse_expr())
                    while self.accept_op(","):
                        args.append(self.parse_expr())
                    self.expect_op(")")
                return FunctionCall(name.upper(), args, distinct)
            if self.accept_op("."):
                col = self.expect_ident()
                return ColumnRef(name, col)
            return ColumnRef(None, name)
        raise SQLError(f"syntax error: unexpected token {tok.value!r}")

    def parse_case(self):
        self.expect_keyword("CASE")
        operand = None
        if self.peek().kind != "KEYWORD" or self.peek().value != "WHEN":
            operand = self.parse_expr()
        whens = []
        while self.accept_keyword("WHEN"):
            when_expr = self.parse_expr()
            self.expect_keyword("THEN")
            then_expr = self.parse_expr()
            whens.append((when_expr, then_expr))
        else_expr = None
        if self.accept_keyword("ELSE"):
            else_expr = self.parse_expr()
        self.expect_keyword("END")
        return CaseExpr(operand, whens, else_expr)


def parse_sql(sql):
    """解析单条 SQL,返回 AST 节点。

    容忍语句末尾的分号(sqllogictest 测试文件常带)。
    """
    sql = sql.rstrip().rstrip(";").rstrip()
    parser = Parser(sql)
    stmt = parser.parse_statement()
    if not parser.at_end():
        tok = parser.peek()
        raise SQLError(f"syntax error: unexpected trailing token {tok.value!r}")
    return stmt
