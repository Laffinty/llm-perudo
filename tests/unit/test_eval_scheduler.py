"""P7 单元测试：批量调度器（05 §6.3）——主种子派生 / 座位轮换 / 整批复现。"""

from __future__ import annotations

from pathlib import Path

import pytest

from perudo.engine.rng import derive_seed
from perudo.eval.scheduler import BatchSpec, run_batch


@pytest.fixture()
def spec() -> BatchSpec:
    return BatchSpec(
        slots=tuple({"kind": "bot", "name": f"bot{i}"} for i in range(4)),
        config={"end_threshold": 6, "max_rounds": 20},
        seat_rotations=1,
    )


def test_batch_runs_all_tables_and_aggregates(tmp_path: Path, spec: BatchSpec) -> None:
    """整批跑通：桌数 = 槽位数 × 轮换；聚合表就绪（05 §6.3）。"""
    result = run_batch(spec, master_seed=42, data_root=tmp_path, max_parallel=1)
    assert len(result.tables) == 4
    assert result.aggregate["tables_eligible"] == 4
    for table in result.tables:
        assert table["match_ended"] is True
        assert table["seed"] == derive_seed(42, table["table_index"])


def test_same_master_seed_reproduces_whole_batch(tmp_path: Path, spec: BatchSpec) -> None:
    """G-06：同主种子 ⇒ 整批事件流逐字段一致（每桌指标一致）。"""
    run_a = run_batch(spec, master_seed=2026, data_root=tmp_path / "a")
    run_b = run_batch(spec, master_seed=2026, data_root=tmp_path / "b")
    assert run_a.tables == run_b.tables


def test_different_master_seed_diverges(tmp_path: Path, spec: BatchSpec) -> None:
    """不同主种子 ⇒ 结果分歧（A-10 可复现的另一面）。"""
    run_a = run_batch(spec, master_seed=1, data_root=tmp_path / "a")
    run_b = run_batch(spec, master_seed=2, data_root=tmp_path / "b")
    assert run_a.aggregate != run_b.aggregate


def test_reproducible_sampling(tmp_path: Path, spec: BatchSpec) -> None:
    """G-06 抽样复验：同种子重跑最后一桌，权威流逐字节一致。"""
    result = run_batch(spec, master_seed=77, data_root=tmp_path, verify_reproducible=True)
    assert result.reproducible is True


def test_seat_rotation_changes_table_composition() -> None:
    """座位轮换（05 §6.3）：第 N 桌名册整体轮转（位置偏差消除）。"""
    from perudo.eval.scheduler import _rotated_slots

    slots = (
        {"kind": "bot", "name": "A"},
        {"kind": "bot", "name": "B"},
        {"kind": "bot", "name": "C"},
    )
    rotated = _rotated_slots(slots, 1)
    assert [s["name"] for s in rotated] == ["B", "C", "A"]
    rotated2 = _rotated_slots(slots, 2)
    assert [s["name"] for s in rotated2] == ["C", "A", "B"]
