"""变异清单检查器 —— 落实构建计划 §4.1 变异清单 v1 与 §4.3 G-mut 门禁。

每条变异 = 故意改坏内核一处；对应测试必须变红（变异被「杀死」）。
全部杀灭 → exit 0；存在存活变异 → exit 1；锚点漂移或基线非绿 → exit 2。

与 `scripts/check_traceability.py` 同风格：纯标准库、零第三方依赖、Python 3.12+。

用法::

    uv run python scripts/check_mutations.py
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MUTATED_SUFFIX = ".mutation_backup"


@dataclass(frozen=True)
class Mutation:
    """一条变异：把 ``find`` 首次出现替换为 ``replace``，测试必须变红。"""

    mid: str
    desc: str
    file: str
    find: str
    replace: str


MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        mid="V-1",
        desc="飞白数量翻倍门槛 ≥2X 被改为 ≥X（R-21）",
        file="src/perudo/core/legality.py",
        find="        need = 2 * current.count",
        replace="        need = current.count",
    ),
    Mutation(
        mid="V-2",
        desc="围骰 +1 被改为 +2（R-39）",
        file="src/perudo/core/counting.py",
        find="        return 6 if cfg.leopard_bonus else n_called + n_ones",
        replace="        return 7 if cfg.leopard_bonus else n_called + n_ones",
    ),
    Mutation(
        mid="V-3",
        desc="D-02 字面计数被改为「任意面值取最大」（count(1) 口径红线）",
        file="src/perudo/core/counting.py",
        find="        return n_called\n    if n_called == 5:",
        replace=(
            "        return max(\n"
            "            [n_called]\n"
            "            + [\n"
            "                sum(1 for d in dice if d == f or d == Face.ONE)\n"
            "                for f in (Face.TWO, Face.THREE, Face.FOUR, Face.FIVE, Face.SIX)\n"
            "            ]\n"
            "        )\n"
            "        if n_called == 5:"
        ),
    ),
    Mutation(
        mid="V-4",
        desc="判定方向反转 ≥ 被改为 <（R-45）",
        file="src/perudo/core/settlement.py",
        find="    return count >= bid.count",
        replace="    return count < bid.count",
    ),
    Mutation(
        mid="V-5",
        desc="投降减半丢保底 1 码（R-52 / §12 第 12 项）",
        file="src/perudo/core/settlement.py",
        find="            codes = max(1, codes)",
        replace="            codes = int(multiplier)",
    ),
    Mutation(
        mid="V-6",
        desc="转斋被误加「同数量点数须更大」约束（R-20）",
        file="src/perudo/core/legality.py",
        find=(
            "        return LegalityVerdict.ok()  # 转斋：点数任意，"
            '不受"同数量点数须更大"约束（R-20）'
        ),
        replace=(
            "        if bid.count == current.count and not face_beats(\n"
            "            bid.face, current.face, state.zhai\n"
            "        ):\n"
            '            return LegalityVerdict.reject("V-6：同数量点数须更大")\n'
            "        return LegalityVerdict.ok()  # 转斋：点数任意，"
            '不受"同数量点数须更大"约束（R-20）'
        ),
    ),
    Mutation(
        mid="V-7",
        desc="过 1 后允许飞回（ones_called 失效，R-22/R-23 状态不变式）",
        file="src/perudo/core/legality.py",
        find="        if state.ones_called:",
        replace="        if False:",
    ),
    Mutation(
        mid="V-8",
        desc="起叫下限 ⌈1.5N⌉ 被改为 floor（R-14 / 起叫下限表）",
        file="src/perudo/core/legality.py",
        find="    return -(-3 * player_count // 2)  # ⌈1.5N⌉ 的整数实现（N=5 时取 8，R-14）",
        replace="    return 3 * player_count // 2  # ⌈1.5N⌉ 的整数实现（N=5 时取 8，R-14）",
    ),
)


def run_pytest() -> bool:
    """跑全量测试；返回是否全绿。"""
    result = subprocess.run(
        ["uv", "run", "pytest", "-q", "--no-header"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0


def apply_mutation(path: Path, find: str, replace: str) -> None:
    """把 ``find`` 首次出现替换为 ``replace`` 并写回。

    写回必须带 ``newline=""``：Windows 上默认的行尾翻译会把 LF 改写成 CRLF，
    污染工作区行尾（ruff 的 I001 在 CRLF 文件上不触发，会静默漏检）。
    """
    source = path.read_text(encoding="utf-8")
    mutated = source.replace(find, replace, 1)
    path.write_text(mutated, encoding="utf-8", newline="")


def main(argv: list[str] | None = None) -> int:
    """命令行入口。返回进程退出码（0 通过 / 1 有存活变异 / 2 环境错误）。"""
    del argv  # 预留 CLI 参数位；当前无需参数

    print("基线预检：全量测试须先全绿，变异杀灭判定才有意义……")
    if not run_pytest():
        print("错误：基线测试未全绿，请先修复再跑变异检查。", file=sys.stderr)
        return 2

    survivors: list[str] = []
    for mutation in MUTATIONS:
        path = REPO_ROOT / mutation.file
        source = path.read_text(encoding="utf-8")
        if mutation.find not in source:
            print(f"错误：{mutation.mid} 锚点未命中（实现漂移，须更新变异定义）：", file=sys.stderr)
            print(f"  文件：{mutation.file}", file=sys.stderr)
            print(f"  锚点：{mutation.find!r}", file=sys.stderr)
            return 2
        backup = path.with_suffix(path.suffix + MUTATED_SUFFIX)
        backup.write_bytes(path.read_bytes())  # 逐字节备份，恢复时不经行尾翻译
        killed = False
        try:
            apply_mutation(path, mutation.find, mutation.replace)
            killed = not run_pytest()
        finally:
            path.write_bytes(backup.read_bytes())  # 逐字节恢复
            backup.unlink()
        mark = "已杀灭" if killed else "存活 ✗"
        print(f"  {mutation.mid} {mutation.desc} —— {mark}")
        if not killed:
            survivors.append(mutation.mid)

    if survivors:
        print(
            f"\nG-mut 不通过：{len(survivors)} 条变异存活：{'、'.join(survivors)}", file=sys.stderr
        )
        return 1
    print(f"\n通过：变异清单 v1 全部 {len(MUTATIONS)} 条被测试杀灭（G-mut 全红）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
