"""值模型:sqldb0 内部值的表示、渲染与类型判定。

值用 Python 原生类型表示:
- INTEGER -> int
- REAL    -> float
- TEXT    -> str
- BLOB    -> bytes
- NULL    -> None
"""

# 类型串字符(与 sqllogictest 约定一致)
TYPE_INTEGER = "I"
TYPE_REAL = "R"
TYPE_TEXT = "T"
TYPE_BLOB = "B"


def render_value(v):
    """把内部值渲染为 sqllogictest 结果文本。

    规则(与 sqllogictest 规范一致):
    - NULL 渲染为 "NULL"
    - 整数渲染为 %d
    - 浮点渲染为 %.3f
    - 空字符串渲染为 "(empty)"
    - 不可打印/控制字符渲染为 "@"
    """
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return "%.3f" % v
    if isinstance(v, str):
        if v == "":
            return "(empty)"
        return "".join("@" if ord(c) < 32 or ord(c) > 126 else c for c in v)
    if isinstance(v, bytes):
        return v.hex()
    return str(v)


def value_type_char(v):
    """返回值的类型串字符(I/R/T/B),NULL 返回 None。"""
    if v is None:
        return None
    if isinstance(v, bool):
        return TYPE_INTEGER
    if isinstance(v, int):
        return TYPE_INTEGER
    if isinstance(v, float):
        return TYPE_REAL
    if isinstance(v, str):
        return TYPE_TEXT
    if isinstance(v, bytes):
        return TYPE_BLOB
    return TYPE_TEXT


def type_matches(v, type_char):
    """校验值是否与 sqllogictest 类型串字符一致(NULL 恒通过)。"""
    if v is None:
        return True
    actual = value_type_char(v)
    if type_char == TYPE_INTEGER:
        return actual == TYPE_INTEGER
    if type_char == TYPE_REAL:
        # R 列允许整数结果(渲染为 %.3f 后与期望一致)
        return actual in (TYPE_REAL, TYPE_INTEGER)
    if type_char == TYPE_TEXT:
        return actual == TYPE_TEXT
    if type_char == TYPE_BLOB:
        return actual == TYPE_BLOB
    return True
