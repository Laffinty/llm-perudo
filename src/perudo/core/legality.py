"""叫骰合法性判定（L0，02 §3.1 三件套之一）。

覆盖规则：R-04、R-08 ~ R-10、R-11 ~ R-36、R-60、R-61、R-64、R-65。
本模块是合法动作的唯一权威（02 §3.1）：一切非法动作在此被驳回并给出
人类可读原因（原因同时是玩家纠错的依据，02 §4.3）。

硬约束：纯函数、零 IO、零随机、零第三方依赖（02 A-19 / A-10 / A-14）。
"""

from __future__ import annotations

from perudo.core.types import (
    ALL_FACES,
    Bid,
    BidAction,
    BidKind,
    CallState,
    ChallengeAction,
    ChallengeKind,
    Direction,
    Face,
    Hand,
    LegalityVerdict,
    RerollReason,
    ResponseKind,
    RuleConfig,
    ScatteredPolicy,
    StraightPolicy,
    ZhaiState,
    bid_count_cap,
    total_dice,
)

__all__ = [
    "apply_bid",
    "bid_legal",
    "challenge_legal",
    "counter_battle_options",
    "enumerate_bid_actions",
    "enumerate_challenge_actions",
    "face_beats",
    "min_opening_bid",
    "needs_reshake",
    "next_seat",
    "opening_legal",
    "previous_seat",
    "recounter_target",
    "reroll_verdict_failed",
    "response_options",
]

# 飞状态点数序（R-15）：1 > 6 > 5 > 4 > 3 > 2；数值越大越强
_FLY_RANK: dict[Face, int] = {
    Face.ONE: 6,
    Face.SIX: 5,
    Face.FIVE: 4,
    Face.FOUR: 3,
    Face.THREE: 2,
    Face.TWO: 1,
}


# ---------------------------------------------------------------------------
# 座位几何（R-04：行动方向）
# ---------------------------------------------------------------------------


def previous_seat(seat: int, player_count: int, cfg: RuleConfig) -> int:
    """上一位玩家（沿行动方向的上游，R-04）。"""
    if cfg.direction is Direction.CLOCKWISE:
        return (seat - 1) % player_count
    return (seat + 1) % player_count


def next_seat(seat: int, player_count: int, cfg: RuleConfig) -> int:
    """下一位玩家（沿行动方向的下游，R-04）。"""
    if cfg.direction is Direction.CLOCKWISE:
        return (seat + 1) % player_count
    return (seat - 1) % player_count


# ---------------------------------------------------------------------------
# 摇骰合规与重摇（R-08 / R-09 / R-10 / R-60 / R-61 / R-65）
# ---------------------------------------------------------------------------


def _is_straight(dice: tuple[Face, ...]) -> bool:
    """顺色：5 颗点数互不相同且连续，仅 12345 / 23456（R-60）。"""
    values = {int(f) for f in dice}
    return values == {1, 2, 3, 4, 5} or values == {2, 3, 4, 5, 6}


def needs_reshake(hand: Hand, cfg: RuleConfig) -> RerollReason | None:
    """摇骰合规检查：需要重摇时返回原因，合规返回 ``None``（R-08/R-09/R-60）。

    - 顺色优先于散骰报告（顺色是散骰的特例，R-60）。
    - R-08 叠骰：数字桌面不出现（Hand 保证 5 颗可辨骰面），规则位保留（02 §2.4.1），
      故永不返回 ``STACKED``。
    - 策略为 COUNT_ZERO / NORMAL 时对应项不触发重摇，计数口径由 counting 处理。
    - 验骰（R-10）即自动校验：本函数为公开幂等纯函数（02 §2.4.1）。
    """
    if cfg.straight is StraightPolicy.RESHAKE and _is_straight(hand.dice):
        return RerollReason.STRAIGHT
    if cfg.scattered is ScatteredPolicy.RESHAKE and len(set(hand.dice)) == 5:
        return RerollReason.SCATTERED
    return None


def reroll_verdict_failed(times: int, cfg: RuleConfig) -> bool:
    """重摇次数超限判定（R-65）：第 ``times`` 次重摇后仍不合规是否判负。

    同一局同一玩家因叠骰/散骰重摇最多 ``cfg.reroll_limit`` 次（基线 3）；
    ``None`` 表示不限。判负者按 1 码受罚（R-46），结算由 settlement 处理。
    """
    if cfg.reroll_limit is None:
        return False
    return times > cfg.reroll_limit


# ---------------------------------------------------------------------------
# 起叫（R-11 ~ R-14 + R-64）
# ---------------------------------------------------------------------------


def min_opening_bid(player_count: int, zhai: bool) -> int:
    """首叫数量下限（R-11/R-12/R-14）：非斋 ⌈1.5N⌉、斋 N（01 §5.1 起叫下限表）。"""
    if zhai:
        return player_count
    return -(-3 * player_count // 2)  # ⌈1.5N⌉ 的整数实现（N=5 时取 8，R-14）


def opening_legal(action: BidAction, player_count: int, cfg: RuleConfig) -> LegalityVerdict:
    """首叫合法性（R-11 ~ R-14 + R-64）。

    首叫只有非斋（NORMAL）与斋（ZHAI）两种叫法（01 §14.1 前两行）；
    点数任意（R-13，由 ``Face`` 类型保证）。
    """
    bid = action.bid
    if action.kind is BidKind.FEI:
        return LegalityVerdict.reject("首叫不存在可飞回的上家叫骰，不能飞斋（R-21 前提不成立）")
    limit = min_opening_bid(player_count, action.kind is BidKind.ZHAI)
    if bid.count < limit:
        label = "斋首叫" if action.kind is BidKind.ZHAI else "非斋首叫"
        return LegalityVerdict.reject(f"{label}数量 {bid.count} 低于下限 {limit}（R-11/R-12/R-14）")
    cap = bid_count_cap(player_count, cfg)
    if cap is not None and bid.count > cap:
        return LegalityVerdict.reject(f"叫骰数量 {bid.count} 超过在场骰子总数上限 {cap}（R-64）")
    return LegalityVerdict.ok()


# ---------------------------------------------------------------------------
# 点数序（R-15 / R-16）
# ---------------------------------------------------------------------------


def face_beats(a: Face, b: Face, zhai: ZhaiState) -> bool:
    """点数 a 是否强于 b（双轨点数序，R-15/R-16）。

    飞状态：``1 > 6 > 5 > 4 > 3 > 2``（1 为癞子，最强）；
    1 死状态：``1 < 2 < 3 < 4 < 5 < 6``。
    """
    if zhai is ZhaiState.FLY:
        return _FLY_RANK[a] > _FLY_RANK[b]
    return a > b  # IntEnum：DEAD 序即自然序


# ---------------------------------------------------------------------------
# 接叫合法性（R-17/R-18、R-20/R-21/R-23、R-24 ~ R-28 五步短路、R-64）
# ---------------------------------------------------------------------------


def bid_legal(
    action: BidAction,
    state: CallState,
    current: Bid,
    player_count: int,
    cfg: RuleConfig,
) -> LegalityVerdict:
    """接叫合法性：五步短路判定（01 §6.4，R-24 ~ R-28）+ 全局上限（R-64）。

    点数比较一律采用**动作生效前**的状态点数序（01 §6.1 实现约定 / 02 §3.2 红线二）。
    """
    kind = action.kind
    bid = action.bid
    # 第 1 步（R-24）：取当前状态；R-64 全局硬约束与一切叫法同时生效
    cap = bid_count_cap(player_count, cfg)
    if cap is not None and bid.count > cap:
        return LegalityVerdict.reject(f"叫骰数量 {bid.count} 超过在场骰子总数上限 {cap}（R-64）")
    # 第 2 步（R-25）：转斋（FLY → DEAD）
    if kind is BidKind.ZHAI:
        if state.zhai is not ZhaiState.FLY:
            return LegalityVerdict.reject("当前已是斋/过 1 状态，不能再转斋（R-19/R-20）")
        if bid.count < current.count:
            return LegalityVerdict.reject(
                f"转斋只需数量 ≥ {current.count}，{bid.count} 不足（R-20）"
            )
        return LegalityVerdict.ok()  # 转斋：点数任意，不受"同数量点数须更大"约束（R-20）
    # 第 3 步（R-26）：飞斋（DEAD → FLY）
    if kind is BidKind.FEI:
        if state.zhai is not ZhaiState.DEAD:
            return LegalityVerdict.reject("当前已是飞状态，无斋可飞（R-21 前提不成立）")
        if state.ones_called:
            return LegalityVerdict.reject("本局已过 1，1 点永久不作癞子，不可飞斋（R-22/R-23）")
        need = 2 * current.count
        if bid.count < need:
            return LegalityVerdict.reject(
                f"飞斋需数量 ≥ 2×{current.count}={need}，{bid.count} 不足（R-21）"
            )
        return LegalityVerdict.ok()  # 飞斋：点数任意（R-21）
    # 第 4 步（R-27）：其余按常规比较（数量优先，同数量比点数）
    if bid.count > current.count:
        return LegalityVerdict.ok()  # 数量更大，点数不受限（R-18）
    if bid.count == current.count:
        if face_beats(bid.face, current.face, state.zhai):
            return LegalityVerdict.ok()  # 同数量点数更大（R-17）
        return LegalityVerdict.reject(
            f"同数量时点数必须更大（R-17：{bid.face} 不强于 {current.face}）"
        )
    return LegalityVerdict.reject(f"数量 {bid.count} 低于上家叫骰 {current.count}（R-17）")


def apply_bid(action: BidAction, state: CallState) -> CallState:
    """合法叫骰后的状态转移（R-19/R-22/R-28；调用前必须先通过 ``bid_legal``）。

    - 转斋 → DEAD（1 只按面值计，R-19/R-20）；
    - 飞斋 → FLY（R-21）；
    - 常规叫骰点数为 1 → 触发过 1：DEAD 且 ``ones_called=True``（R-22/R-28，
      FLY 下叫 1 即 §14.1 第 5 行，DEAD 下叫 1 仅置标记）；
    - 其余：状态不变。
    """
    if action.kind is BidKind.ZHAI:
        return state.to_dead()
    if action.kind is BidKind.FEI:
        return state.to_fly()
    if action.bid.face == Face.ONE:
        return state.to_dead(ones_called=True)
    return state


# ---------------------------------------------------------------------------
# 杀类合法性（R-29 ~ R-32）与应牌（R-33 ~ R-36）
# ---------------------------------------------------------------------------


def challenge_legal(
    kind: ChallengeKind,
    initiator: int,
    targets: tuple[int, ...],
    last_callers: tuple[int, ...],
    player_count: int,
    cfg: RuleConfig,
) -> LegalityVerdict:
    """杀类动作合法性（R-29 ~ R-32）。

    ``last_callers`` 为本局叫骰流水（从起叫起按叫骰顺序的座位序列）。
    目标按集合语义比较，允许乱序传入。
    """
    target_set = frozenset(targets)
    if len(target_set) != len(targets):
        return LegalityVerdict.reject("杀目标重复（R-29~R-32）")
    predecessor = previous_seat(initiator, player_count, cfg)
    if kind is ChallengeKind.OPEN:
        if not last_callers:
            return LegalityVerdict.reject("本局尚无叫骰，无从开杀（R-29）")
        last = last_callers[-1]
        if target_set != {last}:
            return LegalityVerdict.reject("开杀只能针对最近一位叫骰者（R-29）")
        if last != predecessor:
            return LegalityVerdict.reject(
                f"开杀只能对相邻上家（座位 {predecessor}）发起，目标 {last} 非相邻（R-29）"
            )
        return LegalityVerdict.ok()
    if kind is ChallengeKind.JUMP:
        if len(target_set) != 1:
            return LegalityVerdict.reject("跳杀只针对单一目标（R-30）")
        (target,) = tuple(target_set)
        if target not in last_callers:
            return LegalityVerdict.reject(f"目标 {target} 本局未叫骰，无可判定的叫骰（R-30）")
        if target == predecessor:
            return LegalityVerdict.reject("目标为相邻上家时应用开杀而非跳杀（R-29/R-30）")
        return LegalityVerdict.ok()
    if kind is ChallengeKind.MULTI:
        if len(target_set) < 2:
            return LegalityVerdict.reject("连杀至少连开两位叫骰者（R-31）")
        if initiator in target_set:
            return LegalityVerdict.reject("不能把自己列为杀目标（R-31）")
        # 连杀目标 = 叫骰流水末尾连续 ≥2 位叫骰者（R-31；R-04 轮转保证座位连续）
        for k in range(2, len(last_callers) + 1):
            if target_set == frozenset(last_callers[-k:]):
                return LegalityVerdict.ok()
        return LegalityVerdict.reject("连杀目标必须是本局末尾连续的 ≥2 位叫骰者（R-31）")
    # 通杀（R-32）：点名除自己外的全部参加者；未叫骰者也被点名，
    # 其结算由编排层按"无叫骰不判定"处理（本局无任何叫骰则无判定对象）
    if not last_callers:
        return LegalityVerdict.reject("本局尚无叫骰，通杀无判定对象（R-32）")
    others = frozenset(range(player_count)) - {initiator}
    if target_set != others:
        return LegalityVerdict.reject("通杀必须点名除自己外的全部参加者（R-32）")
    return LegalityVerdict.ok()


def response_options(kind: ChallengeKind, cfg: RuleConfig) -> frozenset[ResponseKind]:
    """被杀者的应牌选项（R-33/R-34）。

    基线：反杀仅被跳杀者可用（R-34，§10 D-04）；``counter_on_open`` 开启时
    被开杀者也可反杀（§12 第 10 项变体）。连杀/通杀逐目标按开杀处理（R-51）。
    投降始终可选（R-35）。
    """
    if kind is ChallengeKind.JUMP:
        return frozenset({ResponseKind.REVEAL, ResponseKind.COUNTER, ResponseKind.SURRENDER})
    options = {ResponseKind.REVEAL, ResponseKind.SURRENDER}
    if cfg.counter_on_open:
        options.add(ResponseKind.COUNTER)
    return frozenset(options)


def recounter_target(
    initiator: int,
    last_callers: tuple[int, ...],
    player_count: int,
    cfg: RuleConfig,
) -> int | None:
    """再反杀目标（R-36）：原杀者被反杀后可再反杀"下一位叫骰者"。

    目标 = 沿行动方向从 ``initiator`` 下一位起环行，第一个叫过骰的玩家
    （01 §13.3 第 6 步：D 再反劈 A）。该次反杀不可再被反杀，倍数 ×8 由
    编排层乘入。无目标时返回 ``None``。
    """
    caller_set = set(last_callers)
    seat = next_seat(initiator, player_count, cfg)
    for _ in range(player_count - 1):
        if seat in caller_set:
            return seat
        seat = next_seat(seat, player_count, cfg)
    return None


def counter_battle_options(can_recounter: bool) -> frozenset[ResponseKind]:
    """被反杀后原杀者的选项（R-36）：开盅摊牌，或再反杀一次（不可再被反杀）。

    ``can_recounter`` = ``recounter_target(...) is not None``（存在下一位叫骰者）。
    投降不在此列：R-35 投降属于被杀者，原杀者被反杀后只能摊牌或加注。
    """
    if can_recounter:
        return frozenset({ResponseKind.REVEAL, ResponseKind.RECOUNTER})
    return frozenset({ResponseKind.REVEAL})


def enumerate_bid_actions(
    state: CallState | None,
    current: Bid | None,
    player_count: int,
    cfg: RuleConfig,
) -> tuple[BidAction, ...]:
    """枚举当前叫骰合法动作集（02 §3.1：合法动作集枚举是唯一权威）。

    ``current is None``（或 ``state`` 为 ``None``）→ 首叫口径（R-11~R-14）；
    否则接叫口径（五步短路，R-24~R-28）。结果按（叫法，数量，面值）升序排列，
    完全确定。叫量上界取 R-64 配置上限；``UNLIMITED`` 变体按 5N 枚举
    （叫超在场骰子总数无实际意义，登记于计划 R-04）。
    """
    cap = bid_count_cap(player_count, cfg)
    upper = cap if cap is not None else total_dice(player_count)
    out: list[BidAction] = []
    if current is None or state is None:
        for kind, floor in (
            (BidKind.NORMAL, min_opening_bid(player_count, False)),
            (BidKind.ZHAI, min_opening_bid(player_count, True)),
        ):
            for x in range(floor, upper + 1):
                for face in ALL_FACES:
                    out.append(BidAction(kind, Bid(x, face)))
        return tuple(out)
    # 常规接叫（R-17/R-18）：数量 ≥ 现叫；同数量时点数须更强
    for x in range(current.count, upper + 1):
        for face in ALL_FACES:
            if bid_legal(
                BidAction(BidKind.NORMAL, Bid(x, face)), state, current, player_count, cfg
            ).legal:
                out.append(BidAction(BidKind.NORMAL, Bid(x, face)))
    # 转斋（R-20）：仅 FLY 态，X' ≥ X0，点数任意
    if state.zhai is ZhaiState.FLY:
        for x in range(current.count, upper + 1):
            for face in ALL_FACES:
                out.append(BidAction(BidKind.ZHAI, Bid(x, face)))
    # 飞斋（R-21/R-23）：仅 DEAD 未过 1 态，X' ≥ 2×X0
    if state.zhai is ZhaiState.DEAD and not state.ones_called:
        for x in range(2 * current.count, upper + 1):
            for face in ALL_FACES:
                out.append(BidAction(BidKind.FEI, Bid(x, face)))
    return tuple(out)


def enumerate_challenge_actions(
    initiator: int,
    last_callers: tuple[int, ...],
    player_count: int,
    cfg: RuleConfig,
) -> tuple[ChallengeAction, ...]:
    """枚举当前杀类合法动作（R-29 ~ R-32），按（类型，目标）确定性排序。

    连杀目标按"末尾连续 K 个不同叫骰者"枚举（K ≥ 2；R-31 的"位"以人为单位）。
    """
    out: list[ChallengeAction] = []
    predecessor = previous_seat(initiator, player_count, cfg)
    caller_set = set(last_callers)
    if last_callers and last_callers[-1] == predecessor:
        out.append(ChallengeAction(ChallengeKind.OPEN, (predecessor,)))
    for target in sorted(caller_set):
        if target != predecessor:
            out.append(ChallengeAction(ChallengeKind.JUMP, (target,)))
    # 连杀：从最近叫骰者向前收集不同玩家（本局不可能同一位连续叫两次——轮转保证）
    distinct_tail: list[int] = []
    for caller in reversed(last_callers):
        if caller not in distinct_tail:
            distinct_tail.append(caller)
        else:
            break
    for k in range(2, len(distinct_tail) + 1):
        targets = tuple(reversed(distinct_tail[:k]))
        if challenge_legal(
            ChallengeKind.MULTI, initiator, targets, last_callers, player_count, cfg
        ).legal:
            out.append(ChallengeAction(ChallengeKind.MULTI, targets))
    if last_callers:
        sweep_targets = tuple(s for s in range(player_count) if s != initiator)
        if challenge_legal(
            ChallengeKind.SWEEP, initiator, sweep_targets, last_callers, player_count, cfg
        ).legal:
            out.append(ChallengeAction(ChallengeKind.SWEEP, sweep_targets))
    return tuple(out)
