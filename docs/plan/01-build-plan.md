# 大话骰 工程构建计划（Build Plan）

| 项 | 值 |
| --- | --- |
| 文档类型 | 构建计划（Engineering Build Plan） |
| 依据 | [`../design/01-game-rules.md`](../design/01-game-rules.md)、[`../design/02-engine-design.md`](../design/02-engine-design.md)、[`../design/03-llm-adapter.md`](../design/03-llm-adapter.md)、[`../design/04-frontend.md`](../design/04-frontend.md)、[`../design/05-evaluation-completion.md`](../design/05-evaluation-completion.md) |
| 项目 | llm-perudo |
| 状态 | v1.0 初稿 —— 待业主评审 |
| 日期 | 2026-11-10 |
| 不含内容 | 任何设计变更（实现中发现设计疑义，一律回设计文档走裁决流程，见 §7） |

---

## 0. 计划定位与假设

本文把五份设计稿综合为**可执行施工序列**：阶段划分（P0–P8）、每阶段的任务清单与验收标准（逐条回指设计稿条款）、测试与质量门禁、风险与前置工序。

**工程假设**（如与预期不符，评审时指出即改）：

| 假设 | 内容 | 依据 |
| --- | --- | --- |
| H-01 | 单人开发主线；可并行的阶段已标注，但不承诺多人分工 | 仓库现状 |
| H-02 | Python 3.12+；工具链 uv + ruff + mypy + pytest | 仓库 `.gitignore` 线索 + 02 §1.3 |
| H-03 | 包名 `perudo`（`src/perudo` 布局）；前端独立目录 `frontend/` | 惯例 |
| H-04 | git main 直提（沿用现有惯例），里程碑打 tag | 提交历史 |
| H-05 | CI = GitHub Actions | 远端为 GitHub |
| H-06 | 适配器用同步 HTTP 客户端（httpx），批量并发交给调度器线程池——与引擎同步确定性（02 A-14）一致 | 02 A-14 |
| H-07 | 工作量标注用 S/M/L（相对），不排日历日期 | 未获时间约束 |

---

## 1. 交付总览（Definition of Done）

| 交付物 | 验收锚点 |
| --- | --- |
| 规则内核库（零三方依赖、零 IO、零随机） | 02 §3；01 §13 三例对账；R-xx 追溯无孤儿 |
| 对局编排 + 持久层（生命周期/事件流/`stream.jsonl`/回放） | 02 §2、§5；05 §2、§3 |
| EVE 全链路（六家适配器 + 观战界面 + 批量评测报告） | 03 全文；04 §3；05 §6 |
| PVE 单人全链路（动作面板/视图纪律/LOG 导出/断线恢复/退出弃局） | 04 全文；05 G-08 |
| 质量门禁（静态/测试矩阵/属性/变异/覆盖率） | 本文档 §4 |
| 文档收尾（README、核对清单回填、规则统计写回） | 02 N-01/N-02；03 N3-01 |

---

## 2. 工程基线

### 2.1 技术栈与工具链

| 层 | 选择 | 说明 |
| --- | --- | --- |
| 规则内核 / 编排 | Python 3.12+ 标准库，**零第三方依赖**（02 A-19） | dataclasses / enum / json / tomllib / hashlib（种子派生，05 G-06） |
| 适配器 | `httpx`（同步） | 统一走 OpenAI 兼容 HTTP（03 §1.2 B-08），**不引入各家 SDK**；MiMo Anthropic 协议为可选第二实现（N3-03 后置） |
| Web 宿主 | `fastapi` + `uvicorn`（含 WebSocket） | 04 F-05 |
| 前端 | Vue 3 + Vite + TypeScript（04 F-05） | 构建产物 `frontend/dist/` 由宿主托管 |
| 评测 | 标准库 + （可选）表格输出库 | 报告为 Markdown（05 §6.5） |
| 工具链 | `uv`（依赖与环境）、`ruff`（lint + format）、`mypy --strict`（core 必过，其余建议级）、`pytest` + coverage | H-02 |

### 2.2 仓库布局

```
llm-perudo/
├─ docs/                        # design/（五稿）+ plan/（本文）
├─ src/perudo/
│  ├─ core/                     # P1 规则内核：types / legality / counting / settlement / opening
│  ├─ engine/                   # P2 编排：state / phases(重摇、应牌链) / events / rng / replay /
│  │                            #        lifecycle / views(信息隔离) / stream(权威持久层)
│  ├─ players/                  # P2 玩家契约 + 保守脚本机器人
│  ├─ adapters/                 # P3/P6 适配器：sdk/ + deepseek/ glm/ mimo/ qwen/ doubao/ minimax/
│  ├─ host/                     # P4/P5 FastAPI 宿主：routes / ws(视图流网关) / logwriter / 静态托管
│  └─ eval/                     # P7 评测：metrics(E-xx) / scheduler / report / commentary(AI 评述)
├─ frontend/                    # P4 Vite + Vue3 SPA
├─ tests/
│  ├─ unit/                     # core / engine / adapters / host / eval
│  ├─ properties/               # 回放一致、隔离、合法性完备（§4.2）
│  ├─ traceability.md           # R-xx ↔ 测试 ID 矩阵（CI 查孤儿）
│  └─ e2e/                      # 脚本机器人全桌冒烟
├─ examples/players/*.toml      # 玩家配置示例（03 §7）
├─ scripts/                     # 开发辅助（批量跑、数据检查）
├─ data/                        # 运行时数据根目录（gitignore；布局见 05 §3）
└─ .github/workflows/ci.yml     # P0 建立
```

### 2.3 依赖边界（门禁化）

| 规则 | 检查 |
| --- | --- |
| `core/` 与 `engine/`：禁止 `httpx/fastapi` 及一切三方导入；禁止 `random`（随机只经注入的 RNG）、禁止网络/时钟直接调用 | CI import 白名单检查（02 G-约束） |
| `players/`、`adapters/`、`host/`、`eval/`：依赖向下不向上；适配器不得 import 引擎内部私有符号，只走契约 | ruff import 规则 + 评审 |
| 契约字段只增不删（02 A-20） | 评审纪律 |

---

## 3. 工作分解（P0–P8）

### P0 工程脚手架（S）

| 任务 | 产出 |
| --- | --- |
| uv 初始化 + `pyproject.toml`（ruff/mypy/pytest 配置） | 可 `uv run pytest` 的空骨架 |
| CI：lint + type + test + 覆盖率四门禁 | `.github/workflows/ci.yml` |
| `tests/traceability.md` 矩阵骨架（先建表，P1 填充） | 追溯机制就位 |
| `.gitignore` 增补 `data/`、`frontend/dist/` | — |

### P1 规则内核（M1）（M）

**任务**：`core/types.py`（2×2 状态、动作类型）；`core/legality.py`（R-11~R-14 起叫下限表、R-15~R-28 五步短路、R-64 上限）；`core/counting.py`（R-37~R-43、**D-02 字面计数**、围骰/全骰）；`core/settlement.py`（R-45 判定、§14.2 倍数叠加、投降减半保底、进阶开关；**R-47 歧义按 05 N5-01：不做下注上限特判**）。

| 验收标准 | 锚点 |
| --- | --- |
| 01 §13 三例完整对账逐项通过 | 01 §13 |
| R-xx 追溯矩阵无孤儿（含 R-60~R-68 边角） | 01 全文 |
| 属性测试：计数单调、合法性自洽、`ones_called ⇒ DEAD` 不变式 | §4.2 |
| 变异清单 v1 全红 | §4.1 |
| core 零三方依赖、零 IO、零随机 | §2.3 |

### P2 对局编排与持久层（M2）（L）

**任务**：`engine/state.py`（桌局/局/回合 + 生命周期状态机，05 G-03）；`engine/phases/`（重摇子流程 R-08/09/60/65；应牌链子状态机 R-29~R-36 含通杀多目标）；`engine/events.py`（02 §5.1 全表 + G-01 `HandObserved` + `ThinkingObserved` + `MatchStateChanged`）；`engine/rng.py`（种子注入 + 主种子派生 G-06）；`engine/replay.py`；`engine/stream.py`（`stream.jsonl` 权威持久层 G-07）；`engine/views.py`（信息隔离唯一出口）；`players/base.py`（02 §4 契约）+ `players/bot.py`（保守机器人 A-18）。

| 验收标准 | 锚点 |
| --- | --- |
| 脚本机器人自对弈完整桌局（开满重摇/应牌链/通杀/陪饮/天黑黑开关各局） | 02 M2 |
| 同种子重放逐字段一致（属性测试） | 02 A-10 |
| 宿主重启模拟：从 `stream.jsonl` 重放重建成功 | 05 G-02 |
| 信息隔离：任意玩家视图不含他人手牌与种子（属性测试） | 02 §5 |
| 生命周期全转移覆盖（含弃局不进统计） | 05 §2 |

### P3 适配器 SDK + 首批两家（03 M4a）（M）

**前置工序**：N3-01 DeepSeek / GLM 字段核对（03 §5.7）。

**任务**：`adapters/sdk/`（ContextBuilder / ResponseParser / SelfChecker / RetryController / CostLedger / Transport，03 §1.1）；`adapters/deepseek/`（温度矩阵、thinking 分级、退役名守门）；`adapters/glm/`（thinking_type、Flash/FlashX、全量呈现）；配置装载（tomllib，03 §7）；附件信封（03 §4）。

| 验收标准 | 锚点 |
| --- | --- |
| DeepSeek / GLM 真实 API vs 脚本机器人完整局跑通 | 03 M4a |
| 附件信封字段齐全；thinking 剥离正确（不混入台词/动作） | 03 §4 |
| 自检循环不消耗引擎纠错预算（单测证明） | 03 B-04 |
| 离线 mock 测试全绿（真实 API 冒烟独立标记，可跳过） | §4.4 |

### P4 Web 宿主 + EVE 观战（04 W1）（M）

**前置工序**：N4-03 极简视觉约定（不阻塞，先默认样式）。

**任务**：`host/`（REST 最小集 05 §4.2、WS 视图流网关 + seq 补发 G-02、LOG Writer、静态托管）；`frontend/`（Vite 骨架、开桌向导页、对局主界面、结束页骨架）；EVE 观战全链路（骰盅卡实时 + 围骰标注来自 `HandObserved`、内心戏气泡）。

| 验收标准 | 锚点 |
| --- | --- |
| 浏览器从向导到终局全程 EVE 观战无断点 | 04 W1 |
| 气泡三分纪律（台词/内心戏/系统播报视觉强制区分） | 04 §4 |
| 前端零规则逻辑（围骰标注等全部来自事件载荷） | 04 F-09 |

### P5 PVE 全量 + LOG 交付（04 W2/W3）（M）

**任务**：动作面板全动作（叫骰选择器/转斋/飞斋/开杀/跳杀选目标/应牌三选一）；PVE 视图纪律落地；桌局列表页（F-11）；LOG 抽屉 + 流式导出；断线/刷新恢复 UI；"退出并结束本桌"（G-08）。

| 验收标准 | 锚点 |
| --- | --- |
| PVE 全动作可玩（含应牌链反杀 ×4/×8） | 04 W2 |
| PVE 玩家流不含他人手牌与内心戏 | 04 F-02/F-06 |
| LOG 边打边写逐行完整；刷新后状态无缺口恢复 | 04 W3 |
| 退出即弃局且不进评测 | 05 G-08 |

### P6 其余四家适配器（03 M4b）（M）

**前置工序**：N3-01 MiMo / Qwen / 豆包 / MiniMax 字段核对。

**任务**：mimo（双协议占位 + Batch 预留 + 自托管位）、qwen（thinking_budget 阶段化）、doubao（接入点双支持）、minimax（交错思考剥离 + 稳定前缀强制）；台词人格包调校（粤语模板）；防注入红队测试。

| 验收标准 | 锚点 |
| --- | --- |
| 六家同桌 EVE 局跑通 | 03 M4b |
| 台词无注入逃逸（红队用例集） | 03 §3 / 04 §4 |
| MiniMax 稳定前缀装配被强制（开关测试） | 03 §5.6 |

### P7 批量评测（M3）（L）

**前置工序**：N5-04 挑衅词表初版。

**任务**：`eval/metrics.py`（E-01~E-15，含降级/弃局过滤）；`eval/scheduler.py`（主种子派生、座位轮换、并行桌 + 适配器限流尊重）；聚合数据集；`eval/report.py`（单桌 + 批量报告）；`eval/commentary.py`（AI 评述，`glm-5.3-flash`，三禁）。**同时产出 02 N-01/N-02 验证统计**（D-02 过 1 使用率、各人数起叫压力——机器人桌即可）。

| 验收标准 | 锚点 |
| --- | --- |
| 主种子批量 N 桌可整批复现 | 05 G-06 |
| E-01~E-15 全部产出且口径与 05 §6.2 一致 | 05 §6 |
| AI 评述产物标注"AI 评述"；不触碰判定与统计数字 | 05 §6.4 |
| N-01/N-02 统计结论写回 01 附录 | 02 §6.1 |

### P8 收尾（S）

README（安装/配置/跑一桌/跑批量）；N3-01 核对结果回填 03 §5.7；型号线复核；`v0.1` tag。

---

## 4. 测试与质量门禁

### 4.1 追溯矩阵与变异清单

`tests/traceability.md`：每条 R-xx ↔ 至少一个测试 ID，CI 检查孤儿（无测试的规则 = 红）。

**变异清单 v1**（每条 = 故意改坏内核一处，对应测试必须变红；放进 CI 的变异作业）：

| # | 变异 | 必须捕获的测试面 |
| --- | --- | --- |
| V-1 | 删飞斋数量翻倍门槛（`≥ 2X` → `≥ X`） | R-21 合法性 |
| V-2 | 围骰 +1 改 +2 | R-39 计数 |
| V-3 | D-02 改为"任意面值取最大"计数 | count(1) 字面口径 |
| V-4 | 判定方向反转（`≥` → `<`） | R-45 / 结算 |
| V-5 | 投降减半丢保底 1 码 | R-52 / §12 第 12 项 |
| V-6 | 转斋误加"点数须更大"约束 | R-20 |
| V-7 | 过 1 后允许飞回（`ones_called` 失效） | R-22/R-23 状态不变式 |
| V-8 | 起叫下限 `ceil(1.5N)` 改 `floor` | R-14 / 起叫表 |

### 4.2 属性测试清单

| 属性 | 锚点 |
| --- | --- |
| 同种子 + 同决策序列 ⇒ 事件流逐字段相等 | 02 A-10 |
| 合法动作集完备：每个非法动作被拒且 reason 非空 | 02 §3.1 |
| 信息隔离：任意玩家视图不含他人手牌/种子 | 02 §5 |
| 结算恒等式：胜负 ⇔ `count ≥ X` | R-45 |
| 生命周期转移合法性（非法转移不可达） | 05 §2.1 |

### 4.3 CI 门禁总表

| 门禁 | 内容 | 阈值 |
| --- | --- | --- |
| G-lint | ruff 全绿 | 0 告警 |
| G-type | mypy --strict | core 必过；其余告警清零后转必过 |
| G-test | pytest 全绿 | — |
| G-cov | 行覆盖 | core / engine ≥ 95% |
| G-trace | 追溯孤儿 | 0 |
| G-mut | 变异清单 | 全红 |
| G-e2e | 脚本机器人全桌冒烟 | 每次合并跑 |

### 4.4 手动验收（真实 API / 浏览器，不进 CI）

P3 双家真实冒烟 → P4-W1 全程观战 → P5 PVE 全动作 → P7 报告目检。每阶段手动验收清单在阶段完成时勾选并记录于 §6 表格。

---

## 5. 风险与前置工序

| 风险 | 影响 | 对策 |
| --- | --- | --- |
| 模型线时效（六家迭代极快） | P3/P6 接入即失效 | N3-01 核对清单为**每家接入前硬工序**；型号 ID 全走配置（03 N3-04） |
| API 限流 / 成本失控 | 批量阶段账单 / 卡死 | 并发上限 + Flash 轨默认 + 预算护栏（03 B-07）；评述用 Flash（N5-03） |
| LLM 行为不可测（拒答/幻觉） | 桌局中断 | 降级代打政策（02 A-15）+ 评测过滤降级回合 |
| 单人带宽 | 周期拉长 | 阶段独立可交付、可暂停；每阶段完成后即为可用状态 |
| 前端栈陌生 | P4/P5 变慢 | 页面数已最小化（3 页）；不引 UI 组件库之外的复杂层 |
| 粤语台词质量 | 行为面指标失真 | 人格包在 P6 集中调校；E-12 词表可迭代 |

**前置工序汇总**：N3-01（P3 前 2 家 / P6 前 4 家）、N4-03（P4 前，极简）、N5-04（P7 前）。

---

## 6. 里程碑顺序与状态

```
P0 ──► P1 ──► P2 ──► P3 ──► P4 ──► P5 ──► P6 ──► P7 ──► P8
 脚手架  内核   编排   适配×2  宿主+EVE  PVE+LOG  适配×4   批量评测  收尾
               └──────── eval 指标可并行开发（只需 stream.jsonl schema）──────┘
```

| 阶段 | 内容 | 工作量 | 依赖 | 状态 |
| --- | --- | --- | --- | --- |
| P0 | 脚手架 | S | — | **已完成（2026-11-10）** |
| P1 | 规则内核（M1） | M | P0 | **已完成（2026-11-11）** |
| P2 | 编排与持久（M2） | L | P1 | 未开始 |
| P3 | 适配器 SDK + 2 家（03 M4a） | M | P2 | 未开始 |
| P4 | 宿主 + EVE 观战（04 W1） | M | P2、P3 | 未开始 |
| P5 | PVE + LOG（04 W2/W3） | M | P4 | 未开始 |
| P6 | 其余 4 家（03 M4b） | M | P3 | 未开始（可与 P4/P5 并行） |
| P7 | 批量评测（M3） | L | P2（指标可提前）、P3（真实数据） | 未开始（指标模块可与 P3 并行） |
| P8 | 收尾 | S | P7 | 未开始 |

> 状态列随施工推进更新，作为施工日志；每阶段完成时附手动验收勾选记录。

### P0 完成记录（2026-11-10）

| P0 任务 | 产出 | 状态 |
| --- | --- | --- |
| uv 初始化 + `pyproject.toml`（ruff/mypy/pytest 配置） | `pyproject.toml`、`uv.lock`（51 包）、`src/perudo/__init__.py` | 完成 |
| CI：lint + type + test + 覆盖率四门禁 | `.github/workflows/ci.yml`（6 个作业，见 §8 修订记录 R-01） | 完成 |
| `tests/traceability.md` 矩阵骨架（先建表，P1 填充） | `tests/traceability.md`（R-01 ~ R-68 共 **68** 行，全 `pending`）+ `scripts/check_traceability.py` | 完成 |
| `.gitignore` 增补 `data/`、`frontend/dist/` | 另增 `/frontend/node_modules/`（P4 Vite 前端依赖，防入库） | 完成 |

**本地门禁实跑记录**（与 CI 同一套命令，全部 exit 0）：

| 门禁 | 命令 | 结果 |
| --- | --- | --- |
| G-lint | `uv run ruff check .` / `uv run ruff format --check .` | All checks passed / 5 files already formatted |
| G-type | `uv run mypy src/perudo` | Success: no issues found in 1 source file |
| G-test | `uv run pytest` | 2 passed |
| G-cov | `uv run pytest --cov=perudo --cov-report=term-missing --cov-report=xml` | 2 passed，coverage.xml 已产出 |
| G-trace | `uv run python scripts/check_traceability.py` | 矩阵尚未启用（P1 待填充），68 条规则待填 |
| 依赖边界 | `uv run python scripts/check_imports.py` | 通过（core/engine 尚未落地，暂未生效） |

**手动验收**：P0 无真实 API / 浏览器环节，全部为机器可验项，已全部实跑通过。

**首轮 GitHub Actions 实跑（2026-11-10，run id 42763507250，结论 `success`）**：

| 作业 | 结论 | 对应本地命令 |
| --- | --- | --- |
| 代码风格 · ruff | success | `uv run ruff check .` + `uv run ruff format --check .` |
| 类型检查 · mypy | success | `uv run mypy src/perudo` |
| 单元测试 · pytest · Python 3.12 | success | `uv run pytest`（3.12 档） |
| 单元测试 · pytest · Python 3.13 | success | `uv run pytest`（3.13 档） |
| 覆盖率 · pytest-cov | success | `uv run pytest --cov=perudo --cov-report=term-missing --cov-report=xml` |
| 追溯矩阵 · 孤儿检查 | success | `uv run python scripts/check_traceability.py` |
| 依赖边界 · 零三方依赖 | success | `uv run python scripts/check_imports.py` |

7 个作业实例（6 个作业，test 矩阵展开为 3.12 / 3.13 两档）全部通过。由此首次验证了三处本地不可验的面：ubuntu runner 环境、**Python 3.12 矩阵档**、干净 runner 上的 `uv sync --frozen` 安装行为；同时验证 §8 R-01.2 的 action 升版（node24 档）无兼容问题。

### P1 完成记录（2026-11-11）

| P1 任务 | 产出 | 状态 |
| --- | --- | --- |
| `core/types.py`（2×2 状态、动作类型） | 共享契约：`CallState`（2×2，构造期强制 `ones_called ⇒ DEAD`）、`Bid/BidAction/BidKind`、`ChallengeKind/ResponseKind`、`RuleConfig`（§12 十八项全开关）、结算载体 `StakeContext/LoserEntry` | 完成 |
| `core/legality.py`（R-11~R-28、R-64） | 五步短路 `bid_legal` + `apply_bid`、起叫下限表 `min_opening_bid`、双轨点数序 `face_beats`、杀类 `challenge_legal`（R-29~R-32）、应牌 `response_options`（R-33/R-34）、再反杀 `recounter_target`（R-36）、重摇谓词 `needs_reshake`（R-08/09/60/61）与 `reroll_verdict_failed`（R-65） | 完成 |
| `core/counting.py`（R-37~R-43、D-02 字面计数、围骰/全骰） | `player_contribution / count_table / total_count`；围骰 +1 / 全骰 +2 仅飞态、全红变体仅飞态、顺色/散骰计 0 变体开关 | 完成 |
| `core/settlement.py`（R-45 判定、§14.2 倍数叠加、投降减半保底、进阶开关） | `judge / decide_bid_stood`（R-45 + R-63 天黑黑前置）、`settle_stake`（R-46~R-56 + D-04 裁决口径 + R-52 保底）、`multi_kill_double`（R-50）、`drink_along_pick`（R-57，D-05 登记约定）；**R-47 歧义按 05 N5-01：不做下注上限特判** | 完成 |
| `core/opening.py`（R-05 + A-05） | `opening_caller`：上一局输家先叫，多输家取罚码最多者、并列沿座位方向取先 | 完成 |

**验收标准对账**（§3 P1 表逐条）：

| 验收标准 | 锚点 | 结果 |
| --- | --- | --- |
| 01 §13 三例完整对账逐项通过 | 01 §13 | ✓ `tests/unit/test_scenario.py` 三例全对账（逐叫骰合法性 + 状态转移 + 逐玩家贡献 + 判定结算），另含 D-04 进阶变体端到端断言 |
| R-xx 追溯矩阵无孤儿（含 R-60~R-68 边角） | 01 全文 | ✓ `check_traceability.py`：「通过：68 条规则全部有测试覆盖」，矩阵启用（单向棘轮） |
| 属性测试：计数单调、合法性自洽、`ones_called ⇒ DEAD` 不变式 | §4.2 | ✓ `tests/properties/` 三文件穷举：252 手牌 × 面值 × 状态 × 配置单调性、合法性 ≍ 独立规约式（17k 组合）、结算分解恒等（16k 组合）、2×2 构造守护；注：单调性限定不计 0 配置（顺色计 0 变体下天然不成立，属变体设计后果，测试内注明） |
| 变异清单 v1 全红 | §4.1 | ✓ `scripts/check_mutations.py`：V-1~V-8 全部杀灭（基线预检 + 逐条变异跑全量测试） |
| core 零三方依赖、零 IO、零随机 | §2.3 | ✓ `check_imports.py` 通过（core 5 文件） |

**本地门禁实跑记录**（2026-11-11，全部 exit 0）：

| 门禁 | 命令 | 结果 |
| --- | --- | --- |
| G-lint | `uv run ruff check .` / `uv run ruff format --check .` | All checks passed |
| G-type | `uv run mypy src/perudo` | Success（strict，7 文件） |
| G-test | `uv run pytest` | **88 passed** |
| G-cov | `uv run pytest --cov=perudo --cov-report=term-missing` | 98.47%（≥ 95，fail_under 已收紧至 core/engine） |
| G-trace | `uv run python scripts/check_traceability.py` | 68 条全部 covered，孤儿 0 |
| G-mut | `uv run python scripts/check_mutations.py` | V-1~V-8 全部杀灭 |
| 依赖边界 | `uv run python scripts/check_imports.py` | 通过 |

**施工说明**：本阶段原计划以三个并行子代理分模块施工，因用户并发额度触顶全部失败且未产出文件，改由主会话单线完成；共享契约（types.py）先行冻结、测试先行锁定 API 的做法使集成零返工。属性测试在集成中逮到两处测试侧规约缺陷（转斋规约漏 `X' ≥ X0`、单调性未排除计 0 变体），实现本身零缺陷通过。

---

## 7. 变更纪律

1. **实现不得偏离设计稿**：发现设计疑义/缺口 → 回对应设计文档登记并走业主裁决（对齐既定工作方式），裁决结果先改设计文档、再改代码。
2. **契约只增不删**（02 A-20）：`PlayerView`、事件类型、附件信封字段的新增走评审，删除禁止。
3. **计划状态更新**只在本文 §6 表格；阶段验收标准的变更须在本文登记修订记录。

---

## 8. 修订记录

### R-03 P1 施工（2026-11-11）

| # | 变更 | 依据 | 说明 |
| --- | --- | --- | --- |
| R-03.1 | G-cov 收紧落地 | §4.3（core/engine 行覆盖 ≥ 95%） | `pyproject.toml` 增 `fail_under = 95`，coverage report `include` 限定 `src/perudo/core/*` 与 `src/perudo/engine/*`——adapters/host/eval（P3 起）不在 G-cov 口径内，与门禁总表范围一致。实测 98.47%。 |
| R-03.2 | CI 新增 G-mut 作业 | §4.1（变异清单放进 CI 的变异作业） | `.github/workflows/ci.yml` 增 `mut` 作业跑 `scripts/check_mutations.py`（V-1~V-8 逐条变异 + 全量测试须变红；基线非绿或锚点漂移 exit 2）。G-e2e 仍待 P2。 |
| R-03.3 | 追溯矩阵启用 | 矩阵 §0.6 单向棘轮 | 68 行全部 `covered`（P1 填充，见矩阵变更记录 v1.1）；自此任何规则不得退回孤儿态。A 类变体用守护性测试、B 类用开关两态功能测试（D-03 口径）。 |
| R-03.4 | `core/opening.py` 独立成模块 | §2.2 布局（core 含 opening） | §3 P1 任务表原把 R-11~R-14 归入 legality.py（已按此实现：`min_opening_bid`/`opening_legal` 在 legality.py）；R-05 首叫玩家确定（A-05 并列取先）落 `opening.py`，与布局五模块清单一致。 |
| R-03.5 | 施工方式记录 | 工程事实 | P1 原拟三并行子代理分模块施工，因用户并发额度触顶全部失败且无产出；改主会话单线完成（契约先行 + 测试锁定 API，集成零返工）。后续阶段仍可按额度情况选择并行。 |

### R-02 P1 开工前裁决落地（2026-11-10）

业主逐项拍板 §8 待裁决项 D-01 / D-02 / D-03，按「先改设计文档、再改代码」纪律落地：

| # | 变更 | 依据 | 说明 |
| --- | --- | --- | --- |
| R-02.1 | 计划 P1 验收标准编号上界 R-60~R-67 → **R-60~R-68** | D-01 裁决 | 原表述实际位于 §3 P1 验收标准表（此前 R-01.5 / D-01 记述为「§4.1」，以实际位置为准）。设计稿与矩阵本已登记至 R-68，本次仅计划文字对齐。 |
| R-02.2 | 设计稿 `01-game-rules.md` §3 流程汇总表改为实际规则区间 | D-02 裁决 | 新区间：杀发起 R-29~R-32、应牌 R-33~R-36、计数 R-37~R-43、判定 R-45、结算 R-46~R-52（基础）+ R-53~R-57（进阶）；表下加边角条款（R-60~R-66 散见各章）与变体（R-44/58/59/67/68 基线不实现）注记；顺手修正该表「开盰」错别字为「开盅」。 |
| R-02.3 | 变体追溯口径维持矩阵 §0.8 不变 | D-03 裁决 | A 类（R-44/58/59/67/68）守护性测试、B 类（R-61/62/63、R-53~57）功能测试；`check_traceability.py` 不改。 |

至此 P1 开工前置条件全部就绪：验收口径唯一（设计稿 §3 ↔ 正文实际条款 ↔ 追溯矩阵三方一致）、追溯上界定案（R-68）、变体口径定案（§0.8）。

### R-01 P0 施工（2026-11-10）

| # | 变更 | 依据 | 说明 |
| --- | --- | --- | --- |
| R-01.1 | CI 作业由「四门禁」扩为 **6 个** | §4.3 门禁总表 + §2.3 依赖边界门禁化 | 在 lint/type/test/cov/trace 之外新增 `deps` 作业，跑 `scripts/check_imports.py`（core/engine 禁三方依赖、禁 `random` 直调、禁时钟与网络直调，依据 02 A-19 / A-10 / A-14）。该检查在 P0 判定为「暂未生效」并通过，P1 内核落地后自动生效，无需再改 CI。 |
| R-01.2 | GitHub Actions 版本统一升到 **node24 档位** | 运行时事实 | `actions/checkout@v7`、`actions/setup-python@v7`、`actions/upload-artifact@v7`。理由：Node.js 20 已于 2026-09-16 从 GitHub runner 移除，旧版 action（checkout@v4 / setup-python@v5 / upload-artifact@v4）仍声明 `node20`，存在运行时不兼容隐患。已核验 upload-artifact v4→v7 的输入接口（`name` / `path` / `if-no-files-found`）未变，行为兼容。 |
| R-01.3 | ruff 排除 `docs/` 目录 | 工具链事实 | 实测 ruff 0.17 会格式化 Markdown 内的 Python 代码块，若纳入则 `ruff format .` 将改写中文设计稿、纯文档改动也会把 G-lint 打红。 |
| R-01.4 | `pyproject.toml` 声明 `license = "GPL-2.0-only"` | 仓库 `LICENSE` | `LICENSE` 为 GPL v2 原文。「only / or-later」属法律口径，**留待业主确认**；若应为 `or-later`，改一个词即可，不影响依赖锁。 |
| R-01.5 | 追溯矩阵扩展至 R-68 | `01-game-rules.md` §9.3 | 计划 §4.1 原表述为「R-60~R-67 边角」，而设计稿实际定义到 **R-68（反弹）**。矩阵按设计稿实况登记至 R-68；计划编号上界已于 R-02 裁决改为 R-68（见 §8）。 |

### 裁决登记（D-xx）

| # | 事项 | 事实 | 裁决结果 | 状态 |
| --- | --- | --- | --- | --- |
| D-01 | 计划「R-60~R-67」与设计稿实际 R-68 不一致 | `01-game-rules.md` §9.3 定义了 R-68（反弹，标注为「变体，基线不实现」）；矩阵已按 R-68 登记 | **计划改为 R-68**：P1 验收标准编号上界同步改为 R-60~R-68；设计稿与矩阵不动 | 已裁决（2026-11-10） |
| D-02 | 设计稿 `01-game-rules.md` §3 流程表的规则区间与后续章节不一致 | §3 汇总表写「⑥计数 R-34~R-38、⑦判定 R-39、⑧结算 R-40~R-47」，但 §7 实际定义 R-34~R-36 为反杀/投降、§8.3 才是判定 R-45、§9.1 才是基础结算 R-46 起。追溯矩阵的「规则出处」一律指向**实际定义条款** | **更新设计稿 §3 汇总表**为实际区间（见 R-02.2），读者无需再跳转核对 | 已裁决（2026-11-10） |
| D-03 | 变体规则（基线不实现）的追溯口径 | R-44、R-58、R-59、R-67、R-68 标注「变体，基线不实现」。追溯矩阵 §0.8 已定：其「覆盖」= 守护性测试（证明基线下不被触发），而非功能测试 | **维持矩阵 §0.8 现口径**（A 类守护性测试 / B 类功能测试），检查器不改 | 已裁决（2026-11-10） |
| D-04 | 01 §9.2 进阶结算 R-54/R-55/R-56 语义分叉 | R-55「超半」条件在 count ≥ X 时自动成立，是否翻转 R-45 未闭合；「被开者/开杀者」名词范围未定；§13 三例均关闭进阶，无例可校 | **R-55 修辞性加倍，不翻转 R-45**；R-54/R-55 严格限开杀链、R-56 专管跳杀失败、R-53 两链通用；各加倍项乘法叠加；count 恰为 X/2 不加倍。口径表已补注于 01 §9.2 | 已裁决（2026-11-10） |
| D-05 | 陪饮骰（R-57）「按点数顺时针选一位」的映射细则缺失 | 2 颗骰的点数如何映射到 2~6 人的一位玩家、6/12 人「1 颗大骰」的面数，原文无细则；R-57 配置默认关，但 B 类开关测试需要确定映射 | P1 暂按登记约定实现：**两骰点数之和 s，从负方自己起沿座位方向数第 `((s − 1) mod N) + 1` 位为目标，摇中自己则加倍**；1 颗大骰按面值同式。业主改判时只改 `drink_along_pick` 一处 | **待裁决**（P2 落地陪饮前需定） |
