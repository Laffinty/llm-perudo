"""随机源注入与确定性派生（02 A-10 / 05 G-06）。

引擎**不导入** ``random``（依赖边界门禁，scripts/check_imports.py）：
随机只经注入的 ``Rng`` 协议进入引擎。本模块提供协议定义与一个纯算术的
确定性实现 ``SplitMix64``——同一种子在任意平台产生同一序列，重放（A-10）
因此只依赖"种子 + 决策序列"。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from perudo.core.types import ALL_FACES, Face

__all__ = ["Rng", "SplitMix64", "derive_seed"]

_U64_MASK = (1 << 64) - 1
_GOLDEN = 0x9E3779B97F4A7C15


@runtime_checkable
class Rng(Protocol):
    """引擎可用的最小随机接口（随机只经此注入，02 A-10）。"""

    def below(self, n: int) -> int:
        """均匀返回 [0, n) 中的一个整数。"""
        ...

    def roll(self, count: int) -> tuple[Face, ...]:
        """掷 ``count`` 颗六面骰（R-01/R-07：各玩家手牌来源）。"""
        ...


class SplitMix64:
    """纯算术确定性 PRNG（splitmix64）：同种子 ⇒ 同序列，跨平台一致。"""

    __slots__ = ("_state",)

    def __init__(self, seed: int) -> None:
        self._state = seed & _U64_MASK

    def next_u64(self) -> int:
        self._state = (self._state + _GOLDEN) & _U64_MASK
        z = self._state
        z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & _U64_MASK
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & _U64_MASK
        return z ^ (z >> 31)

    def below(self, n: int) -> int:
        """均匀返回 [0, n)；n 必须 ≥ 1。取高 32 位避免低位相关性。"""
        if n < 1:
            raise ValueError("below(n) 要求 n ≥ 1")
        return (self.next_u64() >> 32) % n

    def roll(self, count: int) -> tuple[Face, ...]:
        """掷 ``count`` 颗六面骰（面值 1–6）。"""
        if count < 1:
            raise ValueError("掷骰数必须 ≥ 1（R-01）")
        return tuple(ALL_FACES[self.below(6)] for _ in range(count))


def derive_seed(master_seed: int, table_index: int) -> int:
    """主种子 → 第 ``table_index`` 桌的确定性派生种子（05 G-06）。

    同主种子整批可复现；派生只用纯算术，与引擎其余部分零耦合。
    """
    mixer = SplitMix64(master_seed)
    for _ in range(table_index + 1):
        derived = mixer.next_u64()
    return derived & _U64_MASK
