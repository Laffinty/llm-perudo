# 大话骰（Perudo）—— LLM 多人桌游引擎

以 LLM 玩家为核心的实时多人骰子桌游引擎：EVE（LLM 对 LLM）与 PVE（真人对 LLM）并重，规则内核零第三方依赖、对局全程可重放、评测数字全由程序产出。

- 规则事实源：[`docs/design/01-game-rules.md`](docs/design/01-game-rules.md)（广东·广州玩法，R-01~R-68）
- 工程构建计划：[`docs/plan/01-build-plan.md`](docs/plan/01-build-plan.md)（P0–P8 施工序列 + 决策登记）

## 快速开始

前置：Python 3.12+，[uv](https://docs.astral.sh/uv/)（依赖与环境管理）。

```bash
# 安装依赖与环境
uv sync

# 全量测试（170+ 用例，≈1 分钟）
uv run pytest -q

# 单桌冒烟（4 bot 快速局，REST 建桌）
uv run python scripts/run_host.py --port 8900 &
curl -s -X POST http://127.0.0.1:8900/matches \
  -H "Content-Type: application/json" \
  -d '{"mode":"eve","slots":[{"kind":"bot"},{"kind":"bot"},{"kind":"bot"},{"kind":"bot"}],"config":{"end_threshold":6}}'
# 浏览器打开 http://127.0.0.1:8900/?match=<返回的 match_id>&mode=eve 观战
```

## 前端（Vue 3 + Vite）

```bash
cd frontend
npm install
npm run build   # 产物 dist/ 由宿主静态托管
```

宿主启动时自动托管 `frontend/dist`（缺失时返回构建提示）。

## LLM 玩家接入（03 六家）

每玩家一份 TOML 配置（`examples/players/`），API Key 走环境变量引用（`env:VAR`，永不落盘）：

```toml
[player]
provider = "glm"
model    = "glm-5.3-flash"
api_key_ref = "env:GLM_API_KEY"

[persona]
name = "细霞"
style = "广州西关口音，嘴快过脑"
trash_talk = 1
```

支持六家：DeepSeek / GLM / MiMo（OpenAI + Anthropic 双协议）/ Qwen / 豆包 / MiniMax。
各型号 ID 全走配置不做硬编码（N3-04）；接入前按各官方文档核对 thinking 字段（03 §5.7.1 已留核对结果）。

**真实 API 冒烟**（持键执行）：

```bash
DEEPSEEK_API_KEY=... uv run pytest tests/unit/test_adapters_smoke_real.py -v
```

## 跑一桌（PVE：真人对 LLM）

1. 启动宿主：`uv run python scripts/run_host.py --port 8900`
2. 浏览器打开 `http://127.0.0.1:8900` → 开桌向导选 PVE
3. 人类席（恒为 1 席）从动作面板出牌（合法动作集由引擎下发）；LLM 席需对应 Key 环境变量
4. 终局自动转结束页（积分最小者胜）

## 跑批量评测（EVE bot/LLM 桌）

```python
from pathlib import Path
from perudo.eval.scheduler import BatchSpec, run_batch

spec = BatchSpec(
    slots=tuple({"kind": "bot", "name": f"bot{i}"} for i in range(4)),
    config={"end_threshold": 20, "max_rounds": 100},
    seat_rotations=2,  # 座位轮换（05 §6.3）
)
result = run_batch(
    spec, master_seed=2026, data_root=Path("data"), max_parallel=2, verify_reproducible=True
)
print(result.aggregate)  # E-01~E-15 跨桌聚合
print(result.reproducible)  # G-06 整批复现抽样
```

LLM 桌：把 slots 里的 bot 换成 `{"kind": "llm", "provider": "glm", "model": "glm-5.3-flash", ...}`（需环境变量 Key）。

## 工程结构

```
src/perudo/
├─ core/       # L0 规则内核：合法性 / 计数 / 结算（纯函数，零 IO 零随机）
├─ engine/     # L1 编排：状态机 / 事件流 / stream.jsonl / 重放 / 人类席桥
├─ players/    # 玩家契约（PlayerView / Decision）+ 保守机器人
├─ adapters/   # LLM 接入：SDK 六件套 + 六家 Tuning（P3 首批 + P6 四家）
├─ host/       # Web 宿主：REST + WS 视图流网关 + LOG Writer
└─ eval/       # 批量评测：E-01~E-15 指标 / 调度器 / 报告 / AI 评述
frontend/      # Vue 3 + Vite SPA（向导 / 对局主界面 / 结束页）
tests/         # 170+ 用例（unit / properties / e2e）
scripts/       # 开发辅助（宿主入口 / 变异检查 / N-01/N-02 统计）
docs/          # 设计稿五份 + 构建计划（决策登记表全量留痕）
```

## 质量门禁（CI 七作业）

G-lint / G-type（mypy strict）/ G-test（3.12+3.13 双档）/ G-cov（core+engine ≥95%）/
G-trace（R-01~R-68 追溯矩阵零孤儿）/ G-mut（变异清单 V-1~V-8 全杀灭）/ 依赖边界（内核零三方依赖）。

## 文档索引

| 文档 | 内容 |
| --- | --- |
| `docs/design/01` | 游戏规则（68 条 R-xx + 三例推演 + N-01/N-02 附录） |
| `docs/design/02` | 引擎框架（生命周期 / 契约 / 事件流 / 配置 / 机器人） |
| `docs/design/03` | LLM 接入层（SDK / 六家选型 / 防注入 / Tuning） |
| `docs/design/04` | Web 界面（三页结构 / 视图纪律 / 气泡三分） |
| `docs/design/05` | 评测设计（E 指标 / 调度 / 三层记录 / AI 评述边界） |
| `docs/plan/01` | 构建计划（P0–P8 + 决策登记 D-01~D-07 全量留痕） |

## License

GPL-2.0-only（见 LICENSE）
