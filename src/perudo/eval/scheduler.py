"""批量调度器（05 §6.3）：主种子派生 → 座位轮换 → 并行桌 → 整批复现。

可复现（G-06）：同主种子 ⇒ 每桌种子确定性派生 ⇒ 事件流逐字段一致
（A-10 的整批形态）。限流：LLM 适配器的网络层自带退避（03 §8），
调度器按 ``max_parallel`` 控制并行桌数（A-14：并发在引擎外）。
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from perudo.adapters.deepseek import make_player as make_deepseek
from perudo.adapters.doubao import make_player as make_doubao
from perudo.adapters.glm import make_player as make_glm
from perudo.adapters.mimo import make_player as make_mimo
from perudo.adapters.minimax import make_player as make_minimax
from perudo.adapters.qwen import make_player as make_qwen
from perudo.adapters.sdk.config import AdapterConfig, PersonaConfig, default_base_url
from perudo.engine.config import MatchConfig
from perudo.engine.match import Match
from perudo.engine.rng import derive_seed
from perudo.eval.metrics import aggregate_batch, compute_match_metrics
from perudo.players.base import Player
from perudo.players.bot import ConservativeBot

__all__ = ["BatchSpec", "BatchResult", "run_batch"]

_FACTORIES = {
    "deepseek": make_deepseek,
    "glm": make_glm,
    "mimo": make_mimo,
    "qwen": make_qwen,
    "doubao": make_doubao,
    "minimax": make_minimax,
}


@dataclass(frozen=True)
class BatchSpec:
    """批量开桌规格：名册模板 + 桌局参数（座位由轮换填充，03 §7 每桌可变）。"""

    slots: tuple[dict[str, Any], ...]  # 名册模板（seat 按轮换顺序填充）
    config: dict[str, Any] = field(default_factory=dict)
    #: 座位轮换轮数（05 §6.3：同一阵容各座位轮转，消除位置偏差）
    seat_rotations: int = 1


@dataclass
class BatchResult:
    """整批结果：每桌指标 + 聚合表 + 复现标记。"""

    tables: list[dict[str, Any]]
    aggregate: dict[str, Any]
    #: 同主种子重跑抽样比对（True=整批复现成立；False=抽样失败；None=未抽验）
    reproducible: bool | None


def run_batch(
    spec: BatchSpec,
    *,
    master_seed: int,
    data_root: Path,
    max_parallel: int = 1,
    verify_reproducible: bool = False,
) -> BatchResult:
    """跑整批桌局并返回聚合指标。

    并行桌 = ``max_parallel`` 线程（A-14：并发在引擎外）；每桌种子 =
    ``derive_seed(master_seed, table_index)``（G-06 确定性派生）。
    ``verify_reproducible=True`` 时重跑最后一桌并比对权威流
    （整批复现抽样验证，G-06/A-10）。
    """
    data_root.mkdir(parents=True, exist_ok=True)
    table_count = spec.seat_rotations * max(1, len(spec.slots))
    results: list[dict[str, Any] | None] = [None] * table_count

    def run_table(index: int) -> None:
        seed = derive_seed(master_seed, index)
        seats = _rotated_slots(spec.slots, index)
        stream = data_root / f"batch_table_{index:04d}" / "stream.jsonl"
        stream.parent.mkdir(parents=True, exist_ok=True)
        match = Match.create(
            f"batch_{master_seed}_{index:04d}",
            _match_config(spec.config, len(seats)),
            _build_roster(seats),
            seed=seed,
            stream_path=stream,
        )
        match.run_to_end()
        metrics = compute_match_metrics(match.event_log())
        metrics["table_index"] = index
        metrics["seed"] = seed
        results[index] = metrics

    parallel = max(1, min(max_parallel, table_count))
    if parallel == 1:
        for index in range(table_count):
            run_table(index)
    else:
        with ThreadPoolExecutor(max_workers=parallel) as pool:
            list(pool.map(run_table, range(table_count)))

    reproducible: bool | None = None
    if verify_reproducible and table_count > 0:
        reproducible = _verify_reproduction(spec, master_seed, data_root, table_count - 1)

    filled = [m for m in results if m is not None]
    aggregate = aggregate_batch(filled)
    return BatchResult(tables=filled, aggregate=aggregate, reproducible=reproducible)


def _verify_reproduction(spec: BatchSpec, master_seed: int, data_root: Path, index: int) -> bool:
    """抽样复验：同种子重跑该桌，权威流逐字节一致（A-10/G-06）。"""
    seed = derive_seed(master_seed, index)
    seats = _rotated_slots(spec.slots, index)
    original = data_root / f"batch_table_{index:04d}" / "stream.jsonl"
    repro_stream = data_root / f"batch_repro_{index:04d}" / "stream.jsonl"
    repro_stream.parent.mkdir(parents=True, exist_ok=True)
    match = Match.create(
        f"batch_{master_seed}_{index:04d}",  # 同 match_id：MatchStarted 载荷一致（A-10）
        _match_config(spec.config, len(seats)),
        _build_roster(seats),
        seed=seed,
        stream_path=repro_stream,
    )
    match.run_to_end()
    original_text = original.read_text(encoding="utf-8")
    repro_text = repro_stream.read_text(encoding="utf-8")
    return bool(original_text) and original_text == repro_text


def _rotated_slots(
    slots: tuple[dict[str, Any], ...], table_index: int
) -> tuple[dict[str, Any], ...]:
    """座位轮换（05 §6.3）：第 ``table_index`` 桌整体轮转 table_index 位。"""
    n = len(slots)
    rotation = table_index % n if n else 0
    return tuple(slots[(i + rotation) % n] for i in range(n))


def _match_config(config_overrides: dict[str, Any], player_count: int) -> MatchConfig:
    """spec.config → MatchConfig（人数以名册槽位数为准）。"""
    overrides = dict(config_overrides)
    overrides.pop("player_count", None)
    rules = dict(overrides.pop("rules", {}) or {})
    match_config = MatchConfig(player_count=player_count, **overrides)
    if rules:
        match_config = match_config.with_rules(**rules)
    return match_config


def _build_roster(seats: tuple[dict[str, Any], ...]) -> list[Player]:
    """名册构建：bot → ConservativeBot；llm → provider 工厂（03 §7）。"""
    roster: list[Player] = []
    for index, slot in enumerate(seats):
        kind = str(slot.get("kind", "bot"))
        if kind == "bot":
            roster.append(ConservativeBot(str(slot.get("name", f"bot{index}"))))
        elif kind == "llm":
            provider = str(slot.get("provider", ""))
            factory = _FACTORIES.get(provider)
            if factory is None:
                raise ValueError(f"未知 provider：{provider}（03 §3 六家）")
            roster.append(factory(_llm_config(dict(slot), index)))
        else:
            raise ValueError(f"批量名册不支持 {kind} 席（评测层人类席随 PVE 单桌流程）")
    return roster


def _llm_config(slot: dict[str, Any], index: int) -> AdapterConfig:
    provider = str(slot.get("provider", ""))
    return AdapterConfig(
        provider=provider,
        model=str(slot.get("model", "")),
        api_key_ref=str(slot.get("api_key_ref", f"env:{provider.upper()}_API_KEY")),
        base_url=str(slot.get("base_url") or "") or default_base_url(provider),
        persona=PersonaConfig(
            name=str(slot.get("persona_name", f"LLM{index}")),
            style=str(slot.get("persona_style", "")),
            trash_talk=int(slot.get("trash_talk", 1)),
        ),
        thinking=str(slot.get("thinking", "auto")),
        timeout_ms=int(slot.get("timeout_ms", 60_000)),
    )
