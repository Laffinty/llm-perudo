"""判定与结算（L0，02 §3.1 三件套之二/之三）。

覆盖规则：R-45 判定、R-46 ~ R-57 结算、R-63 天黑黑；R-58/R-59/R-67/R-68
为变体（基线不实现，矩阵 §0.8 A 类守护口径）。

进阶结算口径（01 §9.2 补注 / 计划 §8 D-04，2026-11-10 业主裁决）：
R-55「超半」为修辞性加倍、不翻转 R-45；R-54/R-55 严格限开杀链、R-56 专管
跳杀失败、R-53 两链通用；各加倍项与基础倍数乘法叠加；count 恰为 X/2 不加倍；
投降（R-52）减半且保底 1 码，不吃依赖开盅事实的加倍项。

硬约束：纯函数、零 IO、零随机、零第三方依赖（02 A-19 / A-10 / A-14）。
陪饮骰面由引擎种子驱动传入（05 §5），本模块保持零随机。
"""

from __future__ import annotations

from collections.abc import Mapping
from fractions import Fraction

from perudo.core.types import (
    Bid,
    ChallengeKind,
    Direction,
    DrinkAlongResult,
    Face,
    Hand,
    LoserEntry,
    LoserSide,
    RuleConfig,
    StakeContext,
)

__all__ = [
    "decide_bid_stood",
    "drink_along_pick",
    "is_total_darkness",
    "judge",
    "multi_kill_double",
    "settle_stake",
]


# ---------------------------------------------------------------------------
# 判定（R-45 + R-63）
# ---------------------------------------------------------------------------


def judge(count: int, bid: Bid) -> bool:
    """判定（R-45）：``count ≥ X`` → 叫骰成立（开杀方输）；否则被杀方输。"""
    return count >= bid.count


def is_total_darkness(hands: Mapping[int, Hand], called: Face) -> bool:
    """天黑黑前提（R-63）：全场没有任何一颗骰面 == called（1 作癞子**不**计入）。"""
    return not any(d == called for hand in hands.values() for d in hand.dice)


def decide_bid_stood(bid: Bid, count: int, hands: Mapping[int, Hand], cfg: RuleConfig) -> bool:
    """判定入口（R-45 + R-63）：返回"叫骰是否成立"。

    成立 → 开杀方输；不成立 → 被杀方输。天黑黑（R-63）在判定**前置**检查
    （05 §5）：开启且全场无真 Y 骰 → 开骰者输，即使常规判定本该不成立。
    """
    if cfg.darkness and is_total_darkness(hands, bid.face):
        return True
    return judge(count, bid)


# ---------------------------------------------------------------------------
# 结算（R-46 ~ R-56；多输家由编排层逐 StakeContext 调用，R-51）
# ---------------------------------------------------------------------------


def _validate_stake(stake: StakeContext) -> None:
    """结算上下文一致性校验（R-45 输赢方向 + D-04 名词分工）。"""
    if stake.chain not in (ChallengeKind.OPEN, ChallengeKind.JUMP):
        raise ValueError("chain 须为 OPEN/JUMP；连杀/通杀属开杀型，由编排层组装时归 OPEN（D-04）")
    if stake.side is LoserSide.CHALLENGER:
        if stake.bid_stood is not True:
            raise ValueError("杀者输 ⟺ 叫骰成立（R-45）")
    else:
        if stake.bid_stood is True:
            raise ValueError("被杀者输 ⟺ 叫骰不成立或投降（R-45/R-35）")
    if (stake.bid_stood is None) != (stake.count is None):
        raise ValueError("bid_stood 与 count 必须同为 None（投降）或同为非 None（开盅）")


def settle_stake(stake: StakeContext, cfg: RuleConfig) -> LoserEntry:
    """单输家结算（R-46 ~ R-56）：码数（=积分，A-04 整数）与倍数明细。

    ``base_multiplier`` 为链上升级后的基础倍数（开杀 ×1、跳杀 ×2、反杀 ×4、
    再反杀 ×8；连杀连赢达标的 ×2 由编排层按 ``multi_kill_double`` 乘入）。

    R-47 的"下注不得超过 2 码"不入引擎结算（05 §5 N5-01 裁决）——结算只按
    01 §14.2 倍数表，本函数不存在任何下注上限截断路径。
    """
    _validate_stake(stake)
    multiplier = stake.base_multiplier
    breakdown: list[tuple[str, Fraction]] = [("base", stake.base_multiplier)]

    if stake.bid_stood is None:
        # 投降（R-35/R-52）：不开盅，接受当前惩罚的一半；保底 1 码（§12 第 12 项）。
        # 不开盅 ⇒ R-53/R-54 等依赖开盅事实的加倍项不适用（D-04 裁决第 5 条）。
        multiplier = stake.base_multiplier / 2
        breakdown.append(("surrender:R-52", Fraction(1, 2)))
        codes = int(multiplier)
        if cfg.surrender_floor_one:
            codes = max(1, codes)
        return LoserEntry(stake.loser, codes, multiplier, tuple(breakdown))

    if stake.side is LoserSide.CHALLENGER:
        # 杀者输（叫骰成立）：
        # R-55「超半」（修辞性加倍，不翻转判定 —— D-04 第 1 条）
        if stake.chain is ChallengeKind.OPEN and cfg.half_double:
            multiplier *= 2
            breakdown.append(("advance:R-55 超半", Fraction(2)))
        # R-56「跳杀失败」：被跳杀者叫骰成立（D-04：严格限跳杀链）
        if stake.chain is ChallengeKind.JUMP and cfg.jump_fail_double:
            multiplier *= 2
            breakdown.append(("advance:R-56 跳杀失败", Fraction(2)))
    else:
        # 被杀者输（叫骰不成立，开盅）：
        # R-54「不够一半」：count 严格小于 X 的一半（D-04：严格限开杀链、恰为 X/2 不加倍）
        bid_count = stake.bid.count
        assert stake.count is not None  # 一致性已由 _validate_stake 保证
        if stake.chain is ChallengeKind.OPEN and cfg.half_double and stake.count * 2 < bid_count:
            multiplier *= 2
            breakdown.append(("advance:R-54 不够一半", Fraction(2)))
        # R-53「豹子加倍」：被开杀/被跳杀者输且持围骰/全骰（D-04：两链通用）
        if stake.loser_holds_leopard and cfg.leopard_double:
            multiplier *= 2
            breakdown.append(("advance:R-53 豹子加倍", Fraction(2)))

    return LoserEntry(stake.loser, int(multiplier), multiplier, tuple(breakdown))


def multi_kill_double(win_count: int, cfg: RuleConfig) -> bool:
    """连杀连赢翻倍判定（R-50）：连赢 ≥ 阈值（基线 3 家）时输家惩罚再翻倍。

    ``multi_win_double_threshold`` 为 ``None`` 表示"不翻"（§12 第 11 项变体）。
    编排层对达标的各输家把 base_multiplier ×2 后再调 ``settle_stake``（分别结算，R-51）。
    """
    threshold = cfg.multi_win_double_threshold
    return threshold is not None and win_count >= threshold


# ---------------------------------------------------------------------------
# 陪饮（R-57；映射细则 = 计划 §8 D-05 登记约定）
# ---------------------------------------------------------------------------


def drink_along_pick(
    loser: int, roll: tuple[Face, ...], player_count: int, cfg: RuleConfig
) -> DrinkAlongResult:
    """陪饮选人（R-57）：负方摇陪饮骰后按点数沿座位方向选一位同罚对象。

    映射细则为计划 §8 D-05 登记的临时约定：两骰点数之和 s（1 颗大骰即面值），
    从负方自己起沿行动方向数第 ``((s − 1) mod N) + 1`` 位为目标；
    摇中自己则再多喝一倍（R-57）。业主改判时只改本函数。
    码数记账由编排层处理；骰面由引擎种子驱动传入（05 §5），本模块零随机。
    """
    if len(roll) not in (1, 2):
        raise ValueError("陪饮骰为 1 颗大骰或 2 颗标准骰（R-57）")
    total = sum(int(f) for f in roll)
    offset = (total - 1) % player_count
    if cfg.direction is Direction.CLOCKWISE:
        buddy = (loser + offset) % player_count
    else:
        buddy = (loser - offset) % player_count
    return DrinkAlongResult(buddy=buddy, self_hit=buddy == loser)
