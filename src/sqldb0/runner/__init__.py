"""sqllogictest runner:文件解析、执行、逐条 pass/fail 报告。"""

from .runner import run_file, run_path, main

__all__ = ["run_file", "run_path", "main"]
