"""sqllogictest 测试文件解析。

格式规范见 sqllogictest 项目(gregrahn/sqllogictest)的 Test-Script Format:
- 记录(record)之间以空行分隔;以 # 开头的行是注释,预处理时移除。
- statement ok|error|count N:期望成功/失败/影响 N 行。
- query <type-string> [<sort-mode>] [<label>]:type-string 每列一个字符
  (I/R/T/B);sort-mode 为 nosort/rowsort/valuesort;label 用于跨查询结果一致性。
- 查询的 SQL 之后以 "----" 行(可带列数)分隔期望结果,结果逐行排列到空行。
- hash-threshold N:结果超过 N 个值时以 MD5 哈希表示。
- halt:停止处理后续记录。
- skipif/onlyif <db>:按引擎名条件跳过/执行记录。
"""

from dataclasses import dataclass, field


class SLTParseError(Exception):
    """sqllogictest 文件解析错误。"""


@dataclass
class Record:
    line: int  # 记录首行在原始文件中的行号
    kind: str  # "statement" | "query" | "hash-threshold" | "halt"
    conditionals: list = field(default_factory=list)  # [(kind, db_name), ...]


@dataclass
class StatementRecord(Record):
    expect: str = "ok"  # "ok" | "error" | "count"
    count: int = None
    sql: str = ""


@dataclass
class QueryRecord(Record):
    type_string: str = ""
    sort_mode: str = "nosort"
    label: str = ""
    sql: str = ""
    expected: list = None  # 期望结果行(渲染文本);None 表示无期望
    expected_hash: str = None  # "N values hashing to <md5>"
    column_counts: list = None


@dataclass
class ControlRecord(Record):
    value: int = None


def _strip_comments(lines):
    """移除注释行,返回 [(line_no, text), ...]。"""
    out = []
    for no, text in lines:
        if text.lstrip().startswith("#"):
            continue
        out.append((no, text))
    return out


def _strip_inline_comment(text):
    """去掉行内注释(从 # 到行尾),用于记录头行。"""
    idx = text.find("#")
    if idx >= 0:
        return text[:idx]
    return text


def parse_test_file(path):
    """解析 sqllogictest 文件,返回 Record 列表。"""
    with open(path, "r", encoding="utf-8") as f:
        raw = [(i + 1, line.rstrip("\n")) for i, line in enumerate(f)]
    lines = _strip_comments(raw)
    records = []
    i = 0
    n = len(lines)
    while i < n:
        no, text = lines[i]
        if text.strip() == "":
            i += 1
            continue
        start_line = no
        conditionals = []
        while True:
            stripped = _strip_inline_comment(text).strip()
            if stripped.startswith("skipif") or stripped.startswith("onlyif"):
                parts = stripped.split()
                if len(parts) < 2:
                    raise SLTParseError(
                        f"{path}:{no}: malformed conditional {stripped!r}")
                conditionals.append((parts[0], parts[1]))
                i += 1
                if i >= n:
                    raise SLTParseError(f"{path}:{no}: conditional without record")
                no, text = lines[i]
            else:
                break
        stripped = _strip_inline_comment(text).strip()
        parts = stripped.split()
        head = parts[0]
        if head == "statement":
            if len(parts) < 2 or parts[1] not in ("ok", "error", "count"):
                raise SLTParseError(
                    f"{path}:{no}: statement expects ok/error/count, got {stripped!r}")
            expect = parts[1]
            count = None
            if expect == "count":
                if len(parts) < 3:
                    raise SLTParseError(f"{path}:{no}: statement count needs a number")
                count = int(parts[2])
            i += 1
            sql_lines = []
            while i < n and lines[i][1].strip() != "":
                sql_lines.append(lines[i][1])
                i += 1
            records.append(StatementRecord(
                line=start_line, kind="statement", conditionals=conditionals,
                expect=expect, count=count, sql="\n".join(sql_lines)))
        elif head == "query":
            if len(parts) < 2:
                raise SLTParseError(f"{path}:{no}: query needs a type string")
            type_string = parts[1]
            sort_mode = "nosort"
            label = ""
            for tok in parts[2:]:
                if tok in ("nosort", "rowsort", "valuesort"):
                    sort_mode = tok
                else:
                    label = tok
            i += 1
            sql_lines = []
            while i < n:
                ln, txt = lines[i]
                if txt.strip() == "":
                    break
                if txt.lstrip().startswith("----"):
                    break
                sql_lines.append(txt)
                i += 1
            expected = None
            expected_hash = None
            column_counts = None
            if i < n and lines[i][1].lstrip().startswith("----"):
                rest = lines[i][1].lstrip()[4:].strip()
                if rest:
                    column_counts = [int(x) for x in rest.split()]
                i += 1
                expected = []
                while i < n and lines[i][1].strip() != "":
                    expected.append(lines[i][1])
                    i += 1
                if expected and "values hashing to" in expected[0]:
                    expected_hash = expected[0]
                    expected = None
            records.append(QueryRecord(
                line=start_line, kind="query", conditionals=conditionals,
                type_string=type_string, sort_mode=sort_mode, label=label,
                sql="\n".join(sql_lines), expected=expected,
                expected_hash=expected_hash, column_counts=column_counts))
        elif head == "hash-threshold":
            if len(parts) < 2:
                raise SLTParseError(f"{path}:{no}: hash-threshold needs a number")
            records.append(ControlRecord(
                line=start_line, kind="hash-threshold",
                conditionals=conditionals, value=int(parts[1])))
            i += 1
        elif head == "halt":
            records.append(ControlRecord(
                line=start_line, kind="halt", conditionals=conditionals))
            i += 1
        else:
            raise SLTParseError(f"{path}:{no}: unknown record type {head!r}")
    return records
