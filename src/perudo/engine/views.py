"""信息隔离唯一出口（02 §5：任意玩家视图不含他人手牌与种子）。

``build_view`` 是把引擎内部状态渲染为 ``PlayerView`` 的**唯一**函数；
视图字段定稿见 ``players.base.PlayerView``（05 §4.3）。
"""

from __future__ import annotations

from perudo.core.legality import (
    counter_battle_options,
    enumerate_bid_actions,
    enumerate_challenge_actions,
    recounter_target,
    response_options,
)
from perudo.core.types import BidAction, ChallengeAction, ResponseKind
from perudo.engine.state import ChainState, MatchState
from perudo.players.base import ChainPosition, Phase, PlayerView

__all__ = ["build_view"]


def _kind_key(kind: ResponseKind) -> str:
    """应牌选项的稳定排序键（按动作名字典序）。"""
    return kind.value


def _respond_options(chain: ChainState, seat: int, state: MatchState) -> frozenset[ResponseKind]:
    """当前座位在应牌链上的合法选择（R-33/R-34/R-36）。"""
    if chain.countered:
        if seat != chain.initiator:
            return frozenset()
        can = (
            recounter_target(
                chain.initiator,
                tuple(state.last_callers),
                state.config.player_count,
                state.config.rules,
            )
            is not None
        )
        return counter_battle_options(can)
    if seat != chain.awaiting:
        return frozenset()
    return response_options(chain.kind, state.config.rules)


def _chain_position(chain: ChainState, seat: int, state: MatchState) -> ChainPosition:
    """把链状态渲染为 ChainPosition（仅 RESPOND 阶段，面向待决策座位）。"""
    if chain.countered and chain.counter_focus is not None:
        # 原杀者被反杀：只能摊牌或再反杀（R-36），面对反杀战倍数
        can_recounter = (
            recounter_target(
                chain.initiator,
                tuple(state.last_callers),
                state.config.player_count,
                state.config.rules,
            )
            is not None
        )
        options = counter_battle_options(can_recounter)
        stake = chain.stakes[chain.counter_focus]
        return ChainPosition(
            initiator=chain.initiator,
            kind=chain.kind.value,
            stake_numerator=stake.numerator,
            stake_denominator=stake.denominator,
            contested_bid=chain.contested_bids[chain.counter_focus],
            can_reveal=ResponseKind.REVEAL in options,
            can_counter=False,
            can_recounter=ResponseKind.RECOUNTER in options,
            can_surrender=False,
        )
    # 被杀者应牌：按挑战类型给三选一（R-33/R-34）
    options = response_options(chain.kind, state.config.rules)
    stake = chain.stakes[seat]
    return ChainPosition(
        initiator=chain.initiator,
        kind=chain.kind.value,
        stake_numerator=stake.numerator,
        stake_denominator=stake.denominator,
        contested_bid=chain.contested_bids[seat],
        can_reveal=ResponseKind.REVEAL in options,
        can_counter=ResponseKind.COUNTER in options,
        can_recounter=False,
        can_surrender=ResponseKind.SURRENDER in options,
    )


def build_view(state: MatchState, seat: int) -> PlayerView:
    """为 ``seat`` 渲染当前私有视图（信息隔离唯一出口，02 §5）。

    只读 ``state``：不注入种子；``my_hand`` 只取本人手牌；
    ``legal_actions`` 为该座位在当前阶段的完整合法动作集（02 §3.1 唯一权威）。
    """
    if not 0 <= seat < state.config.player_count:
        raise ValueError(f"座位 {seat} 越界（0..{state.config.player_count - 1}）")
    rules = state.config.rules
    chain = state.chain
    chain_position: ChainPosition | None = None
    legal: tuple[BidAction | ChallengeAction | ResponseKind, ...]
    if state.phase is Phase.RESPOND and chain is not None:
        options = _respond_options(chain, seat, state)
        ordered: list[ResponseKind] = sorted(options, key=_kind_key)
        chain_position = _chain_position(chain, seat, state)
        legal = tuple(ordered)
    else:
        bids = enumerate_bid_actions(
            state.call_state if state.current_bid is not None else None,
            state.current_bid,
            state.config.player_count,
            rules,
        )
        challenges: tuple[ChallengeAction, ...] = ()
        if state.current_bid is not None and seat not in state.disqualified:
            challenges = enumerate_challenge_actions(
                seat, tuple(state.last_callers), state.config.player_count, rules
            )
        legal = tuple(bids) + challenges
    return PlayerView(
        match_id=state.match_id,
        round_no=state.round_no,
        phase=state.phase,
        my_seat=seat,
        player_count=state.config.player_count,
        my_hand=state.hands[seat].dice if seat in state.hands else (),
        bid_history=tuple(state.bid_history),
        wild_state=state.call_state.zhai,
        ones_called=state.call_state.ones_called,
        current_bid=state.current_bid,
        legal_actions=legal,
        scores=tuple(state.scores),
        chain_position=chain_position,
    )
