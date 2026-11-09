# 引擎设计（规则内核与对局编排）

| 项 | 值 |
| --- | --- |
| 文档类型 | 设计子文档（Engine / Rules Kernel） |
| 前置文档 | [`01-game-rules.md`](./01-game-rules.md) —— 规则事实源，本文所有语义以 `R-xx` 编号回指 |
| 项目 | llm-perudo |
| 状态 | v1.0 草案 —— 待业主评审 |
| 日期 | 2026-11-09 |
| 不含内容 | LLM 提示词与协议细节（属 `03`）、前端交互（属 `04`）、玩法扩展 |

---

## 0. 设计目标与边界

### 0.1 目标

llm-perudo 的主角是 **LLM 玩家**，不是人。这决定了架构的第一性约束：

> **规则内核必须先于提示词存在，且必须能被机器判定「什么是合法的」。**
> LLM 只能在一个**封闭、可枚举、可验证**的动作集里选；引擎负责证明该动作合法，LLM 负责选择它是否划算。

因此本设计的三条硬目标：

| 目标 | 含义 | 验收方式 |
| --- | --- | --- |
| G-1 确定性 | 同一初始状态 + 同一随机种子 ⇒ 同一事件流 | 回放一致性属性测试 |
| G-2 无副作用 | 内核是纯函数：不 IO、不读时钟、不用全局随机源 | 内核层禁止 import `os/time/random`（CI 静态检查） |
| G-3 可枚举 | 任意时刻某玩家的合法动作集可完整列出 | 合法动作集完备性属性测试 |

### 0.2 分层与依赖方向

```
┌──────────────────────────────────────────────────────────┐
│ L3 表现层    CLI / Web / 日志                             │  可有 IO
├──────────────────────────────────────────────────────────┤
│ L2 玩家接入层  LLM 玩家 / 人类玩家 / 脚本机器人            │  可有 IO
├──────────────────────────────────────────────────────────┤
│ L1 对局编排层  状态机 / 事件流 / 随机源 / 回放            │  仅通过注入的随机源
├──────────────────────────────────────────────────────────┤
│ L0 规则内核    合法性判定 / 计数 / 结算 —— 纯函数          │  零 IO、零随机
└──────────────────────────────────────────────────────────┘
              依赖方向严格向下，L0 不依赖任何上层
```

**为什么规则内核不放在 L1**：LLM 玩家要「读懂规则」，但更关键的是**引擎要在每次动作到达时独立复算合法性**。若合法性判定与状态推进混在一起，就无法保证「LLM 说什么引擎都验一遍」。分离后，`legal_actions()` 成为唯一权威，L2 只负责把动作翻译成结构化对象。

### 0.3 技术选型

| 项 | 选择 | 依据 |
| --- | --- | --- |
| 语言 | Python 3.12+ | 仓库 `.gitignore` 为标准 Python 模板（`__pycache__`、`*.egg-info`、uv/poetry/pdm/pixi、ruff、mypy、pytest、Django/Flask/Streamlit 全套），未出现 Node/Rust/Go 痕迹 |
| 包管理 | `uv` | `.gitignore` 含 `.pixi/`、`uv.lock` 注释与 PEP 582 段落 |
| 格式化 / 静态检查 | `ruff` + `mypy --strict` | `.gitignore` 含 `.ruff_cache/`、`.mypy_cache/` |
| 测试 | `pytest` + `hypothesis` | `.gitignore` 含 `.pytest_cache/`、`.hypothesis/` ⇒ 明确打算用属性测试 |
| 打包 | `pyproject.toml` + `src/` 布局 | `.gitignore` 含 `src/` 相关忽略与 `*.egg-info/` |

> 若业主另有既定技术栈，本节需重写；本文其余部分与语言无关（只约束**结构**，不约束**语法**）。

---

## 1. 核心数据模型

### 1.1 基础类型

```python
from dataclasses import dataclass
from enum import Enum
from typing import Literal

Face  = Literal[1, 2, 3, 4, 5, 6]
Dice  = tuple[Face, ...]          # 恒为长度 5（R-01）
PlayerId = str


class WildState(str, Enum):
    WILD = "wild"   # 1 为癞子，可代表任意面值（R-15）
    DEAD = "dead"   # 1 只按面值 1 计：斋 或 过 1（R-16）
```

> 用**单一枚举**而非「斋 / 飞 / 过 1」三态：`过 1` 与 `斋` 在规则上对骰子的影响完全相同（1 死），差别只在**能否飞回**——那由独立的布尔标记 `ones_called` 承担（见 §1.3）。这样状态空间从 3×2 降到 2×2，且每一条转移都有唯一语义。

### 1.2 叫骰动作

```python
class BidKind(str, Enum):
    PLAIN = "plain"   # 普通叫骰
    ZHAI  = "zhai"    # 叫斋 / 转斋：进入 DEAD（R-19、R-20）
    FEI   = "fei"     # 飞斋：回到 WILD（R-21）


@dataclass(frozen=True, slots=True)
class BidAction:
    quantity: int      # X
    face: Face         # Y
    kind: BidKind = BidKind.PLAIN
```

**状态转移解析**（唯一函数，禁止散落各处）：

```python
def resolve_wild(before: WildState, action: BidAction) -> WildState:
    if action.kind is BidKind.ZHAI:
        return WildState.DEAD
    if action.kind is BidKind.FEI:
        return WildState.WILD
    # PLAIN：叫出点数 1 ⇒ 过 1，1 死（R-22）；其余不改变状态
    return WildState.DEAD if action.face == 1 else before
```

### 1.3 回合状态

```python
@dataclass(frozen=True, slots=True)
class PlayerState:
    player_id: PlayerId
    hand: Dice                      # 引擎内部可见；对外经 PlayerView 过滤
    seat: int


@dataclass(frozen=True, slots=True)
class RoundState:
    round_no: int
    players: tuple[PlayerState, ...]
    wild: WildState
    ones_called: bool               # 本局是否有人叫过点数 1（R-22）
    bids: tuple[BidRecord, ...]      # 公开叫骰流水
    current: PlayerId
    phase: Phase
    stake: int                      # 1 码的量（R-46）
    options: RuleOptions            # 进阶层开关（R-06）
```

```python
@dataclass(frozen=True, slots=True)
class RuleOptions:
    leopard: bool = True        # 围骰/全骰加成（R-39~R-43）
    reroll_single: bool = True  # 散骰必重摇（R-09）
    double_leopard: bool = True # 豹子加倍（R-53）
    half_threshold: bool = True # 不够一半/超半加倍（R-54、R-55）
    double_failed_challenge: bool = True  # 跳杀失败加倍（R-56）
    drink_along: bool = False   # 陪饮（R-57）
```

### 1.4 阶段枚举

```python
class Phase(str, Enum):
    SHAKING   = "shaking"    # 摇骰 / 重摇判定（R-07~R-10）
    OPENING   = "opening"    # 起叫（R-11~R-14）
    BIDDING   = "bidding"    # 轮流叫骰（R-15~R-28）
    RESPOND   = "respond"    # 被开杀/跳杀者三选一（R-33~R-35）
    REVEAL    = "reveal"     # 开盰计数（R-37~R-45）
    SETTLE    = "settle"     # 结算码数（R-46~R-57）
```

---

## 2. 规则内核 API（L0）

### 2.1 设计原则

- 全部为**纯函数**：输入是不可变状态，输出是不可变结果。
- 不抛异常表达业务失败，一律返回布尔或结构化结果（`Legality`），便于 LLM 侧读取原因。
- 合法性判定**只此一份**，UI、CLI、LLM 校验一律调用同一函数。

### 2.2 合法性判定

```python
@dataclass(frozen=True, slots=True)
class Legality:
    ok: bool
    reason: str = ""          # 人类可读，也是 LLM 提示词的反馈源
```

```python
def legal_bid(state: RoundState, actor: PlayerId, action: BidAction) -> Legality:
    """判断一次叫骰是否合法。覆盖 R-11~R-23、R-45 的比较侧。"""
```

判定顺序（严格按此顺序，短路返回）：

1. **轮次检查**：`state.current == actor` 且 `state.phase is Phase.BIDDING`，否则拒绝。
2. **首叫 / 接叫分流**：`state.bids` 为空 ⇒ 走 **起叫下限**（§2.3）；否则走 **接叫比较**（§2.4）。
3. **过 1 副作用**：若 `action.face == 1`，调用方须同时置 `ones_called = True`（R-22）。

### 2.3 起叫下限（R-11 ~ R-14）

```python
import math

def open_bid_min(player_count: int, *, zhai: bool) -> int:
    if zhai:
        return player_count                # R-12
    return math.ceil(1.5 * player_count)   # R-11 / R-14（D-01 已裁决）
```

> 4 人局 ⇒ 飞 6 / 斋 4。`⌈1.5N⌉` 用 `math.ceil`，不要用 `round`（`round(7.5)=8` 靠运气，`round(6.5)=6` 靠银行家舍入）。

### 2.4 接叫比较（R-15 ~ R-21）

点数序用**由弱到强**的元组，索引越大越强：

```python
WEAK_TO_STRONG: dict[WildState, tuple[Face, ...]] = {
    WildState.WILD: (2, 3, 4, 5, 6, 1),   # R-15：1 为癞子，最强
    WildState.DEAD: (1, 2, 3, 4, 5, 6),   # R-16：1 最小
}

def face_rank(face: Face, wild: WildState) -> int:
    return WEAK_TO_STRONG[wild].index(face)
```

比较**一律使用动作生效前的状态**（01 §6.1 实现约定）：

```python
def legal_bid(state: RoundState, actor: PlayerId, action: BidAction) -> Legality:
    ...
    last = state.bids[-1]
    x0, y0 = last.quantity, last.face

    # ── 分支 A：飞斋（DEAD → WILD）R-21
    if action.kind is BidKind.FEI:
        if state.wild is not WildState.DEAD:
            return Legality(False, "当前不是斋，不能飞斋")
        if state.ones_called:
            return Legality(False, "本局已过 1，1 点不可复生（R-22/R-23）")
        if action.quantity < 2 * x0:
            return Legality(False, f"飞斋需数量翻倍：至少 {2 * x0} 个")
        return Legality(True)

    # ── 分支 B：转斋 / 叫斋（FLY → DEAD）R-19、R-20
    if action.kind is BidKind.ZHAI:
        if state.wild is WildState.DEAD:
            return Legality(False, "已经是斋")
        if action.quantity < x0:
            return Legality(False, f"转斋需数量不低于上家：{x0} 个")
        return Legality(True)

    # ── 分支 C：普通叫骰 R-17、R-18
    if action.quantity > x0:
        return Legality(True)                      # 数量优先，点数不受限
    if action.quantity < x0:
        return Legality(False, f"数量不得低于上家：{x0} 个")
    if face_rank(action.face, state.wild) > face_rank(y0, state.wild):
        return Legality(True)                      # 同数量，点数须更大
    return Legality(False, f"同数量时点数须大于上家的 {y0}")
```

> 关键点：`转斋`（分支 B）**放宽了点数约束**——只要 `X' ≥ X0` 即可，点数可以比上家小。这正是转斋存在的意义（不改数量就能改变计数结构）。
> `飞斋`（分支 A）数量翻倍 ⇒ `X' ≥ 2·X0 > X0`，点数天然自由，无需再比点数。

### 2.5 合法动作集枚举（G-3）

```python
def legal_actions(state: RoundState, actor: PlayerId) -> tuple[Action, ...]:
    """列出该玩家当前全部合法动作。LLM 玩家只在这个集合里选。"""
```

- 叫骰部分：数量取 `range(min_qty, 5 * player_count + 3)`，点数 1–6，`kind` 三选一，再逐个过 `legal_bid` 过滤。
- 动作量级：4 人局约 `(22−2) × 6 × 3 ≈ 360` 个候选，过滤后不足百级 —— **完全可枚举**，可以整体塞进 LLM 上下文。
- `开杀 / 跳杀 / 连杀 / 投降` 按 01 §7 的邻接关系与阶段加入。

> **设计取舍**：不采用「只给合法动作、不给非法原因」的做法。`Legality.reason` 直接复用为 LLM 的纠错反馈（见 `03`），能显著降低重试率。

### 2.6 计数与判定（R-37 ~ R-45）

```python
def count_face(hands: Sequence[Dice], face: Face, wild: WildState,
               *, leopard: bool = True) -> int:
    """全场上符合被叫点数的骰子总数。"""
    return sum(_hand_contribution(h, face, wild, leopard) for h in hands)


def _hand_contribution(hand: Dice, face: Face, wild: WildState, leopard: bool) -> int:
    if wild is WildState.DEAD:
        return sum(1 for d in hand if d == face)          # R-38

    n_one = sum(1 for d in hand if d == 1)
    if face == 1:
        base = n_one                                       # R-37 + D-02（字面计数）
    else:
        base = sum(1 for d in hand if d == face) + n_one   # R-37

    if not leopard:
        return base                                        # R-44
    return base + _leopard_bonus(hand, face)               # R-39 ~ R-43


def _leopard_bonus(hand: Dice, face: Face) -> int:
    """围骰 +1 / 全骰 +2；仅当整手可归为被叫面值时才生效。"""
    faces = set(hand)
    if not faces <= {face, 1}:
        return 0                    # R-42：加成只作用于被叫面值
    if len(faces) == 1:
        return 2                    # R-40：全骰（含 5 个 1）
    return 1                        # R-39：围骰
```

**校验**：该实现必须复现 01 §8.4 的整张示例表。

| 局面（FLY，被叫 4） | base | bonus | 贡献 |
| --- | --- | --- | --- |
| 4,4,4,4,1 | 4 + 1 = 5 | 围骰 +1 | **6** |
| 4,4,4,4,4 | 5 | 全骰 +2 | **7** |
| 1,1,1,1,1 | 0 + 5 = 5 | 全骰 +2 | **7** |
| 4,4,4,2,1 | 3 + 1 = 4 | 不适用（{4,2,1} ⊄ {4,1}） | **4** |
| 2,3,5,6,1 | 0 + 1 = 1 | 不适用 | **1** |

### 2.7 结算（R-45 ~ R-57）

```python
@dataclass(frozen=True, slots=True)
class Settlement:
    winner: PlayerId
    loser: PlayerId
    multiplier: int
    stake: int                  # 实际受罚码数
    count: int                  # 场上实际点数
    bid_holds: bool             # count >= X ⇒ 叫骰成立（R-45）
    reason: str
```

判定主线（R-45）：

```
count >= bid.quantity  ⇒  叫骰成立  ⇒  开杀/开骰的一方输
count <  bid.quantity  ⇒  叫骰不成立 ⇒  被开杀/被跳杀的一方输
```

倍数叠加顺序（R-47 ~ R-56）：

```
base          = 1
if 跳杀:      base *= 2                 # R-48
if 反杀:      base *= 2                 # R-49（4 倍）
if 连杀且赢≥3: base *= 2                # R-50
if 豹子加倍命中: base *= 2              # R-53
if 不够一半 / 超半命中: base *= 2        # R-54、R-55
if 跳杀失败:  base *= 2                 # R-56
if 投降:      base = max(1, base // 2)  # R-52
stake = base * 1码                     # R-46
```

> `投降` 的减半取整：广东原文只说"码数减半"。本设计取**向下取整且不低于 1 码**，理由是「喝 0 码」等于免罚，会让投降变成比认输更优的选项。若业主另有口径，改这一行即可。

---

## 3. 对局编排层（L1）

### 3.1 状态机

```
        ┌─────────┐
        │ SHAKING │◄────────────────────────────┐
        └────┬────┘                             │
     叠骰/散骰重摇                              │ 下一局
             ▼                                   │
        ┌─────────┐                             │
        │ OPENING │  首叫（受 R-11~R-14 约束）    │
        └────┬────┘                             │
             ▼                                   │
        ┌─────────┐   叫骰 / 转斋 / 飞斋          │
        │ BIDDING │◄──────────────┐             │
        └────┬────┘               │             │
             │ 开杀/跳杀            │ 继续叫       │
             ▼                    │             │
        ┌─────────┐               │             │
        │ RESPOND │───────────────┘             │
        └────┬────┘                             │
   开盰/反杀/投降                                │
             ▼                                   │
        ┌─────────┐                             │
        │ REVEAL  │  计数（R-37~R-43）            │
        └────┬────┘                             │
             ▼                                   │
        ┌─────────┐                             │
        │ SETTLE  │─────────────────────────────┘
        └─────────┘
```

### 3.2 事件流（轻量 Event Sourcing）

事件是引擎对外**唯一**的叙述方式；UI 与 LLM 提示词都由事件流渲染而成。

| 事件 | 载荷 | 公开性 |
| --- | --- | --- |
| `RoundStarted` | `round_no, seed, player_count, options` | 公开 |
| `HandShaken` | `player, dice` | **私密**（公开视图须剔除） |
| `Rerolled` | `player, reason` | 公开 |
| `BidMade` | `player, quantity, face, kind` | 公开 |
| `Called` | `challenger, target` | 公开 |
| `Challenged` | `challenger, target, multiplier` | 公开 |
| `Countered` | `player, multiplier` | 公开 |
| `Surrendered` | `player, multiplier` | 公开 |
| `Revealed` | `hands` | 公开 |
| `RoundSettled` | `settlement` | 公开 |

**信息墙的实现纪律**（G-2 的延伸，也是本项目最容易出安全事故的地方）：

1. 引擎内部持有真实手牌；**只有** `PlayerView` 决定谁能看到什么。
2. `HandShaken` 携带真骰，但进入 LLM 上下文前必须经过 `to_public_view()` 过滤；**过滤发生在序列化层，不靠调用方自觉**。
3. 增加 CI 静态检查：公开事件流中不得出现 `HandShaken`；LLM 请求体中不得出现非本人的 `dice` 字段。

### 3.3 随机性（G-1）

- 全局**唯一** `random.Random` 实例，由 `RoundStarted.seed` 构造，随机源注入状态机。
- 摇骰一律经 `rng.roll(5)`；**内核层禁止 `import random`**（CI 检查），杜绝不可复现的随机。
- 回放：`seed + 玩家动作序列 ⇒ 完全相同的骰面与事件流`。
- 种子写入 `RoundStarted` 并公开给复盘工具，但**不公开给玩家**（防止玩家反推骰子）。

### 3.4 玩家接入层（L2）协议

```python
class Player(Protocol):
    async def on_turn(self, view: PlayerView) -> Action: ...
    async def on_respond(self, view: PlayerView) -> Action: ...
```

```python
@dataclass(frozen=True, slots=True)
class PlayerView:
    player_id: PlayerId
    round_no: int
    my_hand: Dice                    # 只有自己的
    public_bids: tuple[BidRecord, ...]
    wild: WildState
    ones_called: bool
    legal_actions: tuple[Action, ...]  # 唯一权威的合法动作集
    last_settlement: Settlement | None
```

> `PlayerView` **不含**他人手牌、不含随机种子、不含 `HandShaken` 原始事件。构造 `PlayerView` 的代码只允许出现在 `engine/views.py` 一处。

---

## 4. 可测性设计

### 4.1 规则追溯矩阵

`docs/design/01-game-rules.md` 的每条 `R-xx` 至少对应一条测试，映射表放在 `tests/README.md`，CI 检查**无孤儿规则**（有规则无测试 ⇒ 失败）。

### 4.2 属性测试（Hypothesis）

| 编号 | 不变量 | 对应 |
| --- | --- | --- |
| P-1 | `count_face` 对骰子集合单调：加入骰子不使计数减少 | R-37 ~ R-43 |
| P-2 | `settle` 的胜负判定恒等于 `count >= quantity` | R-45 |
| P-3 | 状态机不变式：`wild` 与 `ones_called` 的取值组合恒合法；`ones_called` 为真时 `wild` 必为 `DEAD` | R-22、R-23 |
| P-4 | 合法性自洽：任意合法叫骰动作执行后，新状态仍满足 P-3 | R-17 ~ R-23 |
| P-5 | 随机对局 fuzz 10000 局不抛异常、不出现非法状态 | 全局 |
| P-6 | 回放一致性：同 seed + 同动作序列 ⇒ 事件流逐字段相等 | G-1 |
| P-7 | 围骰/全骰加成只在该手可归为被叫面值时生效 | R-42 |

### 4.3 变异测试门禁（防「无牙测试」）

**每条关键断言必须配至少一条变异**：故意把内核改成非法行为（例：把 `quantity < 2 * x0` 的飞斋门槛去掉、把围骰 +1 改成 +2、把 `count >= quantity` 反转），对应测试**必须变红**。红不出来的测试视为无效门禁。

> 这一条是本设计的硬性要求：规则内核的正确性完全依赖测试，而「测试通过」若来自「断言根本碰不到被测分支」，等于没测。

### 4.4 CI 门禁

| 门禁 | 内容 |
| --- | --- |
| G-静态 | `mypy --strict` 通过；`ruff` 无告警 |
| G-纯净 | 内核层（`src/perudo/core/`）import 检查：禁止 `os`/`sys`/`time`/`random`/`socket`/`http` |
| G-覆盖 | `pytest` 全绿；核心模块行覆盖 ≥ 95%，分支覆盖 ≥ 90% |
| G-孤儿 | 规则追溯矩阵无孤儿 |
| G-变异 | 变异测试集全红（故意改坏必被捕获） |

---

## 5. 目录结构建议

```
llm-perudo/
├─ pyproject.toml
├─ README.md
├─ docs/
│  └─ design/
│     ├─ 01-game-rules.md      # 规则事实源（已完成）
│     ├─ 02-engine-design.md   # 本文
│     ├─ 03-llm-player.md      # LLM 接入契约（待写）
│     └─ 04-frontend.md        # 表现层（待写）
├─ src/perudo/
│  ├─ core/                    # L0：纯函数，零 IO
│  │  ├─ types.py              # Face/Dice/BidAction/RoundState/…
│  │  ├─ rules.py              # 起叫下限、点数序
│  │  ├─ bids.py               # legal_bid / legal_actions
│  │  ├─ count.py              # count_face / 围骰全骰
│  │  ├─ settle.py             # 判定与倍数
│  │  └─ __init__.py
│  ├─ engine/                  # L1
│  │  ├─ machine.py            # 状态机
│  │  ├─ events.py             # 事件类型
│  │  ├─ rng.py                # 随机源注入
│  │  ├─ views.py              # PlayerView 构造（唯一出口）
│  │  └─ replay.py             # 回放
│  ├─ players/                 # L2
│  │  ├─ base.py               # Player 协议
│  │  ├─ llm.py                # LLM 玩家（依赖 03 文档）
│  │  ├─ human.py
│  │  └─ scripted.py           # 脚本机器人：用于批量模拟与回归
│  └─ cli.py                   # L3
└─ tests/
   ├─ README.md                # 规则追溯矩阵
   ├─ test_core_*.py
   ├─ properties/
   │  └─ test_invariants.py
   ├─ mutations/               # 变异测试集
   └─ traces/                  # 回放夹具（seed + 动作序列）
```

---

## 6. 里程碑

| 编号 | 里程碑 | 交付 | 完成判据 |
| --- | --- | --- | --- |
| M1 | 规则内核 | `core/` + 单测 + 属性测试 | P-1~P-7 全绿；R-xx 无孤儿；变异集全红 |
| M2 | 引擎与 CLI | `engine/` + `cli.py` + 脚本机器人 | CLI 能跑完整局并打印事件流；回放一致（P-6） |
| M3 | LLM 接入 | `players/llm.py` | 依 `03` 文档实现；LLM 只经 `PlayerView` 获取信息 |
| M4 | 表现层 | Web/前端 | 依 `04` 文档；仅经事件流渲染 |
| M5 | 平衡与复盘 | 批量模拟 + 回放工具 | 能出「各点数胜率」「过 1 实际使用率」等统计 |

### 6.1 M2 附带的验证任务（重要）

D-02 裁决（"N 个 1"按字面计数）有一个**已知的、可测的后果**：`过 1` 在飞状态下几乎无法靠"N 个 1"兑现，其真实价值退化为"掐掉全桌癞子"。这是裁决人知悉并接受的代价，但需要用数据确认它**没有让"过 1"变成完全的废招**。

M2 完成后，用脚本机器人跑 10000 局，产出三项统计：

1. 「过 1」在全部叫骰中的占比；
2. 过 1 之后的叫骰胜率（对照未过 1）；
3. 若把 D-02 换成"任意面值取最大"口径重跑一遍，对比上述两项。

⇒ **结论不是要推翻裁决，而是把它写成"已知特性"写回 `01-game-rules.md`**，让后续 AI 玩家与人类玩家都知道这个代价的存在。

---

## 7. 风险与未决事项

| 编号 | 事项 | 影响 | 处置 |
| --- | --- | --- | --- |
| N-01 | D-02 裁决使「过 1」近似废招 | 中 | M2 后用统计数据复核（§6.1），必要时业主改判 |
| N-02 | 人数 > 6 时 `⌈1.5N⌉` 起叫过猛，AI 容易被逼死 | 中 | M2 统计各人数的胜率分布；必要时在 §10 增补「人数上限」裁决项 |
| N-03 | LLM 上下文预算：合法动作集 4 人局近 360 条 | 中 | `03` 需定「全量给 / 压缩给 / 采样给」策略；内核接口不变，只影响渲染层 |
| N-04 | 技术栈依据是 `.gitignore` 推断，非业主明示 | 低 | 若与业主预期不符，本文除 §0.3 外均可复用，只需重写类型定义部分 |
| N-05 | 围骰/全骰在 6 人以上局占比高，加成影响大 | 低 | M2 统计各点数贡献分布 |

---

## 8. 与其他设计文档的接口

| 文档 | 依赖本文的什么 | 本文依赖它的什么 |
| --- | --- | --- |
| `01-game-rules.md` | `R-xx` 规则编号与语义 | —— |
| `03-llm-player.md`（待写） | `PlayerView` 字段、`legal_actions()`、`Legality.reason` | `PlayerView` 的字段构成、`Action` 类型集合 |
| `04-frontend.md`（待写） | 事件流类型（§3.2） | —— |
| `05-balance.md`（待写） | 批量模拟入口 | 统计口径定义 |

> **接口稳定性承诺**：`03` 文档落地前，`core/` 的**函数签名**视为稳定；`PlayerView` 的**字段可增不可删**，新增字段须向后兼容。
