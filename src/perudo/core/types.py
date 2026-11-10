"""规则内核共享类型（L0，02 §3）。

硬约束（02 §1.3）：零第三方依赖、零 IO、零随机 —— 全部类型为纯标准库的
不可变值对象，供合法性判定 / 计数判定 / 结算三件套共用。

规则事实源：``docs/design/01-game-rules.md``（R-xx / T-xx / D-xx）；
架构红线：``docs/design/02-engine-design.md`` §3.2（状态模型 2×2、双轨点数序、
"N 个 1"字面计数）。
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from enum import Enum, IntEnum
from fractions import Fraction

__all__ = [
    "ALL_FACES",
    "Bid",
    "BidAction",
    "BidCapPolicy",
    "BidKind",
    "CallState",
    "ChallengeKind",
    "Direction",
    "DrinkAlongResult",
    "Face",
    "Hand",
    "LoserEntry",
    "LoserSide",
    "LegalityVerdict",
    "ResponseKind",
    "RerollReason",
    "RuleConfig",
    "ScatteredPolicy",
    "StakeContext",
    "StraightPolicy",
    "ZhaiState",
    "bid_count_cap",
    "total_dice",
    "validate_player_count",
]

# ---------------------------------------------------------------------------
# 骰面与手牌（R-01 / R-07）
# ---------------------------------------------------------------------------


class Face(IntEnum):
    """骰面点数 1–6（T-02）。"""

    ONE = 1
    TWO = 2
    THREE = 3
    FOUR = 4
    FIVE = 5
    SIX = 6


#: 全部合法骰面（供穷举与校验使用）
ALL_FACES: tuple[Face, ...] = (Face.ONE, Face.TWO, Face.THREE, Face.FOUR, Face.FIVE, Face.SIX)


@dataclass(frozen=True)
class Hand:
    """一名玩家的扣置手牌：恰好 5 颗六面骰（R-01）。

    "扣在骰盅下、只允许自己查看"（R-07）是信息隔离纪律，由 P2 编排层的视图
    机制落实；本类型只承载牌面事实。
    """

    dice: tuple[Face, ...]

    def __post_init__(self) -> None:
        if len(self.dice) != 5:
            raise ValueError(f"一手必须恰为 5 颗骰（R-01），收到 {len(self.dice)} 颗")


# ---------------------------------------------------------------------------
# 叫骰状态模型（02 §3.2 红线一：2×2，不做第三状态）
# ---------------------------------------------------------------------------


class ZhaiState(Enum):
    """斋状态（2×2 之第一轴）：1 点是否作癞子（R-19）。"""

    FLY = "fly"  # 飞：1 为癞子，可代表任意面值
    DEAD = "dead"  # 斋 / 过 1：1 只按面值 1 计


@dataclass(frozen=True)
class CallState:
    """一局内的全局叫骰状态：2×2 = {FLY, DEAD} × {是否过 1}（R-19~R-23）。

    不变式：``ones_called`` 为真 ⇒ ``zhai`` 必为 DEAD（R-22：过 1 后 1 永久
    不作癞子，不可飞回）。非法组合在构造时即被拒绝。
    """

    zhai: ZhaiState
    ones_called: bool

    def __post_init__(self) -> None:
        if self.ones_called and self.zhai is not ZhaiState.DEAD:
            raise ValueError("ones_called=True 时状态必为 DEAD（R-22 过 1 不可逆）")

    @classmethod
    def initial(cls) -> CallState:
        """开局初始态：飞、未过 1（01 §6.4 状态表）。"""
        return cls(ZhaiState.FLY, False)

    def to_dead(self, *, ones_called: bool | None = None) -> CallState:
        """转 DEAD（转斋或过 1）；``ones_called`` 缺省沿用当前值。"""
        called = self.ones_called if ones_called is None else ones_called
        return CallState(ZhaiState.DEAD, called)

    def to_fly(self) -> CallState:
        """转 FLY（飞斋）。过 1 的局不可达 —— 构造器会拒绝 (FLY, True)。"""
        return CallState(ZhaiState.FLY, False)


# ---------------------------------------------------------------------------
# 动作类型（02 §4.1：叫骰类 / 杀类 / 应牌类）
# ---------------------------------------------------------------------------


class BidKind(Enum):
    """叫骰动作类型（02 §4.1：普通 / 转斋 / 飞斋）。

    首叫用 ``NORMAL``（非斋首叫）或 ``ZHAI``（斋首叫，01 §14.1 前两行）；
    ``FEI`` 仅在 DEAD 状态合法（飞斋）。
    """

    NORMAL = "normal"  # 常规接叫 / 非斋首叫
    ZHAI = "zhai"  # 转斋（FLY→DEAD）/ 斋首叫
    FEI = "fei"  # 飞斋（DEAD→FLY）


@dataclass(frozen=True)
class Bid:
    """一个叫骰：宣称全场至少有 ``count`` 个 ``face`` 点（T-03）。"""

    count: int
    face: Face


@dataclass(frozen=True)
class BidAction:
    """叫骰动作 = 叫法 + 叫骰。"""

    kind: BidKind
    bid: Bid


class ChallengeKind(Enum):
    """杀类动作（R-29~R-32）。连杀 / 通杀属开杀型（多目标分别结算，R-51）。"""

    OPEN = "open"  # 开杀：相邻上家
    JUMP = "jump"  # 跳杀（劈）：非相邻
    MULTI = "multi"  # 连杀：相邻多位（≥2）
    SWEEP = "sweep"  # 通杀：除自己外全部


class ResponseKind(Enum):
    """应牌三选一（R-33）：开盅清点 / 反杀 / 投降。"""

    REVEAL = "reveal"
    COUNTER = "counter"
    SURRENDER = "surrender"


class Direction(Enum):
    """行动方向（R-04 基线顺时针；逆时针为 §12 第 15 项变体）。"""

    CLOCKWISE = "clockwise"
    COUNTER_CLOCKWISE = "counter_clockwise"


# ---------------------------------------------------------------------------
# 桌面合法性判定结果
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LegalityVerdict:
    """合法性判定结果（02 §3.1：合法 / 不合法 + 人类可读原因）。

    ``reason`` 在非法时必须非空 —— 它同时是玩家纠错的依据（02 §4.3）。
    """

    legal: bool
    reason: str = ""

    @classmethod
    def ok(cls) -> LegalityVerdict:
        return cls(True)

    @classmethod
    def reject(cls, reason: str) -> LegalityVerdict:
        if not reason:
            raise ValueError("非法判定的 reason 不得为空（02 §3.1 / 计划 §4.2）")
        return cls(False, reason)


class RerollReason(Enum):
    """重摇原因（R-08 / R-09 / R-60）。

    顺色是散骰的特例（R-60），判定时优先报告更具体的原因。
    """

    STACKED = "stacked"  # 叠骰（R-08；数字桌面不会出现，规则位保留 —— 02 §2.4.1）
    SCATTERED = "scattered"  # 散骰：5 颗点数各不相同（R-09）
    STRAIGHT = "straight"  # 顺色：12345 / 23456（R-60）


# ---------------------------------------------------------------------------
# 开桌前约定（01 §12 十八项 —— 每一行都是开关；基线默认值）
# ---------------------------------------------------------------------------


class ScatteredPolicy(Enum):
    """散骰处理（R-09 / §12 第 4 项）。"""

    RESHAKE = "reshake"  # 基线：散骰必须重摇
    COUNT_ZERO = "count_zero"  # 变体①：不重摇，散骰计 0 个
    NORMAL = "normal"  # 变体②：不重摇，照常计色


class StraightPolicy(Enum):
    """顺色处理（R-60 / R-61 / §12 第 2–3 项）。"""

    RESHAKE = "reshake"  # 基线：顺色必重摇（基线下顺色不进入计数）
    COUNT_ZERO = "count_zero"  # 局前变体①：不重摇，顺色计 0 个
    NORMAL = "normal"  # 局前变体②：不重摇，照常计色


class BidCapPolicy(Enum):
    """叫骰数量上限口径（R-64 / §12 第 17 项）。"""

    FIVE_N = "five_n"  # 基线：不超过在场骰子总数 5N
    FIVE_N_MINUS_ONE = "five_n_minus_one"  # 变体：5N−1
    UNLIMITED = "unlimited"  # 不限


@dataclass(frozen=True)
class RuleConfig:
    """开桌前约定清单（01 §12 十八项全部入列，缺省值 = 基线默认）。

    配置在桌局创建时冻结（02 §6 / A-12）；本类型只承载规则开关，桌局参数
    （终局阈值、max_rounds 等）属 P2 编排层。
    """

    # ① 1 码 = 多少（仅显示换算，不进积分 —— 02 A-04）
    stake_label: str = "1 份"
    # ②③ 顺色是否重摇 / 若不重摇怎么算（R-60 / R-61）
    straight: StraightPolicy = StraightPolicy.RESHAKE
    # ④ 散骰怎么处理（R-09）
    scattered: ScatteredPolicy = ScatteredPolicy.RESHAKE
    # ⑤ 围骰、全骰是否加成（R-39 / R-40；False = R-44「有骰计骰」变体）
    leopard_bonus: bool = True
    # ⑥ 5 个 1（"全红"）算 8 个（R-62 局前变体；基线 False = 7 个）
    all_ones_eight: bool = False
    # ⑦ 围骰/全骰持有者输是否加倍（R-53 豹子加倍）
    leopard_double: bool = True
    # ⑧ 够不够一半是否加倍（R-54 / R-55，开杀链）
    half_double: bool = True
    # ⑨ 跳杀失败是否加倍（R-56，跳杀链）
    jump_fail_double: bool = True
    # ⑩ 反杀是否可用于普通开杀（基线否 —— R-34；True = §10 D-04 变体）
    counter_on_open: bool = False
    # ⑪ 连杀连赢几家翻倍（R-50；None = 不翻）
    multi_win_double_threshold: int | None = 3
    # ⑫ 投降怎么算（R-52；True = 减半且保底 1 码，False = 减半向下取整可 0）
    surrender_floor_one: bool = True
    # ⑬ 是否玩「天黑黑」（R-63，默认不玩）
    darkness: bool = False
    # ⑭ 是否玩陪饮（R-57，默认不玩）
    drink_along: bool = False
    # ⑮ 行动方向（R-04）
    direction: Direction = Direction.CLOCKWISE
    # ⑯ 玩家人数上限（R-02：允许 2–12，基线 6）
    player_cap: int = 6
    # ⑰ 叫骰数量上限（R-64）
    bid_cap: BidCapPolicy = BidCapPolicy.FIVE_N
    # ⑱ 重摇次数上限（R-65；None = 不限）
    reroll_limit: int | None = 3


# ---------------------------------------------------------------------------
# 桌面事实的派生量
# ---------------------------------------------------------------------------


def total_dice(player_count: int) -> int:
    """全场总骰数 = 5N（R-03）。"""
    return 5 * player_count


def validate_player_count(player_count: int, cfg: RuleConfig) -> None:
    """校验人数（R-02）：允许 2–12 人，基线上限由 §12 第 16 项配置。"""
    cap = min(cfg.player_cap, 12)
    if not 2 <= player_count <= cap:
        raise ValueError(f"人数 {player_count} 越界：允许 2–{cap} 人（R-02 / §12 第 16 项）")


def bid_count_cap(player_count: int, cfg: RuleConfig) -> int | None:
    """叫骰数量上限（R-64 / §12 第 17 项）；``None`` 表示不限。"""
    match cfg.bid_cap:
        case BidCapPolicy.FIVE_N:
            return total_dice(player_count)
        case BidCapPolicy.FIVE_N_MINUS_ONE:
            return total_dice(player_count) - 1
        case BidCapPolicy.UNLIMITED:
            return None


def rule_config_field_names() -> frozenset[str]:
    """``RuleConfig`` 的字段名集合（守护性测试用：证明基线无变体玩法支撑）。"""
    return frozenset(f.name for f in fields(RuleConfig))


# ---------------------------------------------------------------------------
# 结算（R-45 ~ R-57；02 §3.1 输出：逐输家的码数与倍数明细）
# ---------------------------------------------------------------------------


class LoserSide(Enum):
    """输家在挑战对决中的角色（进阶加倍的严格名词分工依据 —— 计划 §8 D-04）。"""

    CHALLENGER = "challenger"  # 杀者（开杀/跳杀/反杀的发起侧）
    CHALLENGED = "challenged"  # 被杀者侧（被开杀者/被跳杀者/反杀者）


@dataclass(frozen=True)
class StakeContext:
    """单个输家的结算上下文（应牌链落定后的原子事实，由 P2 编排层组装）。

    一局可以产生多个输家（02 §3.3），每个输家对应一个 ``StakeContext``；
    多目标挑战（连杀 / 通杀）分别结算（R-51），逐目标各出一个上下文。

    ``base_multiplier`` 为链上升级后的基础倍数：开杀 ×1、跳杀 ×2、反杀 ×4、
    再反杀 ×8（01 §14.2 / 02 §3.3）；连杀连赢达标的 ×2（R-50）由编排层在
    组装时乘入（开关判定见 ``settlement.multi_kill_double``）。
    """

    loser: int
    side: LoserSide
    chain: ChallengeKind  # 该输家所在对决的挑战类型（连杀/通杀归 OPEN —— D-04 裁决）
    base_multiplier: Fraction
    bid: Bid  # 被挑战的叫骰
    #: 开盅判定结果：True=叫骰成立；False=不成立；None=投降（未开盅）
    bid_stood: bool | None
    #: 开盅后全场 count（按当前状态口径）；投降为 None
    count: int | None
    #: 输家为被杀者侧且其手牌对被叫面值构成围骰/全骰（R-53）；其余为 False
    loser_holds_leopard: bool = False


@dataclass(frozen=True)
class LoserEntry:
    """逐输家结算明细（02 §3.1）：码数（=积分，A-04 整数）与倍数明细。

    ``breakdown`` 按乘法顺序记录各因子：``("base", 2)``、``("advance:R-56", 2)``
    等；全部因子之积 = ``multiplier``，码数 = 基数 1 码 × multiplier（投降另见
    R-52 的减半与保底）。
    """

    player: int
    codes: int
    multiplier: Fraction
    breakdown: tuple[tuple[str, Fraction], ...]


@dataclass(frozen=True)
class DrinkAlongResult:
    """陪饮结算（R-57）：同罚对象与是否「摇中自己」。"""

    buddy: int
    #: 摇中自己 → 陪饮者再多喝一倍（R-57）
    self_hit: bool
