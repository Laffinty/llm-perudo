#!/usr/bin/env python3
"""规则追溯矩阵检查器（R-xx ↔ 测试 ID 孤儿检查）。

用途
    检查 `tests/traceability.md` 规则追溯矩阵中是否存在「孤儿规则」——
    即：规则已登记，但没有任何测试 ID 指向它。矩阵中的每一条规则都必须
    至少被一个测试覆盖（见 `docs/plan/01-build-plan.md` §4.1）。

用法
    uv run python scripts/check_traceability.py
    uv run python scripts/check_traceability.py --path <矩阵文件路径>

    `--path` 默认指向仓库根下的 `tests/traceability.md`；传入相对路径时，
    先按当前工作目录解析，找不到再按仓库根解析。传入绝对路径时直接使用。
    该参数用于在临时目录里用矩阵副本自测，不会触碰仓库中的真实文件。

判定规则（按序执行）
    1. 矩阵文件缺失 / 表头缺失 / 表格结构无法解析  -> 打印中文错误信息，退出码 2
    2. 规则 ID 格式非法（非 `R-<数字>`）、状态列取值非 `pending`/`covered`
       -> 打印中文错误信息并指出行号，退出码 2
       （格式校验与覆盖状态无关：矩阵自身写错时，一律按错误处理，
         不会因为「尚未启用」而被放过）
    3. 矩阵中没有任何 `covered` 行 -> 打印「矩阵尚未启用（P1 待填充），N 条规则待填」，
       退出码 0（矩阵尚未启用，孤儿检查暂不生效）
    4. 存在 `covered` 行：
       - 有规则行未填测试 ID（孤儿）-> 打印孤儿清单，退出码 1
       - 全部规则行都填了测试 ID    -> 打印「通过：N 条规则全部有测试覆盖」，退出码 0

退出码
    0 = 通过
    1 = 存在孤儿规则（有 `covered` 行，但仍有规则行没有测试 ID）
    2 = 错误（矩阵缺失、表头缺失、表格结构无法解析、规则 ID 或状态取值非法）

依赖
    仅使用 Python 标准库，Python 3.12+ 兼容。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

EXIT_OK = 0
EXIT_ORPHAN = 1
EXIT_ERROR = 2

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MATRIX = REPO_ROOT / "tests" / "traceability.md"

RULE_ID_RE = re.compile(r"R-\d+")
VALID_STATUS = ("pending", "covered")

# 视为「未填测试 ID」的写法
EMPTY_TEST_IDS = {
    "",
    "-",
    "--",
    "—",
    "–",
    "－",
    "无",
    "N/A",
    "n/a",
    "TODO",
    "待填",
    "待定",
}

# 表格分隔行（形如 | --- | :---: |）
SEPARATOR_RE = re.compile(r"^:?-{1,}:?$")

FENCE_RE = re.compile(r"^\s*(```|~~~)")

# 一个 Markdown 表格：(表头行号, 表头单元格列表, [(数据行行号, 数据行单元格列表)])
Table = tuple[int, list[str], list[tuple[int, list[str]]]]


# --------------------------------------------------------------------------- #
# 文本工具
# --------------------------------------------------------------------------- #


def _strip_markdown(cell: str) -> str:
    """去掉单元格里的 markdown 装饰（粗体、代码、反引号、空白）。"""
    text = cell.strip()
    text = text.replace("`", "")
    while text.startswith("**") and text.endswith("**") and len(text) > 4:
        text = text[2:-2].strip()
    while text.startswith("*") and text.endswith("*") and len(text) > 2:
        text = text[1:-1].strip()
    text = text.replace("**", "")
    return text.strip()


def _normalize_header(cell: str) -> str:
    """表头归一化：去掉空白与 markdown 装饰，转小写。"""
    return _strip_markdown(cell).replace(" ", "").replace("　", "").lower()


def _split_row(line: str) -> list[str]:
    """把一行 Markdown 表格拆成单元格列表（不含首尾空单元格）。"""
    stripped = line.strip()
    if not stripped.startswith("|"):
        return []
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    # 去掉行首的竖线，避免产生一个空的占位单元格
    if stripped.startswith("|"):
        stripped = stripped[1:]
    return [cell.strip() for cell in stripped.split("|")]


def _is_separator(cells: list[str]) -> bool:
    if not cells:
        return False
    return all(SEPARATOR_RE.match(cell.replace(" ", "")) for cell in cells)


def _find_tables(lines: list[str]) -> list[Table]:
    """扫描文档，返回所有表格：(表头行号, 表头单元格, [(数据行行号, 数据行单元格)])。

    代码块（``` / ~~~ 围栏）内的内容一律忽略。
    """
    tables: list[Table] = []
    in_fence = False
    fence_marker = ""
    i = 0
    n = len(lines)

    while i < n:
        line = lines[i]
        fence = FENCE_RE.match(line)
        if fence:
            marker = fence.group(1)
            if not in_fence:
                in_fence = True
                fence_marker = marker
            elif marker == fence_marker:
                in_fence = False
                fence_marker = ""
            i += 1
            continue
        if in_fence:
            i += 1
            continue

        if line.strip().startswith("|"):
            header_cells = _split_row(line)
            if i + 1 < n and _is_separator(_split_row(lines[i + 1])) and header_cells:
                data_rows: list[tuple[int, list[str]]] = []
                j = i + 2
                while j < n and lines[j].strip().startswith("|"):
                    data_rows.append((j + 1, _split_row(lines[j])))
                    j += 1
                tables.append((i + 1, header_cells, data_rows))
                i = j
                continue
        i += 1

    return tables


# --------------------------------------------------------------------------- #
# 列识别
# --------------------------------------------------------------------------- #


def _is_rule_header(normalized: str) -> bool:
    if "规则" in normalized:
        return "id" in normalized or "编号" in normalized
    return normalized in {"ruleid", "rule", "rule no", "ruleno"}


def _is_test_header(normalized: str) -> bool:
    if "测试" in normalized or "用例" in normalized:
        return (
            "id" in normalized
            or "编号" in normalized
            or normalized
            in {
                "测试",
                "测试用例",
            }
        )
    return normalized in {"testid", "test"}


def _is_summary_header(normalized: str) -> bool:
    return "摘要" in normalized or "概要" in normalized or "说明" in normalized


def _is_source_header(normalized: str) -> bool:
    return "出处" in normalized or "来源" in normalized or "定位" in normalized


def _is_status_header(normalized: str) -> bool:
    return "状态" in normalized or normalized == "status"


# --------------------------------------------------------------------------- #
# 矩阵解析
# --------------------------------------------------------------------------- #


class MatrixError(Exception):
    """矩阵文件本身出错（对应退出码 2）。"""


class Row:
    """矩阵中的一行规则。"""

    __slots__ = ("line_no", "rule_id", "summary", "source", "test_id", "status")

    def __init__(
        self,
        line_no: int,
        rule_id: str,
        summary: str,
        source: str,
        test_id: str | None,
        status: str,
    ) -> None:
        self.line_no = line_no
        self.rule_id = rule_id
        self.summary = summary
        self.source = source
        self.test_id = test_id
        self.status = status


class Matrix:
    """解析后的规则矩阵。"""

    def __init__(self, path: Path, rows: list[Row]) -> None:
        self.path = path
        self.rows = rows

    @property
    def total(self) -> int:
        return len(self.rows)

    @property
    def covered(self) -> list[Row]:
        return [row for row in self.rows if row.status == "covered"]

    @property
    def orphans(self) -> list[Row]:
        return [row for row in self.rows if row.test_id is None]


def _classify_columns(header: list[str]) -> dict[str, int] | None:
    """在表头中识别「规则 ID」「测试 ID」（以及可选的摘要/出处/状态）列。"""
    cols: dict[str, int] = {}
    for idx, cell in enumerate(header):
        normalized = _normalize_header(cell)
        if not normalized:
            continue
        if "rule" not in cols and _is_rule_header(normalized):
            cols["rule"] = idx
        elif "test" not in cols and _is_test_header(normalized):
            cols["test"] = idx
        elif "status" not in cols and _is_status_header(normalized):
            cols["status"] = idx
        elif "summary" not in cols and _is_summary_header(normalized):
            cols["summary"] = idx
        elif "source" not in cols and _is_source_header(normalized):
            cols["source"] = idx
    if "rule" not in cols or "test" not in cols:
        return None
    return cols


def parse_matrix(path: Path) -> Matrix:
    """解析矩阵文件，失败时抛出 MatrixError。"""
    try:
        raw = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        raise MatrixError(f"找不到矩阵文件：{path}") from None
    except OSError as exc:
        raise MatrixError(f"读取矩阵文件失败：{path}（{exc}）") from None

    lines = raw.splitlines()
    tables = _find_tables(lines)

    best: Table | None = None
    best_cols: dict[str, int] | None = None
    best_count = -1

    for table in tables:
        cols = _classify_columns(table[1])
        if cols is None:
            continue
        count = sum(
            1
            for _, cells in table[2]
            if cells and RULE_ID_RE.match(_strip_markdown(cells[cols["rule"]]))
        )
        if count > best_count:
            best = table
            best_cols = cols
            best_count = count

    if best is None or best_cols is None:
        raise MatrixError(
            f"在 {path} 中找不到规则矩阵表格：表头必须同时包含「规则 ID」与「测试 ID」两列"
        )

    if "status" not in best_cols:
        raise MatrixError(
            f"在 {path} 中找不到「状态」列：矩阵必须包含取值仅为 pending / covered 的状态列"
        )

    rows: list[Row] = []
    for line_no, cells in best[2]:
        if not cells or all(not cell.strip() for cell in cells):
            continue

        rule_idx = best_cols["rule"]
        test_idx = best_cols["test"]
        status_idx = best_cols["status"]
        summary_idx = best_cols.get("summary")
        source_idx = best_cols.get("source")

        if rule_idx >= len(cells):
            raise MatrixError(f"第 {line_no} 行的列数不足，无法读取「规则 ID」列")
        if test_idx >= len(cells):
            raise MatrixError(f"第 {line_no} 行的列数不足，无法读取「测试 ID」列")
        if status_idx >= len(cells):
            raise MatrixError(f"第 {line_no} 行的列数不足，无法读取「状态」列")

        rule_raw = _strip_markdown(cells[rule_idx])
        if not rule_raw:
            raise MatrixError(f"第 {line_no} 行的「规则 ID」列为空")
        if not RULE_ID_RE.fullmatch(rule_raw):
            raise MatrixError(
                f"第 {line_no} 行的规则 ID 非法：{rule_raw}（应为 R-<数字> 形式，如 R-12）"
            )

        test_raw = _strip_markdown(cells[test_idx])
        test_id = None if test_raw in EMPTY_TEST_IDS else test_raw

        status = _strip_markdown(cells[status_idx]).lower()
        if status not in VALID_STATUS:
            raise MatrixError(
                f"第 {line_no} 行的状态取值非法：{status!r}（只允许 pending / covered）"
            )

        summary = ""
        if summary_idx is not None and summary_idx < len(cells):
            summary = _strip_markdown(cells[summary_idx])
        source = ""
        if source_idx is not None and source_idx < len(cells):
            source = _strip_markdown(cells[source_idx])

        rows.append(Row(line_no, rule_raw, summary, source, test_id, status))

    if not rows:
        raise MatrixError(f"{path} 中的规则矩阵没有任何数据行")

    return Matrix(path, rows)


# --------------------------------------------------------------------------- #
# 检查主流程
# --------------------------------------------------------------------------- #


def check(matrix: Matrix) -> int:
    """执行孤儿检查，返回进程退出码。"""
    duplicates = _find_duplicates(matrix.rows)
    if duplicates:
        print("警告：矩阵中存在重复的规则 ID（同一规则登记了多行）：")
        for rule_id in duplicates:
            print(f"  - {rule_id}")

    if not matrix.covered:
        print(f"矩阵尚未启用（P1 待填充），{matrix.total} 条规则待填")
        print("提示：出现任意一条 covered 行后，孤儿检查立即生效。")
        return EXIT_OK

    orphans = matrix.orphans
    if orphans:
        print(f"追溯矩阵检查失败：存在 {len(orphans)} 条孤儿规则（无测试 ID）。")
        print("孤儿清单：")
        for row in orphans:
            detail = f"  - {row.rule_id}"
            if row.summary:
                detail += f" | {row.summary}"
            if row.source:
                detail += f" | 出处：{row.source}"
            detail += f" | 矩阵行号：{row.line_no}"
            print(detail)
        print(
            f"合计：{matrix.total} 条规则，{len(matrix.covered)} 条已标记 covered，"
            f"{len(orphans)} 条孤儿。"
        )
        print("请为上述规则补上测试 ID，并把状态改为 covered。")
        return EXIT_ORPHAN

    print(f"通过：{matrix.total} 条规则全部有测试覆盖")
    return EXIT_OK


def _find_duplicates(rows: list[Row]) -> list[str]:
    seen: set[str] = set()
    dups: list[str] = []
    for row in rows:
        if row.rule_id in seen and row.rule_id not in dups:
            dups.append(row.rule_id)
        seen.add(row.rule_id)
    return dups


def _resolve_matrix_path(raw: str | None) -> Path:
    """解析矩阵文件路径。"""
    if raw is None:
        return DEFAULT_MATRIX
    candidate = Path(raw)
    if candidate.is_absolute():
        return candidate
    from_cwd = (Path.cwd() / candidate).resolve()
    if from_cwd.exists():
        return from_cwd
    from_root = (REPO_ROOT / candidate).resolve()
    if from_root.exists():
        return from_root
    # 都不存在时返回按当前工作目录解析的路径，让错误信息指向用户给的位置
    return from_cwd


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="检查 R-xx 规则追溯矩阵是否存在孤儿规则（无测试 ID 的规则）。",
    )
    parser.add_argument(
        "--path",
        default=None,
        help="矩阵文件路径（默认：tests/traceability.md）",
    )
    args = parser.parse_args(argv)

    path = _resolve_matrix_path(args.path)

    try:
        matrix = parse_matrix(path)
    except MatrixError as exc:
        print(f"错误：{exc}")
        return EXIT_ERROR

    return check(matrix)


if __name__ == "__main__":
    sys.exit(main())
