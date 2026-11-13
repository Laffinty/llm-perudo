"""内置确定性保守脚本机器人（02 §7 / A-18）。

三用途：① EVE/内核冒烟与回归测试的自对弈基线；② 故障代打（A-15 落地者）；
③ 批量模拟中的基线对照组。行为纪律：

- 叫骰：永远选合法动作集中**代价最小**的加叫（最小数量，同数量取最小面值）；
  从不主动杀——除非叫骰已到上限、合法动作集中只剩杀类（被迫应杀时取
  代价最小的开杀/跳杀，登记于计划 R-04）；
- 应牌：被杀选择**投降**（固定减半代价，确定性最强）；被反杀后摊牌
  （REVEAL），不升级再反杀。
"""

from __future__ import annotations

from perudo.core.types import BidAction, ChallengeAction, ResponseKind
from perudo.players.base import Decision, Phase, PlayerView

__all__ = ["ConservativeBot"]


def _no_growth_space(bid_actions: list[BidAction], view: PlayerView) -> bool:
    """合法叫骰是否全部挤在数量上限上（同数量点数交替，无实质加叫）。"""
    total = view.player_count * 5  # R-03：在场骰子总数 5N
    return all(a.bid.count >= total for a in bid_actions)


class ConservativeBot:
    """确定性保守机器人（A-18）。无内部状态，同视图必同决策。"""

    def __init__(self, name: str = "保守机器人") -> None:
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    def decide(self, view: PlayerView) -> Decision:
        """按 02 §7 纪律从合法动作集中确定性选取。"""
        bid_actions = [a for a in view.legal_actions if isinstance(a, BidAction)]
        if bid_actions and not _no_growth_space(bid_actions, view):
            cheapest = min(bid_actions, key=lambda a: (a.bid.count, a.bid.face))
            return Decision(action=cheapest)
        # 无数量增长空间（全部为数量 == 上限的同数量点数交替，R-04.4⑤ 推广口径）：
        # 视为无实质加叫 → 被迫杀（代价最小的杀类）——否则"永不主动杀"纪律
        # 会让 FLY 态 (5N, 1)↔(5N, 6) 互刷永循环。规则层口径待 D-07 业主裁决。
        challenge_actions = [a for a in view.legal_actions if isinstance(a, ChallengeAction)]
        if challenge_actions:
            order = {
                "open": 0,
                "jump": 1,
                "multi": 2,
                "sweep": 3,
            }
            forced = min(
                challenge_actions,
                key=lambda a: (order[a.kind.value], a.targets),
            )
            return Decision(action=forced)  # 被迫应杀（登记 R-04）：取代价最小的杀类
        if view.phase is Phase.RESPOND:
            if ResponseKind.SURRENDER in view.legal_actions:
                return Decision(action=ResponseKind.SURRENDER)
            if ResponseKind.REVEAL in view.legal_actions:
                return Decision(action=ResponseKind.REVEAL)
        if view.legal_actions:
            return Decision(action=view.legal_actions[0])
        raise ValueError(f"{self._name}：合法动作集为空，无法决策（座位 {view.my_seat}）")
