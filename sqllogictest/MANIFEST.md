# 测试基座清单(MANIFEST)

本项目 "ALL sqllogictest test cases" 的权威定义见
[docs/sqllogictest.md](../docs/sqllogictest.md)。本文件是测试基座
(`sqllogictest/tests/`)的机器可读清单。

## 固定上游

- 仓库:https://github.com/gregrahn/sqllogictest
- commit:`c67f97bf3ca7e590d12e073408bcacaf2ff0f3a0`(2026-04-15)

## 测试文件清单

| 文件 | 来源 | 说明 |
|------|------|------|
| `tests/000_basic.test` | 自写 | DDL/DML 基础 |
| `tests/010_expressions.test` | 自写 | 表达式、运算符、函数 |
| `tests/020_aggregates.test` | 自写 | 聚合与 GROUP BY |
| `tests/030_views_indexes.test` | 自写 | 视图与索引 |
| `tests/040_errors.test` | 自写 | 期望失败的语句 |
| `tests/050_ordering.test` | 自写 | 排序、去重、限制 |
| `tests/vendor/slt_lang_droptable.test` | 上游 vendored | DROP TABLE 语义 |
| `tests/vendor/slt_lang_dropindex.test` | 上游 vendored | DROP INDEX 语义 |
| `tests/vendor/slt_lang_dropview.test` | 上游 vendored | DROP VIEW 语义 |

## 运行

```bash
make run
# 或
PYTHONPATH=src python3 -m sqldb0.runner sqllogictest/tests --json report.json
```

退出码:全部通过为 0,存在失败为 1。
