"""LOG Writer（04 §5 / F-04）：事件流 → 追加写文本文件，实时导出的唯一实现。

视角纪律（F-06/F-02）：EVE 桌 = 全量观战视角（含实时手牌行与 THOUGHT 行）；
PVE 桌 = 玩家视角（公开层 + 本人手牌，不含内心戏）。行尾强制 LF（R-03.6）。
"""

from __future__ import annotations

import datetime
from pathlib import Path

from perudo.engine.events import Event

__all__ = ["MatchLogWriter", "render_event_line"]

_TIME_FMT = "%Y-%m-%d %H:%M:%S"


def render_event_line(event: Event, now: datetime.datetime) -> str:
    """单事件 → 行式文本（时间戳 + 类型标签 + 摘要；宿主仅做界面文案级渲染）。"""
    ts = now.strftime(_TIME_FMT)
    tag = f"[{event.type}]"
    summary = _summary(event)
    return f"{ts} {tag} {summary}"


def _summary(event: Event) -> str:
    p = event.payload
    kind = event.type
    if kind == "MatchStarted":
        return f"match={p.get('match_id')} roster={','.join(map(str, p.get('roster', [])))}"
    if kind == "MatchStateChanged":
        return f"status={p.get('status')} reason={p.get('reason')}"
    if kind == "SeedRecorded":
        return "seed=***（私密层，不展开）"
    if kind == "RoundStarted":
        return f"第 {p.get('round_no')} 局开始，{p.get('caller')} 号起叫"
    if kind == "HandShaken":
        dice = ",".join(str(d) for d in p.get("dice", []))
        return f"{p.get('seat')} 号手牌（私密）：[{dice}]"
    if kind == "HandObserved":
        flag = p.get("leopard_flag")
        flag_text = f"（{flag}）" if flag else ""
        dice = ",".join(str(d) for d in p.get("dice", []))
        return f"{p.get('seat')} 号骰盅：[{dice}]{flag_text}"
    if kind == "Rerolled":
        return f"{p.get('seat')} 号重摇（{p.get('reason')}，第 {p.get('times')} 次）"
    if kind == "ThinkingObserved":
        text = str(p.get("thinking_text", "")).replace("\n", " ")
        return f"THOUGHT {p.get('seat')} 号：{text}"
    if kind == "BidMade":
        quote = f"「{p.get('quote')}」" if p.get("quote") else ""
        return f"{p.get('seat')} 号叫 {p.get('count')} 个 {p.get('face')}（{p.get('kind')}）{quote}"
    if kind == "ChallengeMade":
        targets = ",".join(str(t) for t in p.get("targets", []))
        return f"{p.get('seat')} 号发起 {p.get('kind')} → 目标 {targets}（×{p.get('base_multiplier')}）"
    if kind == "Responded":
        declared = p.get("declared_target")
        extra = f" 声明目标={declared}" if declared is not None else ""
        quote = f"「{p.get('quote')}」" if p.get("quote") else ""
        return f"{p.get('seat')} 号应牌：{p.get('choice')}{extra}{quote}"
    if kind == "Revealed":
        hands = "；".join(
            f"{seat}=[{','.join(str(d) for d in dice)}]" for seat, dice in p.get("hands", {}).items()
        )
        judgments = "；".join(
            f"{j.get('seat')}号 {j.get('count')}≥{j.get('bid', [0, 0])[0] if isinstance(j.get('bid'), list) else '?'}"
            + ("成立" if j.get("stood") else "不成立")
            for j in p.get("judgments", [])
        )
        darkness = "（天黑黑）" if p.get("darkness") else ""
        return f"开盅：{hands} 判定：{judgments or '（无开盅 stake）'}{darkness}"
    if kind == "RoundSettled":
        entries = "；".join(
            f"{e.get('seat')}号 付 {e.get('codes')} 码（×{e.get('multiplier')}）"
            for e in p.get("entries", [])
        )
        return f"第 {p.get('round_no')} 局结算：{entries or '（无输家）'}"
    if kind == "TurnDegraded":
        return f"{p.get('seat')} 号决策失败，引擎代打（{p.get('reason')}）"
    if kind == "DecisionFacts":
        return (
            f"turn={p.get('turn_seq')} seat={p.get('seat')} phase={p.get('phase')} "
            f"self_support={p.get('self_support')} degraded={p.get('degraded')}（评测层）"
        )
    if kind == "MatchEnded":
        winners = ",".join(str(w) for w in p.get("winners", []))
        return f"终局（{p.get('reason')}）积分={p.get('scores')} 胜者={winners} 号"
    return str(p)[:200]


class MatchLogWriter:
    """追加写 LOG 文件（F-04：随事件到达逐行写，宿主流式导出唯一实现）。"""

    def __init__(self, path: Path) -> None:
        self._path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = path.open("a", encoding="utf-8", newline="\n")
        self.lines = 0

    @property
    def path(self) -> Path:
        return self._path

    def append(self, event: Event) -> None:
        now = datetime.datetime.now()
        self._handle.write(render_event_line(event, now) + "\n")
        self.lines += 1

    def close(self) -> None:
        if not self._handle.closed:
            self._handle.close()
