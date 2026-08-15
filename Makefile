PYTHON ?= python3
PYTHONPATH := src

.PHONY: build test run test-base ci

## 构建:字节码编译全部源码,验证可构建
build:
	$(PYTHON) -m compileall -q src tests

## 单元测试
test:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m unittest discover -s tests -v

## 运行测试基座:对 sqllogictest/tests/ 下全部文件执行 sqllogictest runner
run:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m sqldb0.runner sqllogictest/tests --json /tmp/sqldb0-slt-report.json

## 测试基座别名
test-base: run

## CI 全流程:构建 + 单元测试 + 测试基座
ci: build test run
