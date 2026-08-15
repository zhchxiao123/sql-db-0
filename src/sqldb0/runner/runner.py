"""sqllogictest runner:对引擎执行测试文件,输出逐条 pass/fail 报告。

用法:
    python3 -m sqldb0.runner <file-or-dir> [--json FILE] [--engine-name NAME]

退出码:全部通过为 0,存在失败为 1。
"""

import hashlib
import json
import os
import sys

from .. import ENGINE_NAME
from ..engine import Engine, SQLError
from ..engine.values import render_value, value_type_char, type_matches
from .slt_parser import parse_test_file, SLTParseError

SCHEMA_VERSION = 1
RUNNER_NAME = "sqldb0-sqllogictest-runner"


def _md5(values):
    h = hashlib.md5()
    for v in values:
        h.update(v.encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()


def _conditionals_skip(conditionals, engine_name):
    for kind, db in conditionals:
        match = db.lower() == engine_name.lower()
        if kind == "skipif" and match:
            return True
        if kind == "onlyif" and not match:
            return True
    return False


def _case(rec, status, detail=None, extra=None):
    case = {
        "index": 0,
        "line": rec.line,
        "kind": rec.kind,
        "status": status,
        "detail": detail,
    }
    if rec.kind == "statement":
        case["expect"] = rec.expect if rec.expect != "count" else f"count {rec.count}"
        case["sql"] = rec.sql
    else:
        case["expect"] = rec.type_string
        if rec.sort_mode != "nosort":
            case["expect"] += f" {rec.sort_mode}"
        if rec.label:
            case["expect"] += f" {rec.label}"
        case["sql"] = rec.sql
    if extra:
        case.update(extra)
    return case


def _run_statement(rec, engine):
    try:
        affected = engine.statement(rec.sql)
    except SQLError as e:
        if rec.expect == "error":
            return _case(rec, "pass")
        return _case(rec, "fail", detail=f"statement failed: {e}")
    if rec.expect == "ok":
        return _case(rec, "pass")
    if rec.expect == "error":
        return _case(rec, "fail", detail="expected error, statement succeeded")
    if rec.expect == "count":
        if affected == rec.count:
            return _case(rec, "pass")
        return _case(rec, "fail",
                      detail=f"expected {rec.count} rows affected, got {affected}")
    return _case(rec, "fail", detail=f"unknown expectation {rec.expect!r}")


def _diff_detail(expected, actual):
    if len(expected) != len(actual):
        return (f"result row count mismatch: expected {len(expected)} "
                f"values, got {len(actual)}")
    for i, (e, a) in enumerate(zip(expected, actual)):
        if e != a:
            return f"value {i}: wrong result - expected [{e}] got [{a}]"
    return "results differ"


def _run_query(rec, engine, hash_threshold, labels):
    try:
        columns, rows = engine.query(rec.sql)
    except SQLError as e:
        return _case(rec, "fail", detail=f"query failed: {e}")
    rendered = [render_value(v) for row in rows for v in row]
    ncols = len(rec.type_string)

    # 类型串一致性校验
    type_errors = []
    for row in rows:
        for v, tc in zip(row, rec.type_string):
            if not type_matches(v, tc):
                type_errors.append(
                    f"type mismatch: expected {tc}, got "
                    f"{value_type_char(v) or 'NULL'} ({render_value(v)})")

    # 排序模式
    if rec.sort_mode == "rowsort" and ncols > 0:
        groups = [rendered[i:i + ncols] for i in range(0, len(rendered), ncols)]
        groups.sort()
        rendered = [v for g in groups for v in g]
    elif rec.sort_mode == "valuesort":
        rendered.sort()

    ok = True
    detail = None
    if hash_threshold > 0 and len(rendered) > hash_threshold:
        actual = f"{len(rendered)} values hashing to {_md5(rendered)}"
        expected = rec.expected_hash
        if expected is None and rec.expected:
            expected = rec.expected[0]
        if expected != actual:
            ok = False
            detail = f"wrong result hash - expected [{expected}] got [{actual}]"
    else:
        expected = rec.expected or []
        if rendered != expected:
            ok = False
            detail = _diff_detail(expected, rendered)

    # 标签一致性
    if rec.label:
        h = _md5(rendered)
        if rec.label in labels and labels[rec.label] != h:
            ok = False
            detail = (f"labeled result [{rec.label}] does not agree with "
                      "previous values")
        labels[rec.label] = h

    if type_errors:
        ok = False
        detail = "; ".join(type_errors)

    extra = {"columns": columns}
    if not ok:
        extra["actual"] = rendered
        if rec.expected is not None:
            extra["expected"] = rec.expected
    return _case(rec, "pass" if ok else "fail", detail=detail, extra=extra)


def run_file(path, engine, engine_name=ENGINE_NAME, hash_threshold_override=None):
    """对单个测试文件执行,返回逐条报告 dict。"""
    records = parse_test_file(path)
    hash_threshold = 0
    labels = {}
    cases = []
    halted = False
    for rec in records:
        if halted:
            break
        if rec.kind == "hash-threshold":
            if hash_threshold_override is None:
                hash_threshold = rec.value
            continue
        if rec.kind == "halt":
            if not _conditionals_skip(rec.conditionals, engine_name):
                halted = True
            continue
        if _conditionals_skip(rec.conditionals, engine_name):
            cases.append(_case(rec, "skip"))
            continue
        if rec.kind == "statement":
            cases.append(_run_statement(rec, engine))
        elif rec.kind == "query":
            cases.append(_run_query(rec, engine, hash_threshold, labels))
        else:
            cases.append(_case(rec, "fail", detail=f"unknown record {rec.kind!r}"))

    for idx, c in enumerate(cases, 1):
        c["index"] = idx
    summary = {
        "total": len(cases),
        "passed": sum(1 for c in cases if c["status"] == "pass"),
        "failed": sum(1 for c in cases if c["status"] == "fail"),
        "skipped": sum(1 for c in cases if c["status"] == "skip"),
    }
    return {
        "file": path,
        "summary": summary,
        "cases": cases,
    }


def run_path(path, engine, engine_name=ENGINE_NAME, hash_threshold_override=None):
    """对文件或目录执行;目录递归收集 *.test 文件。"""
    if os.path.isdir(path):
        files = []
        for root, _dirs, names in os.walk(path):
            for name in sorted(names):
                if name.endswith(".test"):
                    files.append(os.path.join(root, name))
        files.sort()
    else:
        files = [path]
    file_reports = []
    for f in files:
        try:
            # sqllogictest 语义:每个测试文件从空数据库开始
            file_reports.append(run_file(f, Engine(), engine_name,
                                         hash_threshold_override))
        except SLTParseError as e:
            file_reports.append({
                "file": f,
                "summary": {"total": 0, "passed": 0, "failed": 1, "skipped": 0},
                "cases": [{
                    "index": 1, "line": 0, "kind": "parse-error",
                    "status": "fail", "detail": str(e),
                }],
            })
    total = sum(r["summary"]["total"] for r in file_reports)
    passed = sum(r["summary"]["passed"] for r in file_reports)
    failed = sum(r["summary"]["failed"] for r in file_reports)
    skipped = sum(r["summary"]["skipped"] for r in file_reports)
    return {
        "schema_version": SCHEMA_VERSION,
        "runner": RUNNER_NAME,
        "engine": engine_name,
        "path": path,
        "summary": {
            "files": len(file_reports),
            "total": total,
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
        },
        "files": file_reports,
    }


def main(argv=None):
    import argparse

    parser = argparse.ArgumentParser(
        prog="sqldb0-runner",
        description="sqllogictest runner for the sqldb0 engine")
    parser.add_argument("path", help="sqllogictest 测试文件或目录")
    parser.add_argument("--json", metavar="FILE",
                       help="把 JSON 报告写入 FILE('-' 表示 stdout)")
    parser.add_argument("--engine-name", default=ENGINE_NAME,
                       help="引擎名,用于 skipif/onlyif 匹配(默认 %(default)s)")
    parser.add_argument("--hash-threshold", type=int, default=None,
                       help="覆盖脚本内的 hash-threshold")
    args = parser.parse_args(argv)

    engine = Engine()
    report = run_path(args.path, engine, args.engine_name, args.hash_threshold)

    if args.json:
        text = json.dumps(report, indent=2, ensure_ascii=False)
        if args.json == "-":
            print(text)
        else:
            with open(args.json, "w", encoding="utf-8") as f:
                f.write(text + "\n")

    s = report["summary"]
    print(f"files: {s['files']}  total: {s['total']}  "
          f"passed: {s['passed']}  failed: {s['failed']}  "
          f"skipped: {s['skipped']}", file=sys.stderr)
    for fr in report["files"]:
        fs = fr["summary"]
        if fs["failed"]:
            print(f"  FAIL {fr['file']}: {fs['failed']} failed / "
                  f"{fs['total']} total", file=sys.stderr)
    return 0 if s["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
