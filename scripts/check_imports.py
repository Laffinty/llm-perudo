"""依赖边界检查器 —— 落实构建计划 §2.3 与设计稿 02 A-19。

检查对象：`src/perudo/core/` 与 `src/perudo/engine/`（规则内核与对局编排）。

三条硬约束：

1. **零第三方依赖**（02 A-19）：内核必须是纯 Python 标准库，不得导入
   `httpx` / `fastapi` 等任何三方包，也不得导入 `perudo` 以外的内部包。
2. **禁随机**（02 A-10）：随机源唯一且可注入 —— 一桌局一个种子，种子只进引擎与
   私密记录。内核不得直接 `import random` / `import secrets`，随机必须走注入的 RNG。
3. **禁时钟与网络直调**（§2.3）：引擎须保持同步确定性（02 A-14），不得直接读取
   系统时钟，也不得发起任何网络调用；并发在引擎之外。

用法::

    uv run python scripts/check_imports.py
    uv run python scripts/check_imports.py --path src/perudo --dirs core engine

退出码：

- ``0`` 通过（无违规；目标目录尚不存在时视为通过并提示）
- ``1`` 存在违规，打印逐条明细
- ``2`` 检查器自身出错（路径不存在、无法解析源码等）

说明：目录不存在时**不判红**，因为 P0 阶段内核尚未落地；P1 一旦建立 ``core/``，
本检查即刻自动生效，无需改动 CI 配置。
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

# 允许的第三方之外的例外：项目自身内部包（引擎允许引用内核契约）
ALLOWED_INTERNAL_ROOTS: frozenset[str] = frozenset({"perudo"})

# 禁随机：随机只允许经注入的 RNG 进入引擎（02 A-10）
FORBIDDEN_RANDOM: frozenset[str] = frozenset({"random", "secrets"})

# 禁时钟直调：引擎必须可重放、可确定性复现（02 A-10 / A-14）
FORBIDDEN_CLOCK: frozenset[str] = frozenset({"time", "datetime", "zoneinfo"})

# 禁网络直调：网络属适配层职责（03），引擎不得自行出网
FORBIDDEN_NETWORK: frozenset[str] = frozenset(
    {
        "asyncio",
        "ftplib",
        "http",
        "httpx",
        "smtplib",
        "socket",
        "ssl",
        "telnetlib",
        "urllib",
        "xmlrpc",
    }
)

# 违规分类标签 -> 规则说明
REASON_LABELS: dict[str, str] = {
    "third-party": "第三方依赖（02 A-19：内核零第三方依赖）",
    "random": "直接使用随机源（02 A-10：随机只经注入的 RNG）",
    "clock": "直接读取系统时钟（§2.3：禁时钟直调）",
    "network": "直接访问网络（§2.3：禁网络直调）",
}


def _root_module(module: str) -> str:
    """取导入路径的根包名（``a.b.c`` -> ``a``）。"""
    return module.split(".", 1)[0]


def _is_stdlib(root: str) -> bool:
    """判断根包是否为 Python 标准库。"""
    return root in sys.stdlib_module_names


def _classify(root: str) -> str | None:
    """返回违规分类；合规则返回 ``None``。"""
    if root in FORBIDDEN_RANDOM:
        return "random"
    if root in FORBIDDEN_CLOCK:
        return "clock"
    if root in FORBIDDEN_NETWORK:
        return "network"
    if root in ALLOWED_INTERNAL_ROOTS:
        return None
    if _is_stdlib(root):
        return None
    return "third-party"


def _imports_of(path: Path) -> list[tuple[int, str]]:
    """解析文件中的顶层导入，返回 ``(行号, 根包名)`` 列表。"""
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.append((node.lineno, _root_module(alias.name)))
        elif isinstance(node, ast.ImportFrom):
            # 相对导入（from .x import y）的 module 为 None，属包内引用，放行
            if node.level and node.level > 0:
                continue
            if node.module:
                found.append((node.lineno, _root_module(node.module)))
    return found


def _iter_python_files(directory: Path) -> list[Path]:
    """列出目录下全部 ``.py`` 文件（递归）。"""
    return sorted(p for p in directory.rglob("*.py") if p.is_file())


def check(package_root: Path, dirs: list[str]) -> list[str]:
    """执行检查，返回违规明细列表（每条一行中文说明）。"""
    violations: list[str] = []
    checked_files = 0

    for name in dirs:
        directory = package_root / name
        if not directory.is_dir():
            continue
        for py_file in _iter_python_files(directory):
            checked_files += 1
            rel = py_file.as_posix()
            for lineno, root in _imports_of(py_file):
                category = _classify(root)
                if category is None:
                    continue
                label = REASON_LABELS[category]
                violations.append(f"{rel}:{lineno}: 导入 `{root}` —— {label}")

    print(f"检查目录：{package_root.as_posix()} 的 {', '.join(dirs)}")
    if checked_files == 0:
        print("目标目录尚不存在或无 .py 文件 —— 依赖边界约束暂未生效（P1 内核落地后自动启用）。")
        return violations

    print(f"已扫描 {checked_files} 个 Python 文件。")
    return violations


def main(argv: list[str] | None = None) -> int:
    """命令行入口。返回进程退出码。"""
    parser = argparse.ArgumentParser(
        description="检查 core/ 与 engine/ 的依赖边界（零三方依赖 / 禁随机 / 禁时钟网络）"
    )
    parser.add_argument(
        "--path",
        default="src/perudo",
        help="待检查的包根目录（默认 src/perudo）",
    )
    parser.add_argument(
        "--dirs",
        nargs="+",
        default=["core", "engine"],
        help="待检查的子目录名（默认 core engine）",
    )
    args = parser.parse_args(argv)

    package_root = Path(args.path)
    if not package_root.is_dir():
        print(f"错误：包根目录不存在 —— {package_root.as_posix()}", file=sys.stderr)
        return 2

    violations = check(package_root, list(args.dirs))

    if violations:
        print(f"\n依赖边界违规 {len(violations)} 处：")
        for item in violations:
            print(f"  - {item}")
        return 1

    print("通过：未发现依赖边界违规。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
