"""P2 测试共享设施：脚本化玩家与受控随机（决策序列与骰面全部可预言）。"""

from __future__ import annotations

from collections.abc import Iterable

from perudo.core.types import Face
from perudo.engine.rng import Rng
from perudo.players.base import Decision, PlayerView
from perudo.players.bot import ConservativeBot


class ScriptedPlayer:
    """按**阶段分队**的脚本玩家：``bids`` 供叫骰轮次、``responds`` 供应牌轮次。

    队列耗尽时回退到保守机器人行为（最小加叫 / 投降）——同一座位在叫骰轮转中
    会被多次询问，分队设计避免"叫骰轮弹出应牌动作"的错位。
    """

    def __init__(
        self,
        name: str,
        bids: Iterable[Decision] = (),
        responds: Iterable[Decision] = (),
    ) -> None:
        self._name = name
        self._bids: list[Decision] = list(bids)
        self._responds: list[Decision] = list(responds)
        self._bot = ConservativeBot(f"{name}(fallback)")

    @property
    def name(self) -> str:
        return self._name

    def decide(self, view: PlayerView) -> Decision:
        from perudo.players.base import Phase

        queue = self._bids if view.phase is Phase.BIDDING else self._responds
        if queue:
            return queue.pop(0)
        return self._bot.decide(view)


class ExceptionPlayer:
    """decide 恒抛异常的玩家（A-15 故障政策测试用）。"""

    def __init__(self, name: str = "故障玩家") -> None:
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    def decide(self, view: PlayerView) -> Decision:
        raise RuntimeError(f"{self._name} 调用故障")


class IllegalPlayer:
    """恒返回非法动作的玩家（纠错预算测试用）：永远叫 99 个 6（超上限）。"""

    def __init__(self, name: str = "违规玩家") -> None:
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    def decide(self, view: PlayerView) -> Decision:
        from perudo.core.types import Bid, BidAction, BidKind

        return Decision(action=BidAction(BidKind.NORMAL, Bid(99, Face.SIX)))


class ScriptedRng(Rng):
    """受控随机：``roll`` 依序弹出 rolls（耗尽后重复最后一个）；``below`` 弹出 belows（耗尽 0）。"""

    def __init__(
        self,
        rolls: Iterable[tuple[Face, ...]] | None = None,
        belows: Iterable[int] | None = None,
    ) -> None:
        self._rolls: list[tuple[Face, ...]] = list(rolls or [])
        self._belows: list[int] = list(belows or [])
        self._last: tuple[Face, ...] = tuple(Face.ONE for _ in range(5))

    def roll(self, count: int) -> tuple[Face, ...]:
        if self._rolls:
            dice = self._rolls.pop(0)
            if len(dice) != count:
                raise AssertionError(f"脚本骰面数 {len(dice)} ≠ 请求 {count}")
            self._last = dice
            return dice
        if len(self._last) != count:
            raise AssertionError(f"骰面脚本耗尽且长度不符：请求 {count}")
        return self._last

    def below(self, n: int) -> int:
        if self._belows:
            return self._belows.pop(0) % n
        return 0
