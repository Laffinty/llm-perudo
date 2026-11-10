"""P1 单元测试：判定（域 judging，矩阵 §0.3）。

覆盖规则：R-45、R-63。穷举恒等式见 tests/properties/test_settlement_properties.py。
"""

from __future__ import annotations

from dataclasses import replace

from perudo.core.settlement import decide_bid_stood, is_total_darkness, judge
from perudo.core.types import Bid, Face, Hand, RuleConfig


def H(*faces: int) -> Hand:
    return Hand(tuple(Face(f) for f in faces))


def test_r45_judge_direction_with_examples() -> None:
    """R-45：count ≥ X → 成立（开杀方输）；< X → 不成立（被杀方输）。§13 三例对账。"""
    assert judge(7, Bid(7, Face.FIVE)) is True  # 临界
    assert judge(6, Bid(7, Face.FIVE)) is False
    assert judge(12, Bid(7, Face.FIVE)) is True  # §13.1
    assert judge(4, Bid(19, Face.ONE)) is False  # §13.2
    assert judge(11, Bid(7, Face.THREE)) is True  # §13.3


def test_r63_darkness_predicate_and_precheck() -> None:
    """R-63：无任何真 Y 骰 → 开骰者输（判定前置覆盖 R-45）；1 不计入本判断。"""
    hands_no_y = {0: H(1, 1, 2, 3, 5), 1: H(1, 2, 2, 6, 6)}
    hands_with_y = {0: H(4, 4, 1, 1, 6)}
    bid = Bid(6, Face.FOUR)
    assert is_total_darkness(hands_no_y, Face.FOUR) is True
    assert is_total_darkness(hands_with_y, Face.FOUR) is False
    # 默认关闭：一切按 R-45
    cfg_off = RuleConfig()
    assert decide_bid_stood(bid, 3, hands_no_y, cfg_off) is False
    assert decide_bid_stood(bid, 7, hands_no_y, cfg_off) is True
    # 开启：无真 Y → 钉在成立方向（开骰者输），即使 count < X
    cfg_on = replace(cfg_off, darkness=True)
    assert decide_bid_stood(bid, 3, hands_no_y, cfg_on) is True
    assert decide_bid_stood(bid, 3, hands_with_y, cfg_on) is False  # 有真 Y 回归 R-45
    assert decide_bid_stood(bid, 7, hands_with_y, cfg_on) is True
