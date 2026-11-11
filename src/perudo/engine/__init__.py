"""对局编排与持久层（L1，02 §2/§5、05 §2/§3）。

模块划分（计划 §2.2）：

- ``config``：桌局配置快照（规则开关 + 桌局参数，创建时冻结 A-12）；
- ``rng``：随机源注入协议 + 确定性实现（A-10，引擎不导入 ``random``）；
- ``events``：事件流与三层记录（A-10b，02 §5.1 + 05 G-01 增补）；
- ``state``：桌局/局状态与生命周期状态机（05 G-03）；
- ``views``：信息隔离唯一出口（02 §5）；
- ``stream``：``stream.jsonl`` 权威持久层（05 G-07）；
- ``phases``：重摇子流程 + 应牌链子状态机（02 §2.4）；
- ``match``：编排门面（创建/驱动/挂起/恢复/弃局，A-03 终局判定）；
- ``replay``：从 ``stream.jsonl`` 重放重建与逐字段验证（05 §2.2，A-10）。

依赖纪律：零第三方依赖、禁 ``random``/时钟/网络直调（scripts/check_imports.py
覆盖本目录）；随机只经注入的 ``Rng`` 协议进入。

**Match 门面契约**（``match.py`` 实现此签名，重放/宿主按此对接）::

    class Match:
        @classmethod
        def create(cls, match_id: str, config: MatchConfig,
                   roster: Sequence[Player], *, seed: int,
                   stream_path: Path | None = None,
                   decision_log: Sequence[Decision] | None = None) -> Match
        @property def match_id / status / scores / round_no / config
        def event_log(self) -> tuple[Event, ...]     # 全量已发射事件（含 seq）
        def current_pending_seat(self) -> int | None  # 等待决策的座位；终态为 None
        def view_for(self, seat: int) -> PlayerView
        def run_to_end(self) -> None                  # 驱动至 ENDED/ABANDONED
        def suspend(self) -> None / resume(self) -> None / abandon(self) -> None

契约要点：``decision_log`` 提供时进入**重放模式**——所有决策点按日志回放、
不调用 roster（此时 roster 可为空元组、``stream_path`` 必须为 None）；
``roster`` 长度必须等于 ``config.player_count``；``stream_path`` 提供时逐事件
追加写 ``stream.jsonl`` 并落 ``meta.json`` 快照（05 §3 布局，宿主传入路径）。
"""
