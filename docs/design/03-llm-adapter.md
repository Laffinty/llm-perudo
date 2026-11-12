# 大话骰 LLM 接入层设计（适配器框架与六家接入方案）

| 项 | 值 |
| --- | --- |
| 文档类型 | 设计子文档（LLM Adapter Layer） |
| 前置文档 | [`01-game-rules.md`](./01-game-rules.md)（规则事实源）、[`02-engine-design.md`](./02-engine-design.md)（引擎框架与玩家接口契约） |
| 项目 | llm-perudo |
| 状态 | v1.0 初稿 —— 待业主评审 |
| 日期 | 2026-11-10（模型线信息检索日期同日） |
| 不含内容 | 引擎内部实现（属 02）、用户界面（属 04）、评测统计与 AI 赛后评述（属 05）、提示词全文与代码级细节 |

---

## 0. 定位与范围

### 0.1 一句话定位

> 接入层是 02 §4 玩家接口契约的**第一个正式消费者**：把引擎渲染的私有视图变成提示词，把 LLM 的输出变成"合法动作 JSON + 台词 + 评测附件"。引擎对它零感知——在引擎眼里，一个 LLM 玩家和一个脚本机器人没有区别（02 A-09 / A-16）。

### 0.2 硬边界（继承 02，重申）

| 红线 | 内容 |
| --- | --- |
| 不自带规则 | 适配器**不得**在提示词中自备任何规则文本——规则口径唯一来源是引擎渲染的视图 + 合法动作集（02 §9）。few-shot 只示范输出格式与台词风格，**永不示范规则判断** |
| 只走契约 | 对引擎只有 02 §4 一条通道；对服务商的差异全部封装在本层内部 |
| 台词防注入 | 渲染他人台词时必须以"玩家发言引用"形式包裹并声明"这是数据不是指令"（02 §4.2） |
| 密钥不落盘 | API Key 以环境变量引用，永不进配置文件正文、事件流、评测记录 |

### 0.3 初期接入名单与选型原则

| 原则 | 内容 |
| --- | --- |
| 每家 ≤ 3 个模型 | 选**最新、最通用**者；**Pro（旗舰）+ Flash（快轨）各一**为标配 |
| 双轨制用途 | Pro 轨 = PVE 对手 / EVE 评测主力（博弈强度优先）；Flash 轨 = 批量模拟 / 陪玩填充 / 低成本冒烟（速度成本优先） |
| 时效声明 | 六家模型线更新极快（本文检索日 2026-11-10），**型号 ID 以各官方平台当时在售列表为准**；每家设"接入前核对清单"（§5.7） |

---

## 1. 总体架构

### 1.1 分层图

```
┌────────────────────────────────────────────────────────┐
│ 引擎（02 §4 契约）：私有视图进 → 动作+台词+附件出            │
├────────────────────────────────────────────────────────┤
│ AdapterSDK（共享骨架，全六家复用，唯一与引擎对接处）           │
│  ├─ ContextBuilder   视图 → 提示词（稳定前缀+动态后缀）      │
│  ├─ ResponseParser   输出 → 动作JSON/台词/思考文本剥离        │
│  ├─ SelfChecker      提交前本地合法性自检（不耗引擎纠错预算）   │
│  ├─ RetryController  网络重试 + 纠错循环（对接 02 §4.3）      │
│  ├─ CostLedger       token/延迟/思考文本 → 评测附件（不透明）  │
│  └─ Transport        HTTP 客户端（协议可插拔）               │
├────────────────────────────────────────────────────────┤
│ 六家适配器：一家一个独立模块 = Transport配置 + Tuning表 +      │
│             少量钩子覆写                                   │
│  deepseek_adapter · mimo_adapter · glm_adapter            │
│  qwen_adapter · doubao_adapter · minimax_adapter          │
└────────────────────────────────────────────────────────┘
```

### 1.2 核心原则："六家一个骨架，一家一份 Tuning"

| 决策 | 内容 |
| --- | --- |
| B-01 | 初期六家：DeepSeek、MiMo（小米）、GLM（智谱）、Qwen（阿里）、豆包（字节）、MiniMax |
| B-02 | **双层契约**：对引擎一层（六家完全一致，02 §4）；对服务商一层（每家独立模块，含各自 Tuning） |
| B-03 | 共性 ≈ 90% 收进 AdapterSDK；差异点只允许出现在三处：Tuning 数据表、协议 Transport、显式声明的钩子覆写 |
| B-04 | 适配器在提交引擎前**本地自检**合法性（视图里本来就有合法动作集）——自检循环不消耗引擎的纠错预算（02 §4.3），被引擎驳回才消耗 |
| B-05 | 思考（reasoning）预算**按对局阶段分配**：常规跟叫省、应牌链豪——是所有家共用的调优思想，各家映射到自家参数 |
| B-06 | 台词人格包（persona）是与模型无关的个性化维度：名字、语言风格（粤语/普通话）、攻击性等级、话痨程度 |
| B-07 | 成本护栏：单桌 token 预算上限（默认关闭），超限动作可配（切 Flash 轨 / 触发降级代打） |
| B-08 | 六家全部有 OpenAI 兼容协议 → Transport 默认一套；MiMo 额外兼容 Anthropic 协议 → Transport 第二实现仅为其存在 |

### 1.3 一次决策的完整流程（适配器内部状态机）

```
收到视图 → ContextBuilder 渲染
        → Transport 调用（网络层重试：指数退避，独立于引擎）
        → ResponseParser 解析（剥离思考文本 → 附件；提取动作JSON+台词）
        → SelfChecker 自检（非法 → 带原因内部重试，最多 tuning.self_check_retries 次）
        → 提交引擎
             ├─ 引擎接受 → CostLedger 结账 → 附件上报 → 结束
             └─ 引擎驳回（耗引擎纠错预算）→ 带原因回到 Transport（引擎预算内）
        → 调用异常/超时 ×3 → 返回"决策失败" → 引擎代打（02 §4.3，记降级回合）
```

---

## 2. 统一调优参数骨架（所有适配器共有）

| 类别 | 参数 | 默认 | 说明 |
| --- | --- | --- | --- |
| 接入 | `api_key_ref` | —— | 环境变量引用（B-08 红线） |
| 接入 | `base_url` | 各家官方端点 | 指向自托管端点即实现私有部署（见 §5.2 MiMo） |
| 接入 | `model` | —— | 型号 ID 或火山推理接入点 ID（§5.5） |
| 接入 | `timeout_ms` / `net_retries` | 30000 / 3 | 网络层，独立于引擎纠错 |
| 生成 | `temperature` / `top_p` | 各家推荐值 | 见 §5 各家 |
| 生成 | `max_tokens` | 1024 | 含台词 |
| 思考 | `thinking` | per-phase | 取值 `off / low / mid / high / auto`，映射各家参数（§5） |
| 输出 | `output_mode` | `json_mode` | `json_mode / tool_call / prompt_json`——优先用服务商原生 JSON 模式，其次工具调用结构化，最后纯提示词约定 |
| 输出 | `self_check_retries` | 2 | 提交前自检循环次数（B-04） |
| 呈现 | `context_presentation` | `summary` | `full`（全量事件流水）/ `summary`（近期压缩）——上下文预算旋钮（02 §9） |
| 呈现 | `legal_actions_presentation` | `constraints` | `enumerate`（全量枚举）/ `constraints`（约束描述 + 值域） |
| 呈现 | `history_depth` | `recent_10` | 叫骰流水带多长 |
| 人格 | `persona` | —— | 名字、语言风格、背景设定（不含规则） |
| 人格 | `quote` | 开 | 开关、语言、`trash_talk` 0–3 攻击等级、风格模板；长度上限以桌级配置为准 |
| 阶段 | `phase_overrides` | —— | `opening / bidding / respond / challenge` 四阶段可覆盖以上生成/思考/呈现参数（B-05） |
| 护栏 | `match_token_budget` | 关 | 单桌预算上限 + 超限动作（B-07） |

---

## 3. 提示词装配规范

| 块 | 内容 | 来源 |
| --- | --- | --- |
| 系统提示（稳定前缀） | 身份（persona）+ 目标（赢桌局、少喝酒）+ 输出格式契约 + **防注入声明** | 适配器 + 桌级配置 |
| 局面块（动态） | 引擎渲染的私有视图摘要：手牌、叫骰流水（他人台词以引用块）、飞/斋状态、积分局势 | **引擎**（唯一规则知识来源） |
| 动作块（动态） | 合法动作集呈现（按 `legal_actions_presentation`）+ 当前阶段说明 | **引擎** |
| few-shot（可选） | 仅输出格式与台词风格示例 | 适配器（**禁含规则判断**） |

> **装配顺序规范（服务 MiniMax 前缀缓存，§5.6）**：稳定内容（系统提示）永远在前，动态内容在后。这对支持自动前缀缓存的服务商是直接的省钱设计，对其他家无害。

---

## 4. 评测附件规范（02 §4.1"不透明附件"的落地）

每个决策回合，适配器向引擎提交统一信封（引擎原样入评测层，不解析）：

```json
{
  "provider": "deepseek", "model": "deepseek-v4-pro",
  "latency_ms": 1840,
  "usage": {"input": 3120, "output": 210, "reasoning": 640},
  "thinking_text": "……（剥离出的思考全文；不进任何 LLM 玩家的上下文；呈现按 04 F-06：仅 EVE 观战流实时直出，PVE 实时面不提供，复盘档全量留存）",
  "parse_retries": 0, "self_check_retries": 1,
  "degrade_reason": null
}
```

用途：05 评测工具的成本面与合规面统计（02 §8）；`thinking_text` 是"决策面深度点评"的未来原料（属 05），也是 04 F-06"内心戏"的数据源——本层只负责留存与上报，呈现纪律由 04 定义（仅 EVE 观战实时直出；PVE 实时面不提供、复盘档全量留存；科研优先原则 F-10）。

---

## 5. 六家接入设计

### 5.0 选型总表（检索日 2026-11-10）

| 服务商 | Pro 轨（旗舰） | Flash 轨（快轨） | 备选/注记 | 协议 |
| --- | --- | --- | --- | --- |
| DeepSeek | `deepseek-v4-pro` | `deepseek-v4-flash` | V4.1-Flash（2026-09 上线）；旧名 `deepseek-chat/reasoner` **已于 2026-07-24 退役** | OpenAI 兼容 |
| MiMo（小米） | `mimo-v2.6-pro` | `mimo-v2.6-flash` | V2.5 系已于 2026-10-21 下线；MIT 开源权重可自托管；支持 Batch API | **OpenAI + Anthropic 双兼容** |
| GLM（智谱） | `glm-5.3` | `glm-5.3-flash` | FlashX 高速变体（200 tok/s） | OpenAI 兼容 |
| Qwen（阿里） | `qwen3.8-max` | `qwen-flash` | `qwen-plus` 均衡主力；型号 ID 以百炼在售列表为准 | OpenAI 兼容 |
| 豆包（字节） | `doubao-seed-2.1-pro` | `doubao-seed-2.1-turbo` | `doubao-seed-2.0-lite` 超低价批量备选；方舟支持推理接入点 | OpenAI 兼容 |
| MiniMax | `MiniMax-M3` | `MiniMax-M3.1-Flash` | M3.1-Flash 2026-10-19 发布：200+ tok/s、降价 50%、开源权重；speed 变体是否存在待核 | OpenAI 兼容 |

### 5.1 DeepSeek 适配器

**特性要点**：V4 Pro 为 1.6T MoE（49B 激活）、1M 上下文 / 384K 输出、支持 thinking mode 与工具调用；Flash 价格约 Pro 的 1/3、并发上限更高；**官方明确 V4 对 temperature 与提示词结构更敏感**（迁移指南建议重调）。

**针对性设计思路**：

1. **温度敏感 → 温度矩阵是头等调优项**：默认矩阵偏保守（常规叫 0.9 / 应牌 0.7），评测时全局锁定并记录，杜绝跨桌温度漂移污染数据。
2. **思考分层直通**：V4 thinking 支持分级（低/中/高/最高），映射 `phase_overrides.thinking`——常规跟叫 `low`，应牌链（反杀/投降抉择）`high`。推理 token 计费，分层即省钱。
3. **退役名拒绝**：配置校验直接拒绝 `deepseek-chat` / `deepseek-reasoner`（已退役），给出迁移提示——防旧教程抄来的配置静默降级。

**针对性参数**（2026-11-13 按 §5.7 核对修订）：

| 参数 | 取值 | 说明 |
| --- | --- | --- |
| `thinking_type` | enabled / disabled（per-phase） | 请求体 `thinking: {type}`；默认 enabled，`disabled` = 非思考模式（实测可用） |
| `reasoning_effort` | low / high / max（per-phase） | 思考深度档位（默认 high；社区报告 low/medium 可能被静默映射，有效档以 high/max 为主） |
| `temperature_matrix` | 阶段→温度 | 显式成表（B-05），评测锁定；**注意：思考模式下 temperature 被服务端忽略（不报错）**——温度矩阵仅对 `disabled`（非思考）档生效；非思考模式官方推荐 1.0 |
| `reject_legacy_names` | true（默认） | 退役型号守门 |

### 5.2 MiMo 适配器（小米）

**特性要点**：官方开放平台 mimo.mi.com；**六家中唯一同时兼容 OpenAI 与 Anthropic 两种协议**；Pro（$0.435/M 入）与 Flash 双档；支持 Batch API 与 Token Plan 订阅；V2.5 系权重 MIT 开源、V2.6-Flash-RL（311B）权重在 HuggingFace 可取。

**针对性设计思路**：

1. **双协议 Transport**：`protocol = openai | anthropic`，是 MiMo 独有参数——Anthropic 协议在长系统提示下的缓存行为更优，作为可选实验项。
2. **Batch API 接批量调度器**：一桌局内回合串行没法批，但**跨桌**可以批——EVE 批量评测（02 M3）中，非当桌依赖的决策可走 Batch 半价通道。默认关，批量模式开。
3. **自托管一等公民**：开源权重 → `base_url` 指向自建推理端点即可，PVE 离线场景 / 长期成本护城河；`self_hosted = true` 时跳过官方限流头与 Token Plan 校验。
4. **Pro/Flash 混编降级**：`match_token_budget` 触发时（B-07）可配置"Pro → Flash"降档而不是直接代打——比其他家多一档缓冲。

**针对性参数**：

| 参数 | 取值 | 说明 |
| --- | --- | --- |
| `protocol` | openai（默认）/ anthropic | 双协议选择 |
| `batch_mode` | off（默认）/ on | 跨桌批量走 Batch API |
| `self_hosted` | false（默认） | 自托管端点模式 |
| `downgrade_model` | —— | 预算超限时降档到的型号（如 flash） |

### 5.3 GLM 适配器（智谱）

**特性要点**：GLM-5.3 旗舰（复杂编程与 Agent 增强）；GLM-5.3-Flash/FlashX 为 320B 总参 / 18B 激活的稀疏+线性混合架构、1M 上下文、FlashX 达 200 tok/s、价格亲民（发布期五折）；原生多模态（本项目用不上）。

**针对性设计思路**：

1. **Flash 轨当批量评测默认**：价格与速度优势全六家前列（FlashX 200 tok/s ≈ 桌感无等待），PVE 界面未上前的冒烟测试也用它。
2. **思考深度按阶段直通（2026-11-13 按 §5.7 核对修订）**：**GLM-5.3 / Flash / FlashX 强制思考——`thinking: {type: "disabled"}` 会直接报错**（GLM-5.2 及更早才支持 enabled/disabled 切换）；5.3 系改用 `reasoning_effort`（low / high / max，默认 max）控制深度。phase_overrides 的 thinking 抽象档映射：off/low → low、mid/high → high、auto → 不传（走默认 max）；"真关思考"在 5.3 系不可达，属已知降级（B-05 的"常规叫省"由 low 档承接）。
3. **1M 上下文 → 呈现参数放开**：`context_presentation = full` + `legal_actions_presentation = enumerate` 作为 GLM 推荐默认，全量流水喂饱，博弈信息最全（与 02 §9"上下文预算是适配层参数"呼应）。

**针对性参数**：

| 参数 | 取值 | 说明 |
| --- | --- | --- |
| `reasoning_effort` | low / high / max（per-phase） | **5.3 系**思考深度（`thinking.type: disabled` 已不可用，见上）；GLM-5.2 及以下仍走 `thinking.type` |
| `use_flashx` | bool | Flash 轨下选 FlashX 高速变体（型号 ID `glm-5.3-flashx`，已核对） |
| `full_presentation` | true（推荐默认） | 放开全量呈现三参数 |

### 5.4 Qwen 适配器（阿里）

**特性要点**：Qwen3.8-Max（2026-08，2.4T 总参 / 95B 激活、1M 上下文）；qwen-plus 融合思考/非思考模式且**可在对话中途切换**；qwen-flash 极速轻量；百炼 OpenAI 兼容模式；中文口语与方言表达质量高。

**针对性设计思路**：

1. **思考预算精细化**：Qwen 系支持 `thinking_budget`（思考 token 预算上限）——比"开关"细一档，按阶段分配：常规叫 1K、应牌 8K。B-05 的最佳载体。
2. **台词人格包主推对象**：中文口语/粤语味道生成质量 → `trash_talk` 高等级人格默认在 Qwen 上调校，再移植他家。
3. **融合模式 = 逐调用切换**：plus 的思考切换是逐次调用生效的，正好匹配"每回合独立决策"的形态——不依赖会话状态，天然契合引擎的回合制。

**针对性参数**：

| 参数 | 取值 | 说明 |
| --- | --- | --- |
| `enable_thinking` | per-phase bool | 映射 Qwen 思考开关 |
| `thinking_budget` | per-phase int（如 1024 / 8192） | 思考 token 预算 |
| `quote_tuning` | 方言度、语气模板 | 台词人格细化 |

### 5.5 豆包适配器（字节 / 火山方舟）

**特性要点**：Doubao-Seed 2.1 系（Pro / Turbo，智能体强化、256K 上下文）；Seed 2.0 系 19 项基准 12 项第一、API 价格约为同类 1/10、2.0-Lite 输入低至 0.6 元/百万 token；中文对话自然度口碑高。

**针对性设计思路**：

1. **端点即模型**：火山方舟传统用推理接入点 `ep-xxxx` 调用——`model` 参数同时接受型号名与接入点 ID，配置校验识别形态。
2. **台词特化位**：中文闲聊与玩笑自然度 → 与 Qwen 并列的台词人格包主推对象；`trash_talk` 中等 + 粤语模板的组合先在豆包上调。
3. **Lite 轨成本洼地**：2.0-Lite 定价全六家最低 → 大规模 EVE 批量的"填充玩家"默认位（对手质量不敏感的桌次）。
4. **thinking 参数待核**：Seed 1.6 起有 `thinking: {type}` 结构；2.1 的精确字段在接入前核对（§5.7）。

**针对性参数**：

| 参数 | 取值 | 说明 |
| --- | --- | --- |
| `endpoint_id` / `model_name` | 二选一 | 方舟接入点与型号名双支持 |
| `thinking_type` | auto / enabled / disabled（per-phase） | 待 §5.7 核对字段名 |
| `budget_series` | seed-2.1 / seed-2.0-lite | 批量填充轨 |

### 5.6 MiniMax 适配器

**特性要点**：M3 旗舰（2026-06-01 发布：前沿编码、agentic 推理、1M 上下文、原生工具调用）；M3.1-Flash（2026-10-19 正式发布，此前自 9-27 起以"太空兔"匿名预演、压测超 200 万亿 token）：新一代 Flash，200+ tok/s 输出、**降价 50%**、1M 上下文、原生多模态 MoE、开源权重；M 系传统为交错思考（interleaved thinking）输出形态。

**针对性设计思路**：

1. **前缀缓存套利**：MiniMax 平台提供自动前缀缓存（M2.7 起为全自动零配置；M3.1 系的命中口径入 §5.7 核对）+ §3 装配顺序规范（稳定前缀在前）= 系统提示与桌局公共前缀几乎零成本重复——长桌局（100 分阈值可达上百局）下成本优势被复利放大。这是 MiniMax 的结构性省钱点，装配规范必须遵守。
2. **交错思考剥离**：M2 系思考交错出现在正文流中——ResponseParser 为其实现专用剥离钩子（`strip_think_blocks`），剥离文本进附件，绝不混入台词或动作字段。
3. **M3.1-Flash 直配快轨**：200+ tok/s 让长桌局的等待感趋零；降价 50% 后成为六家快轨的成本标杆之一。

**针对性参数**：

| 参数 | 取值 | 说明 |
| --- | --- | --- |
| `speed_variant` | normal / highspeed | 平台速度变体（M3.1 系是否保留 highspeed 档，待 §5.7 核对） |
| `strip_think_blocks` | true（默认） | 交错思考剥离钩子 |
| `stable_prefix_layout` | true（默认，强制） | 装配顺序规范守门 |

### 5.7 接入前核对清单（时效护栏）

每家适配器实现前，按官方当日文档核对以下字段——本文型号线为 2026-11-10 快照：

| 家 | 核对项 |
| --- | --- |
| DeepSeek | V4 thinking 层级的精确参数名与取值；温度推荐区间 |
| MiMo | V2.6 系 reasoning 字段位置；Batch API 配额；Anthropic 兼容的覆盖范围 |
| GLM | `thinking.type` 当前结构；Flash/FlashX 的型号 ID |
| Qwen | `enable_thinking` / `thinking_budget` 在 OpenAI 兼容模式下的传递方式；在售型号 ID（3.7/3.8 系） |
| 豆包 | Seed 2.1 的 thinking 结构；接入点 vs 型号名现行口径；2.0-lite 是否仍在售 |
| MiniMax | M3 / M3.1-Flash 的 API 型号名与 speed 变体是否保留；think 块输出格式；前缀缓存命中口径 |

### 5.7.1 核对结果回填

**DeepSeek（核对日 2026-11-13，来源：官方 API 文档 thinking_mode 指南、HuggingFace V4-Pro 模型卡、社区实测）**：

| 核对项 | 结果 | 对设计的影响 |
| --- | --- | --- |
| thinking 开关 | 请求体 `thinking: {type: "enabled"/"disabled"}`；**默认 enabled**，`disabled` = 非思考模式可用 | §5.1 参数落定：`thinking_type` per-phase |
| 思考深度 | `reasoning_effort: low / high / max`（默认 high；社区报告 low/medium 档可能被静默映射，有效档以 high/max 为主） | B-05 阶段映射：常规叫 low/disabled、应牌 high |
| 温度 | **思考模式下 temperature 被忽略（不报错）**；非思考模式官方推荐 1.0、低温度可能压塌推理链 | 温度矩阵仅对非思考档生效（§5.1 已修订）；评测锁定逻辑不变 |
| 退役名 | `deepseek-chat` / `deepseek-reasoner` 仍为退役口径 | `reject_legacy_names` 守门不变 |

**GLM（核对日 2026-11-13，来源：智谱官方文档深度思考/思考模式页、GLM-5.3 模型页、Z.AI 英文文档、腾讯云调用指南）**：

| 核对项 | 结果 | 对设计的影响 |
| --- | --- | --- |
| thinking.type | **GLM-5.3 / Flash / FlashX 强制思考：`{type: "disabled"}` 直接报错**；GLM-5.2 及更早仍支持 enabled/disabled | §5.3 已修订：5.3 系弃用 `thinking_type`，改 `reasoning_effort` |
| 思考深度 | `reasoning_effort: low / high / max`（默认 max） | B-05 映射：off/low→low、mid/high→high、auto→默认；"真关思考"不可达（已知降级） |
| Flash/FlashX 型号 ID | `glm-5.3-flash` / `glm-5.3-flashx`（腾讯云在售列表确认） | `use_flashx` 落定 |

---

## 6. 六家横向对比与默认角色分配

| 维度 | DeepSeek | MiMo | GLM | Qwen | 豆包 | MiniMax |
| --- | --- | --- | --- | --- | --- | --- |
| 旗舰强度 | 强（1.6T/49B） | 中上 | 强 | 强（2.4T/95B） | 强 | 强 |
| 快轨性价比 | 高 | 高 | **极高** | 高 | **极高**（Lite） | 高 |
| 上下文 | 1M | —— | 1M | 1M | 256K | 百万级 |
| 思考机制 | 分级 thinking | reasoning | type 开关 | 开关+**预算** | type 开关 | **交错思考** |
| 协议特例 | —— | **双协议** | —— | —— | 接入点制 | —— |
| 结构性优势 | 温度矩阵调优空间 | 自托管+Batch | 速度 | 台词+思考预算 | 台词+超低价 | **前缀缓存** |
| 默认角色 | EVE 评测主力 | 私有部署/批量 | 批量默认+PVE | PVE 主力+台词 | 台词+填充 | EVE 主力+长桌省钱 |

---

## 7. 配置文件规范（示意）

```toml
[player.ds_pro_1]
provider = "deepseek"
model    = "deepseek-v4-pro"
api_key_ref = "env:DEEPSEEK_API_KEY"        # 密钥永不落盘（B-08）

[persona]
name = "靓仔坤"
style = "粤语话痨，输咗都要笑住饮"
trash_talk = 2

[phases.bidding]
temperature = 0.9
thinking = "off"

[phases.respond]
temperature = 0.7
thinking = "high"                            # 反杀/投降抉择，思考拉满
```

每玩家一份配置；同一服务商可例化任意多玩家（不同人格/不同轨型号）。

---

## 8. 失败、纠错与降级（对接 02 §4.3）

| 层 | 重试 | 计数归属 |
| --- | --- | --- |
| 网络层（超时/5xx） | 指数退避 ×3 | 适配器内部，引擎不可见 |
| 解析层（JSON 坏/字段缺） | 内部重试 `self_check_retries` 次 | 附件 `parse_retries` |
| 自检层（动作非法） | 带原因重试 `self_check_retries` 次 | 附件 `self_check_retries`，**不耗引擎预算**（B-04） |
| 引擎驳回层 | 走引擎纠错预算（默认 2 次） | 引擎计数 |
| 全部失败 | 返回"决策失败"信号 | 引擎代打 + 降级标记（02 §4.3） |

---

## 9. 里程碑（细化 02 M4）

| 里程碑 | 交付 | 验收 |
| --- | --- | --- |
| M4a | AdapterSDK + DeepSeek、GLM 两家 | LLM 玩家 vs 脚本机器人完整桌局跑通；附件信封齐全；同配置重放一致 |
| M4b | 其余四家 + 台词人格包调校 | 六家同桌 EVE 局跑通；台词无注入逃逸（红队测试） |
| M4c | 批量接入 | Batch API（MiMo）与批量调度器打通；成本报表（成本面指标）产出 |

---

## 10. 未决事项

| 编号 | 事项 | 处置 |
| --- | --- | --- |
| N3-01 | §5.7 各家 thinking 字段的当期核对 | 每家实现前执行，核对结果回填本文 |
| N3-02 | 粤语台词质量与攻击等级的量化评测 | 05 文档（行为面） |
| N3-03 | Anthropic 协议 Transport 的优先级 | M4b 后按 MiMo 实测收益决定 |
| N3-04 | 模型线时效（六家迭代极快） | 型号 ID 全部走配置，不做硬编码；大版本更迭走配置变更而非代码变更 |

---

## 11. 参考来源（检索日 2026-11-10）

| 服务商 | 链接 |
| --- | --- |
| DeepSeek | [V4 官方公告](https://www.deepseek.com/en/news/v4-preview)、[API 变更日志](https://api-docs.deepseek.com/updates)、[V4 规格](https://www.morphllm.com/deepseek-v4) |
| MiMo | [MiMo-V2.6 发布](https://mimo.mi.com/docs/zh-CN/quick-start/summary/welcome)、[API 接入](https://mimo.mi.com/docs/zh-CN/quick-start/faq/api-integration)、[开放平台](https://platform.xiaomimimo.com)、[Pro/Flash 型号页](https://mimo.mi.com/models/zh-CN/mimo-v2.6-pro) |
| GLM | [开放平台](https://bigmodel.cn)、[模型概览](https://docs.bigmodel.cn/cn/guide/start/model-overview)、[发布记录](https://docs.bigmodel.cn/cn/update/new-releases) |
| Qwen | [Qwen3.8-Max 上线公告](https://www.aliyun.com/product/news/30083)、[百炼产品月刊 2026-02](https://developer.aliyun.com/article/1713938)、[Max/Plus/Flash 差异](https://developer.aliyun.com/article/1745443) |
| 豆包 | [Seed 2.1 发布报道](https://zhuanlan.zhihu.com/p/2053118530242065054)、[豆包 2.0 整理](https://www.53ai.com/news/LargeLanguageModel/2026021429065.html) |
| MiniMax | [M3.1-Flash 官方发布](https://www.minimax.io/blog/minimax-m31f)、[M3.1-Flash 模型卡](https://huggingface.co/MiniMaxAI/MiniMax-M3.1-Flash)、[API 文档](https://platform.minimax.io/docs/release-notes/models) |
