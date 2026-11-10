"""P1 单元测试：码数 / 惩罚结算（域 settling，矩阵 §0.3）。

覆盖规则：R-46 ~ R-57 基础与进阶结算、R-58/R-59/R-67/R-68 变体守护（A 类，
矩阵 §0.8）。D-04 裁决口径端到端见 tests/unit/test_scenario.py 进阶变体断言。
"""

from __future__ import annotations

from dataclasses import fields, replace
from fractions import Fraction

import pytest

from perudo.core.settlement import drink_along_pick, multi_kill_double, settle_stake
from perudo.core.types import (
    Bid,
    BidKind,
    ChallengeKind,
    Face,
    LoserSide,
    RuleConfig,
    StakeContext,
    rule_config_field_names,
)

CFG = RuleConfig()
#: 进阶（§9.2）关闭的配置（01 §13 三例口径），用于基础层 R-46~R-52 的基线断言
OFF = replace(CFG, half_double=False, jump_fail_double=False, leopard_double=False)


def stake(
    side: LoserSide = LoserSide.CHALLENGER,
    chain: ChallengeKind = ChallengeKind.OPEN,
    bid_stood: bool | None = True,
    base: int = 1,
    bid_count: int = 6,
    count: int | None = 6,
    leopard: bool = False,
) -> StakeContext:
    return StakeContext(
        loser=0,
        side=side,
        chain=chain,
        base_multiplier=Fraction(base),
        bid=Bid(bid_count, Face.THREE),
        bid_stood=bid_stood,
        count=count,
        loser_holds_leopard=leopard,
    )


def test_r46_codes_are_integer_stakes() -> None:
    """R-46：1 码 = 局前约定的量，仅显示换算（A-04：1 码 = 1 分整数）。"""
    entry = settle_stake(stake(), replace(OFF, stake_label="半杯"))
    assert isinstance(entry.codes, int) and entry.codes == 1
    entry2 = settle_stake(stake(), replace(OFF, stake_label="一杯"))
    assert entry2.codes == entry.codes  # stake_label 不参与计算


def test_r47_no_stake_cap_special_case_n5_01() -> None:
    """R-47：数字结算只按 §14.2 倍数表，无"下注不超过 2 码"截断（05 §5 N5-01）。"""
    assert settle_stake(stake(base=1), OFF).codes == 1
    assert settle_stake(stake(chain=ChallengeKind.JUMP, base=8), OFF).codes == 8  # 再反杀不截断


def test_r48_jump_base_double() -> None:
    """R-48：跳杀惩罚翻倍，负方付 2 码。"""
    assert settle_stake(stake(chain=ChallengeKind.JUMP, base=2), OFF).codes == 2


def test_r49_counter_chain_quadruples() -> None:
    """R-49：反杀再翻倍，负方付 4 码。"""
    assert settle_stake(stake(chain=ChallengeKind.JUMP, base=4), OFF).codes == 4


def test_r50_multi_win_double_threshold() -> None:
    """R-50：连杀连赢 ≥ 3 家再翻倍；变体"不翻"（§12 第 11 项）。"""
    assert multi_kill_double(3, CFG) is True
    assert multi_kill_double(2, CFG) is False
    assert multi_kill_double(99, replace(CFG, multi_win_double_threshold=None)) is False
    assert multi_kill_double(2, replace(CFG, multi_win_double_threshold=2)) is True


def test_r51_settled_separately_no_cross_stacking() -> None:
    """R-51：通杀/连杀多目标分别结算——各 StakeContext 独立，倍数不跨目标叠加。"""
    first = settle_stake(stake(base=1, bid_stood=True, count=6), OFF)
    second = settle_stake(stake(base=1, bid_stood=False, count=2, side=LoserSide.CHALLENGED), OFF)
    assert first.codes == 1 and second.codes == 1  # 各自独立，不互相放大


def test_r52_surrender_half_with_floor_one() -> None:
    """R-52：投降减半且保底 1 码（§12 第 12 项；变异 V-5 守护面）；无保底变体可 0。"""
    assert (
        settle_stake(
            stake(side=LoserSide.CHALLENGED, bid_stood=None, base=1, count=None), CFG
        ).codes
        == 1
    )
    assert (
        settle_stake(
            stake(side=LoserSide.CHALLENGED, bid_stood=None, base=2, count=None), CFG
        ).codes
        == 1
    )
    assert (
        settle_stake(
            stake(side=LoserSide.CHALLENGED, bid_stood=None, base=4, count=None), CFG
        ).codes
        == 2
    )
    assert (
        settle_stake(
            stake(side=LoserSide.CHALLENGED, bid_stood=None, base=8, count=None), CFG
        ).codes
        == 4
    )
    no_floor = replace(CFG, surrender_floor_one=False)
    assert (
        settle_stake(
            stake(side=LoserSide.CHALLENGED, bid_stood=None, base=1, count=None), no_floor
        ).codes
        == 0
    )


def test_r53_leopard_double_both_chains() -> None:
    """R-53：豹子加倍两链通用（D-04）；投降不开盅不适用；开关可关。

    count=4 使 R-54 不触发（4×2 ≥ 6），隔离出豹子加倍的净效果。
    """
    leopard = stake(side=LoserSide.CHALLENGED, bid_stood=False, count=4, leopard=True)
    assert settle_stake(leopard, CFG).codes == 2  # 开杀链 ×1 ×豹子 ×2
    jump_leopard = stake(
        side=LoserSide.CHALLENGED,
        chain=ChallengeKind.JUMP,
        bid_stood=False,
        base=2,
        count=1,
        leopard=True,
    )
    assert settle_stake(jump_leopard, CFG).codes == 4  # 跳杀 ×2 ×豹子 ×2
    off = replace(CFG, leopard_double=False)
    assert settle_stake(leopard, off).codes == 1
    surrendered = stake(side=LoserSide.CHALLENGED, bid_stood=None, count=None, leopard=True)
    assert settle_stake(surrendered, CFG).codes == 1  # 投降不吃豹子加倍


def test_r54_under_half_doubles_open_chain_only() -> None:
    """R-54：不够一半（count < X/2 严格）加倍，严格限开杀链；恰为 X/2 不加倍（D-04）。"""
    assert (
        settle_stake(
            stake(side=LoserSide.CHALLENGED, bid_stood=False, bid_count=6, count=2), CFG
        ).codes
        == 2
    )
    assert (
        settle_stake(
            stake(side=LoserSide.CHALLENGED, bid_stood=False, bid_count=6, count=3), CFG
        ).codes
        == 1
    )  # == X/2
    assert (
        settle_stake(
            stake(side=LoserSide.CHALLENGED, bid_stood=False, bid_count=6, count=4), CFG
        ).codes
        == 1
    )
    off = replace(CFG, half_double=False)
    assert (
        settle_stake(
            stake(side=LoserSide.CHALLENGED, bid_stood=False, bid_count=6, count=2), off
        ).codes
        == 1
    )
    jump = stake(
        side=LoserSide.CHALLENGED,
        chain=ChallengeKind.JUMP,
        bid_stood=False,
        base=2,
        bid_count=6,
        count=1,
    )
    assert settle_stake(jump, CFG).codes == 2  # 跳杀链不吃 R-54（D-04 严格名词）


def test_r55_over_half_challenger_rhetorical_double() -> None:
    """R-55：超半 = 修辞性加倍，不翻转判定（D-04 第 1 条）——杀者输恒 ×2。"""
    assert settle_stake(stake(side=LoserSide.CHALLENGER, bid_stood=True, count=12), CFG).codes == 2
    off = replace(CFG, half_double=False)
    assert settle_stake(stake(side=LoserSide.CHALLENGER, bid_stood=True, count=12), off).codes == 1
    with pytest.raises(ValueError):  # 判定不翻转：杀者"输"必然成立
        settle_stake(stake(side=LoserSide.CHALLENGER, bid_stood=False, count=2), CFG)


def test_r56_jump_fail_double_jump_chain_only() -> None:
    """R-56：跳杀失败加倍严格限跳杀链（D-04 第 2 条，§12 第 9 项独立开关）。"""
    assert settle_stake(stake(chain=ChallengeKind.JUMP, base=2), CFG).codes == 4
    off = replace(CFG, jump_fail_double=False)
    assert settle_stake(stake(chain=ChallengeKind.JUMP, base=2), off).codes == 2
    assert settle_stake(stake(chain=ChallengeKind.OPEN, base=1), CFG).codes == 2  # 开杀链只吃 R-55


def test_r57_drink_along_registered_mapping() -> None:
    """R-57：陪饮选人按 D-05 登记约定；摇中自己 self_hit（改判只动 drink_along_pick）。"""
    self_hit = drink_along_pick(0, (Face.TWO, Face.THREE), 4, CFG)  # s=5 → 偏移 (5-1)%4=0 → 自己
    assert self_hit.buddy == 0 and self_hit.self_hit is True
    next_one = drink_along_pick(2, (Face.THREE, Face.THREE), 4, CFG)  # s=6 → 偏移 1 → 3
    assert next_one.buddy == 3 and next_one.self_hit is False
    direct = drink_along_pick(1, (Face.FOUR,), 4, CFG)  # s=4 → 偏移 3 → 0
    assert direct.buddy == 0
    with pytest.raises(ValueError):
        drink_along_pick(0, (), 4, CFG)
    with pytest.raises(ValueError):
        drink_along_pick(0, (Face.ONE, Face.TWO, Face.THREE), 4, CFG)


def test_r58_r59_r67_r68_variant_guards() -> None:
    """R-58/R-59/R-67/R-68：A 类守护（矩阵 §0.8）——基线契约不含变体玩法支撑面。"""
    # R-68 反弹：叫法动作面恰为 普通/转斋/飞斋，无反弹类动作
    assert set(BidKind) == {BidKind.NORMAL, BidKind.ZHAI, BidKind.FEI}
    # R-67 筹码：配置与结算上下文无筹码累积字段
    names = rule_config_field_names()
    assert not (names & {"chip", "chips", "pot", "ante", "rebound"})
    # R-58/R-59（P 版/T 版组队）：无组队字段，公开类型面无组队结构
    assert not (names & {"partner", "team", "teams", "partners"})
    from perudo.core import types as core_types

    assert not any("partner" in n or "team" in n for n in core_types.__all__)
    # 结算上下文字段面复核
    stake_fields = {f.name for f in fields(StakeContext)}
    assert not (stake_fields & {"chips", "pot", "partner", "team"})
