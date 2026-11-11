"""桌局配置（02 §6 三分类的引擎侧子集）。

规则开关 = ``core.RuleConfig``（§12 十八项）；桌局参数 = 终局阈值、保险丝、
台词限长、纠错预算、故障重试、首叫者、人数、观战投影。接口档位（台词开关、
档位声明）随 P3/P4 接入层展开。配置在桌局创建时冻结（A-12）。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import cast

from perudo.core.types import (
    BidCapPolicy,
    Direction,
    RuleConfig,
    ScatteredPolicy,
    StraightPolicy,
    validate_player_count,
)

__all__ = ["MatchConfig"]


@dataclass(frozen=True)
class MatchConfig:
    """桌局配置快照（创建时冻结，A-12/A-08；JSON 快照可整存整取）。"""

    rules: RuleConfig = RuleConfig()
    #: 参赛人数（R-02；roster 长度必须与此一致）
    player_count: int = 4
    #: 终局阈值（A-03：完整结算后首达即终局）
    end_threshold: int = 100
    #: 保险丝（02 §2.2：防批量模拟无限桌局）
    max_rounds: int = 1000
    #: 台词限长（A-07；公开事件截断存档，评测层存全量）
    quote_max_len: int = 200
    #: 纠错预算（A-15：非法动作重提交上限，超限进故障政策）
    correction_budget: int = 2
    #: 调用故障重试次数（A-15：重试后仍失败 → 引擎代打 + 降级标记）
    fault_retries: int = 3
    #: 首局起叫者（R-05：None = 随机，由种子驱动；否则为座位号）
    first_caller: int | None = None
    #: 纯 EVE 观战桌（05 G-01：发射 HandObserved / ThinkingObserved 投影事件）
    spectated: bool = False

    def __post_init__(self) -> None:
        validate_player_count(self.player_count, self.rules)
        if self.end_threshold < 1:
            raise ValueError("终局阈值必须为正（A-03）")
        if self.max_rounds < 1:
            raise ValueError("max_rounds 保险丝必须为正（02 §2.2）")
        if self.quote_max_len < 0:
            raise ValueError("台词限长不得为负（A-07）")
        if self.correction_budget < 0 or self.fault_retries < 0:
            raise ValueError("纠错预算与故障重试不得为负（A-15）")
        if self.first_caller is not None and not 0 <= self.first_caller < self.player_count:
            raise ValueError("首叫者座位越界（R-05）")

    def snapshot(self) -> dict[str, object]:
        """JSON 安全快照（MatchStarted 载荷与 meta.json 共用）。"""
        data = asdict(self)
        rules = asdict(self.rules)
        rules["straight"] = self.rules.straight.value
        rules["scattered"] = self.rules.scattered.value
        rules["bid_cap"] = self.rules.bid_cap.value
        rules["direction"] = self.rules.direction.value
        data["rules"] = rules
        return data

    @classmethod
    def from_snapshot(cls, data: dict[str, object]) -> MatchConfig:
        """从快照重建（重放恢复用；字段可增不可删——A-20）。"""
        rules_raw = cast(dict[str, object], data["rules"])
        rules = RuleConfig(
            stake_label=cast(str, rules_raw["stake_label"]),
            straight=StraightPolicy(cast(str, rules_raw["straight"])),
            scattered=ScatteredPolicy(cast(str, rules_raw["scattered"])),
            leopard_bonus=cast(bool, rules_raw["leopard_bonus"]),
            all_ones_eight=cast(bool, rules_raw["all_ones_eight"]),
            leopard_double=cast(bool, rules_raw["leopard_double"]),
            half_double=cast(bool, rules_raw["half_double"]),
            jump_fail_double=cast(bool, rules_raw["jump_fail_double"]),
            counter_on_open=cast(bool, rules_raw["counter_on_open"]),
            multi_win_double_threshold=_opt_int(rules_raw["multi_win_double_threshold"]),
            surrender_floor_one=cast(bool, rules_raw["surrender_floor_one"]),
            darkness=cast(bool, rules_raw["darkness"]),
            drink_along=cast(bool, rules_raw["drink_along"]),
            direction=Direction(cast(str, rules_raw["direction"])),
            player_cap=_int(rules_raw["player_cap"]),
            bid_cap=BidCapPolicy(cast(str, rules_raw["bid_cap"])),
            reroll_limit=_opt_int(rules_raw["reroll_limit"]),
        )
        return cls(
            rules=rules,
            player_count=_int(data["player_count"]),
            end_threshold=_int(data["end_threshold"]),
            max_rounds=_int(data["max_rounds"]),
            quote_max_len=_int(data["quote_max_len"]),
            correction_budget=_int(data["correction_budget"]),
            fault_retries=_int(data["fault_retries"]),
            first_caller=_opt_int(data["first_caller"]),
            spectated=cast(bool, data["spectated"]),
        )

    def with_rules(self, **changes: object) -> MatchConfig:
        """派生一份仅改规则开关的配置（测试与变体局构造用）。"""
        rules = replace(self.rules, **changes)  # type: ignore[arg-type]
        return replace(self, rules=rules)


def _int(value: object) -> int:
    return cast(int, value)


def _opt_int(value: object) -> int | None:
    return None if value is None else cast(int, value)
