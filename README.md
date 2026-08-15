# sql-db-0

SQL 数据库引擎实现项目。本仓库承载一个从零实现的、最小可用的 SQL 数据库引擎
(`sqldb0`),以及一个可对任意 sqllogictest 测试文件端到端执行并输出逐条
pass/fail 报告的 runner。

## 目录结构

```
├── docs/
│   ├── language-selection.md   # 实现语言选型决策记录(ADR)
│   └── sqllogictest.md         # sqllogictest 版本/commit 与测试文件清单(权威定义)
├── src/sqldb0/
│   ├── engine/                 # SQL 引擎:词法/语法解析、表达式求值、执行
│   └── runner/                 # sqllogictest runner:文件解析、执行、逐条报告
├── tests/                      # 引擎与 runner 的单元测试(unittest)
├── sqllogictest/
│   ├── MANIFEST.md             # 本项目测试基座的文件清单
│   └── tests/                  # 测试基座:sqllogictest 格式的测试文件
├── pyproject.toml              # 构建系统(setuptools)
└── Makefile                    # 构建/测试/运行命令
```

## 构建与测试命令

```bash
make build   # 构建:字节码编译全部源码,验证可构建
make test    # 运行单元测试(unittest)
make run     # 运行测试基座:对 sqllogictest/tests/ 下全部文件执行 sqllogictest runner
make ci      # 构建 + 单元测试 + 测试基座(CI 与本地一致)
```

也可以直接调用 runner:

```bash
# 对单个文件执行并输出 JSON 报告
PYTHONPATH=src python3 -m sqldb0.runner sqllogictest/tests/000_basic.test --json -

# 对目录下全部 *.test 文件执行
PYTHONPATH=src python3 -m sqldb0.runner sqllogictest/tests --json report.json
```

runner 退出码:全部通过为 0,存在失败为 1。

## 语言选型

实现语言为 **Python 3(仅标准库,零外部依赖)**,构建系统为
**setuptools(pyproject.toml)**。决策理由见
[docs/language-selection.md](docs/language-selection.md)。

## sqllogictest 集成

- 固定的 sqllogictest 版本/commit 与测试文件清单见
  [docs/sqllogictest.md](docs/sqllogictest.md)。
- 本项目测试基座的文件清单见 [sqllogictest/MANIFEST.md](sqllogictest/MANIFEST.md)。

## CI

每次推送自动运行测试基座(GitHub Actions),见 `.github/workflows/ci.yml`。
