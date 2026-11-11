# 规则追溯矩阵（R-xx ↔ 测试 ID）

| 项 | 值 |
| --- | --- |
| 文档类型 | 追溯矩阵（Traceability Matrix） |
| 依据 | `docs/design/01-game-rules.md`（规则事实源，R-01~R-68）；`docs/plan/01-build-plan.md` §4.1（矩阵要求）与 §1 交付总览「R-xx 追溯无孤儿」 |
| 项目 | llm-perudo |
| 状态 | **P1 已填充（2026-11-11）—— 68 条规则全部 `covered`，孤儿数 0** |
| 日期 | 2026-11-10 |
| 不含内容 | 规则正文（见 `docs/design/01-game-rules.md`）、测试实现代码、CI 配置（`.github/` 由其它环节维护） |
| 机器检查 | `uv run python scripts/check_traceability.py`（详见 §3） |

---

## 0. 格式契约

> 本节是本文件的**使用契约**。P1 及以后任何 agent 改动本矩阵前，必须先读本节。
> 矩阵的**唯一目的**：让「一条规则」与「一个能跑的测试」之间不存在断链。

### 0.1 每一列的含义

| 列 | 含义 | 填写者 | 约束 |
| --- | --- | --- | --- |
| 规则 ID | 规则编号，形如 `R-12` | P0 已填 | 必须与 `01-game-rules.md` 中的编号**逐字一致**；非法格式会让检查器 exit 2 |
| 规则摘要 | 一句中文概括，说明这条规则要求什么 | P0 已填 | 只写要点，不抄原文；读者不必翻设计稿即可判断测试是否对题 |
| 规则出处 | 该规则在 `01-game-rules.md` 中的**章节定位**（如 `01 §4.2`、`01 §13 第 3 例`） | P0 已填 | 精确到小节；散落在正文而非独立条款的规则写「散见 §x.x」 |
| 测试 ID | 覆盖该规则的测试标识 | **P1 填充** | 至少一个；命名约定见 §0.3；无测试时填 `—` |
| 状态 | 该行当前的追溯状态 | **P1 维护** | 只能是 `pending` 或 `covered`，其它取值让检查器 exit 2 |
| 备注 | 补充信息（变体标记、基线是否实现、特殊说明） | P1 维护 | 自由文本，留空亦可 |

### 0.2 怎么读（读者路径）

1. 拿到一个规则编号 `R-xx`（例如实现时需要确认「起叫下限」怎么算）。
2. 在本文件 §1 找到对应行，读「规则摘要」快速判断该规则讲什么。
3. 读「规则出处」跳回 `docs/design/01-game-rules.md` 的对应章节看原文与依据。
4. 读「测试 ID」找到测试位置；该测试就是这条规则的**可执行判据**。
5. 若「测试 ID」为 `—` ⇒ 该规则**尚无测试保护**（P1 补齐前不得视为已实现）。

反向亦成立：拿到一个测试文件，可以在 §1 里反查它保护了哪些规则。

### 0.3 怎么改（P1 填充指引）

**P1 只需改三列**：`测试 ID`、`状态`、`备注`。「规则 ID」「规则摘要」「规则出处」三列由 P0 依据设计稿写定，P1 不得改动（若发现摘要与设计稿冲突，**改设计稿或提 issue，不要改矩阵**）。

**测试 ID 命名约定（写死，P1 起一律遵守）：**

> **测试 ID = pytest node id**，形如
> `tests/unit/test_<模块>.py::test_<函数名>`
> 一条规则需要多个测试时，在同一单元格内用 `;` 分隔（分号两侧可有空格）：
> `tests/unit/test_counting.py::test_fly_count_includes_wild; tests/unit/test_counting.py::test_wild_leopard_bonus`

细则：

- `<模块>` 取规则所属领域，取值限定为：`table`（人数/道具/顺色/重摇）、`bidding`（起叫/叫骰/点数序/斋飞）、`counting`（计数/围骰全骰）、`judging`（判定）、`settling`（码数/惩罚）、`scenario`（§13 三例对账）。
- node id 中的路径必须**真实存在**，且能由 `uv run pytest --collect-only -q` 收集到；不得写尚不存在的文件。
- 同一条规则允许多个 node id，但**不得**把与本规则无关的测试塞进来凑数。

### 0.4 新增条目守什么

新增一条规则（设计稿新增 `R-xx`）时，必须同时做完下面四件事，缺一不可：

1. 在 `docs/design/01-game-rules.md` 中为该规则落一条**可引用的条款**（独立条款号或明确的正文归属），并写明依据；
2. 在本文件 §1 **新增一行**，填好「规则 ID / 规则摘要 / 规则出处」三列；
3. 写一个能证伪该规则的测试，并在该行填「测试 ID」，同时把「状态」置为 `covered`；
4. 运行 `uv run python scripts/check_traceability.py`，必须 exit 0（孤儿数为 0）。

反向对称：**删除**一条规则时，同样要删掉本文件对应的行，并确认检查器仍通过。

### 0.5 状态标记语义

| 状态 | 含义 | 判定依据 |
| --- | --- | --- |
| `pending` | 该规则**尚无**测试保护，等待 P1/P2 填充 | 「测试 ID」列为 `—` 或空 |
| `covered` | 该规则**已有**至少一个测试保护 | 「测试 ID」列已填，且 node id 真实存在 |

状态与「测试 ID」必须一致：`covered` ⇒ 测试 ID 非空；`pending` ⇒ 测试 ID 为空。检查器只强检「测试 ID 非空」这一侧（孤儿判定所必需），不一致的一侧由人工与 code review 兜住。

### 0.6 矩阵启用条件（关键）

- **全部行都是 `pending`** ⇒ 矩阵视为「**尚未启用**」。此时检查器**通过**（exit 0）并打印「矩阵尚未启用（P1 待填充）」提示。理由：P0 还没有内核代码，测试尚不存在，此时把 CI 打红没有意义。
- **出现任意一条 `covered` 行** ⇒ 矩阵**立即启用**，孤儿检查即刻生效：此时任何「测试 ID」为空的规则行都算**孤儿**，CI 变红（exit 1）。
- 启用是**单向棘轮**：一旦有第一条 `covered`，就不能再靠「全部 pending」把检查绕过去；要退出孤儿状态，必须把测试补齐。

### 0.7 检查器判定规则（`scripts/check_traceability.py`）

| 情形 | 退出码 | 说明 |
| --- | --- | --- |
| 矩阵文件缺失 / 表头找不到 / 表格结构无法解析 | `2` | 错误，需人工修矩阵 |
| 规则 ID 非法（非 `R-<数字>`）或状态列取值非 `pending`/`covered` | `2` | 错误，报告行号 |
| 无任何 `covered` 行 | `0` | 打印「矩阵尚未启用（P1 待填充），N 条规则待填」 |
| 有 `covered` 行，且存在无测试 ID 的规则行 | `1` | 打印孤儿清单（规则 ID + 摘要 + 出处） |
| 有 `covered` 行，且所有规则行都填了测试 ID | `0` | 打印「通过：N 条规则全部有测试覆盖」 |

> 结构校验（规则 ID 格式、状态取值）**先于**启用条件判定：矩阵写错了就是错误，不会因为「还没启用」而被放过。

### 0.8 变体与基线外规则怎么算「覆盖」（P1 填表前必读）

矩阵里有两类「非基线形态」的规则，它们的**覆盖判定标准不同**，P1 填表时不要混为一谈：

| 类别 | 涉及规则 | 依据 | 「覆盖」的标准 |
| --- | --- | --- | --- |
| **A 类：变体，基线不实现** | R-44、R-58、R-59、R-67、R-68 | 备注列写「变体，基线不实现」 | **不为不实现的功能硬造功能测试**。覆盖 = 存在一条测试证明「基线口径下该变体不被触发」（守护性测试）。这类测试断言的是「不发生」，不是「行为正确」。 |
| **B 类：可选 / 局前变体，基线要实现** | R-61、R-62、R-63（默认关闭）；§9.2 进阶层 R-53 ~ R-57 | 备注列写「局前变体」或「可选玩法，默认关闭」 | 需要**真实功能测试**：开关打开时行为正确、关闭时行为正确。构建计划 P2 验收标准已点名「天黑黑开关各局」，R-63 属必做。 |

判定要点：

1. A 类规则**不得**为了凑覆盖率而写成假的实现测试 —— 那是给门禁喂数据，破坏矩阵本身的可信度。
2. A 类规则的守护性测试必须**真的能失败**：若某天有人误把该变体接进基线路径，测试应当变红；否则它只是一张空票。
3. B 类规则的「关闭态」也要有断言 —— 默认口径本身就是被规定过的口径，不是「不需要测」。
4. 两类状态一律填 `covered`（都存在可执行判据），**不要**靠长期留 `pending` 来回避孤儿检查；留 `pending` 只允许用于「P1 尚未动工、还没写测试」的中间态。

---

## 1. 规则矩阵

共 **68** 条规则（`R-01` ~ `R-68`），与 `docs/design/01-game-rules.md` 的规则条目**一一对应**（无缺号、无重复、无自造）。行序按规则编号升序（设计稿 §0.3 规定编号按分配顺序递增、不随章节位置重排）。

| 规则 ID | 规则摘要 | 规则出处 | 测试 ID | 状态 | 备注 |
| --- | --- | --- | --- | --- | --- |
| R-01 | 每位玩家配 1 个骰盅 + 5 颗六面骰（面值 1–6） | 01 §2 | tests/unit/test_table.py::test_r01_hand_is_exactly_five_dice | covered | — |
| R-02 | 人数 N 允许 2–12；本项目基线支持 2–6 人 | 01 §2 | tests/unit/test_table.py::test_r02_player_count_supported_range | covered | — |
| R-03 | 全场总骰数 = 5N，所有玩家的骰子都参与结算计数 | 01 §2 | tests/unit/test_table.py::test_r03_total_dice_is_five_times_n; tests/unit/test_counting.py::test_total_count_sums_all_players | covered | — |
| R-04 | 行动方向为顺时针（逆时针为民间变体） | 01 §2 | tests/unit/test_table.py::test_r04_clockwise_baseline_and_seat_geometry | covered | — |
| R-05 | 每局由上一局输家先起叫；首局由房主指定或随机 | 01 §2 | tests/unit/test_bidding.py::test_r05_opening_caller_loser_first_with_a05_tiebreak | covered | 多输家并列按 A-05 取先；首局随机在引擎层（P2） |
| R-06 | 局前须约定 1 码的量与是否启用进阶加成 | 01 §2 | tests/unit/test_table.py::test_r06_rule_config_defaults_match_section12 | covered | §12 十八项全部入 RuleConfig，逐字段断言基线默认 |
| R-07 | 每人摇 5 颗骰扣在骰盅下，只允许自己查看 | 01 §4 | tests/unit/test_table.py::test_r07_hand_frozen_and_private_by_contract; tests/properties/test_replay_properties.py::test_information_isolation_every_view | covered | 可数部分（恰 5 颗/不可变）；"只允许自己查看"由 P2 信息隔离属性测试补强（全决策点穷举取证） |
| R-08 | 叠骰必须当众开盅检查后重新摇 | 01 §4 | tests/unit/test_table.py::test_r08_stacked_never_representable_in_digital_table | covered | 数字桌面无叠骰，规则位保留（02 §2.4.1）；穷举守护其不触发 |
| R-09 | 散骰（5 颗点数各不相同）必须重摇 | 01 §4 | tests/unit/test_table.py::test_r09_scattered_must_reshake_with_variants; tests/unit/test_counting.py::test_r61_and_r09_variant_count_zero_switches | covered | 基线必重摇 + 「计 0」变体两态 |
| R-10 | 任何人可公开验骰；验出叠骰/散骰按 R-08/R-09 处理 | 01 §4 | tests/unit/test_table.py::test_r10_reshake_check_is_public_idempotent_verification | covered | 数字桌面验骰即自动校验（02 §2.4.1）：判定为公开幂等纯函数 |
| R-11 | 首叫为非斋（飞）时，数量 X ≥ ⌈1.5N⌉ | 01 §5 | tests/unit/test_bidding.py::test_r11_r12_r14_opening_floor_table | covered | 另有属性穷举（tests/properties，不入矩阵） |
| R-12 | 首叫为斋时，数量 X ≥ N | 01 §5 | tests/unit/test_bidding.py::test_r11_r12_r14_opening_floor_table | covered | — |
| R-13 | 首叫的点数 Y 任意（1–6） | 01 §5 | tests/unit/test_bidding.py::test_r13_opening_face_any | covered | — |
| R-14 | ⌈1.5N⌉ 一律向上取整；N=5 时基线取 8 | 01 §5 | tests/unit/test_bidding.py::test_r11_r12_r14_opening_floor_table | covered | 变异 V-8 守护（ceil→floor 必须杀灭） |
| R-15 | 飞状态（1 为癞子）点数序：1 > 6 > 5 > 4 > 3 > 2 | 01 §6.1 | tests/unit/test_bidding.py::test_r15_r16_face_ranks_dual_track | covered | 6×6 穷举 |
| R-16 | 1 死状态（斋或过 1）点数序：1 < 2 < 3 < 4 < 5 < 6 | 01 §6.1 | tests/unit/test_bidding.py::test_r15_r16_face_ranks_dual_track | covered | — |
| R-17 | 数量优先：X' > X0，或同数量时点数按当前点数序更大 | 01 §6.2 | tests/unit/test_bidding.py::test_r17_r18_normal_rebid_three_regions | covered | 另有属性穷举（tests/properties，不入矩阵） |
| R-18 | 当 X' > X0 时，点数不受限制（可以更小） | 01 §6.2 | tests/unit/test_bidding.py::test_r17_r18_normal_rebid_three_regions | covered | — |
| R-19 | 斋：1 点不作癞子，只按面值计；状态由 FLY 转为 DEAD | 01 §6.3 | tests/unit/test_bidding.py::test_r19_zhai_transition_disables_wild; tests/unit/test_counting.py::test_r41_bonus_only_in_fly_state | covered | — |
| R-20 | 转斋（FLY→DEAD）：只需 X' ≥ X0，点数任意 | 01 §6.3 | tests/unit/test_bidding.py::test_r20_zhai_only_count_floor_any_face | covered | 变异 V-6 守护 |
| R-21 | 飞斋（DEAD→FLY）：需 X' ≥ 2 × X0，点数任意 | 01 §6.3 | tests/unit/test_bidding.py::test_r21_fei_requires_double_count | covered | 变异 V-1 守护 |
| R-22 | 过 1：一旦有人叫出点数 1，本局 1 点永久不作癞子，不可飞回 FLY | 01 §6.3 | tests/unit/test_bidding.py::test_r22_r23_ones_called_irreversible | covered | 变异 V-7 守护 |
| R-23 | 已过 1 的局不允许飞斋（onesCalled = false 才可飞斋） | 01 §6.3 | tests/unit/test_bidding.py::test_r22_r23_ones_called_irreversible | covered | 变异 V-7 守护 |
| R-24 | 叫骰合法性判定第 1 步：取当前状态 S 与 onesCalled 标记 | 01 §6.4 | tests/unit/test_bidding.py::test_r24_to_r28_five_step_order_probes | covered | 五步短路次序探针；另有属性穷举规约一致（tests/properties，不入矩阵） |
| R-25 | 判定第 2 步：转斋（FLY→DEAD）只查 X' ≥ X0，点数约束放宽 | 01 §6.4 | tests/unit/test_bidding.py::test_r24_to_r28_five_step_order_probes | covered | — |
| R-26 | 判定第 3 步：飞斋（DEAD→FLY）需 X' ≥ 2 × X0 且未过 1 | 01 §6.4 | tests/unit/test_bidding.py::test_r24_to_r28_five_step_order_probes | covered | — |
| R-27 | 判定第 4 步：其余情况按 R-17 / R-18 常规比较 | 01 §6.4 | tests/unit/test_bidding.py::test_r24_to_r28_five_step_order_probes | covered | — |
| R-28 | 判定第 5 步：被叫点数 Y' = 1 时置 onesCalled = true | 01 §6.4 | tests/unit/test_bidding.py::test_r24_to_r28_five_step_order_probes | covered | — |
| R-29 | 开杀只能对相邻的上家发起 | 01 §7 | tests/unit/test_bidding.py::test_r29_open_only_adjacent_predecessor | covered | — |
| R-30 | 跳杀（劈）只能对非相邻玩家发起 | 01 §7 | tests/unit/test_bidding.py::test_r30_jump_only_non_adjacent_caller | covered | — |
| R-31 | 连杀：可连续开杀相邻的多位叫骰者（至少 2 人），分别结算 | 01 §7 | tests/unit/test_bidding.py::test_r31_multi_consecutive_callers | covered | 目标 = 叫骰流水末尾连续 ≥2 位（R-04 轮转保证座位连续） |
| R-32 | 通杀：开杀除自己以外的所有参加者，同样分别结算 | 01 §7 | tests/unit/test_bidding.py::test_r32_sweep_all_other_participants | covered | 未叫骰者被点名但不判定（编排层按"无叫骰不判定"处理） |
| R-33 | 被开杀/被跳杀者三选一：开盅清点 / 反杀 / 投降 | 01 §7 | tests/unit/test_bidding.py::test_r33_r34_response_options_by_chain_kind | covered | — |
| R-34 | 反杀仅适用于被跳杀者；被开杀者只能开盅或投降 | 01 §7 | tests/unit/test_bidding.py::test_r33_r34_response_options_by_chain_kind | covered | §12 第 10 项变体开关两态同测 |
| R-35 | 投降：不开盅，直接接受当前惩罚减半 | 01 §7 | tests/unit/test_bidding.py::test_r35_surrender_always_available; tests/unit/test_settling.py::test_r52_surrender_half_with_floor_one | covered | — |
| R-36 | 反杀后原开杀/跳杀者可再对下一位叫骰者反杀一次（不可再被反杀） | 01 §7 | tests/unit/test_bidding.py::test_r36_recounter_next_caller_once; tests/unit/test_scenario.py::test_example3_recounter_step6 | covered | 目标 = 沿方向的下一位叫骰者（§13.3 第 6 步） |
| R-37 | 飞状态计数：Y ∈ 2..6 时含 #(骰面 = 1)；Y = 1 时只计 #(骰面 = 1) | 01 §8.1 | tests/unit/test_counting.py::test_r37_fly_count_includes_wilds | covered | 变异 V-3 守护（D-02 字面口径） |
| R-38 | 1 死状态计数：count(Y) = #(骰面 = Y)，对 Y ∈ 1..6 一律如此 | 01 §8.1 | tests/unit/test_counting.py::test_r38_dead_count_literal_only | covered | — |
| R-39 | 围骰：借 1 作癞子凑成同面值（非本来全同），对该面值贡献 6 | 01 §8.2 | tests/unit/test_counting.py::test_r39_leopard_bonus_six | covered | 变异 V-2 守护 |
| R-40 | 全骰：5 颗本来就是同一面值，对该面值贡献 7 | 01 §8.2 | tests/unit/test_counting.py::test_r40_pure_leopard_bonus_seven | covered | — |
| R-41 | 围骰/全骰加成仅在飞状态生效；1 死状态 5 颗相同只计 5 个 | 01 §8.2 | tests/unit/test_counting.py::test_r41_bonus_only_in_fly_state | covered | — |
| R-42 | 加成只作用于被叫的那个面值 | 01 §8.2 | tests/unit/test_counting.py::test_r42_bonus_only_for_called_face | covered | — |
| R-43 | 全骰的 5 个 1 在飞状态下对任意被叫面值都贡献 7 | 01 §8.2 | tests/unit/test_counting.py::test_r43_five_ones_count_seven_for_any_face | covered | — |
| R-44 | 变体「有骰计骰」：不计算围骰/全骰加成（部分地区通行） | 01 §8.2 | tests/unit/test_counting.py::test_r44_guard_baseline_and_switch_off | covered | A 类守护（默认加成存在）+ §12 第 5 项开关功能两层 |
| R-45 | 判定：count(Y) ≥ X 则叫骰成立、开骰者输；count(Y) < X 则被开者输 | 01 §8.3 | tests/unit/test_judging.py::test_r45_judge_direction_with_examples; tests/unit/test_scenario.py::test_example1_full_reconciliation | covered | 变异 V-4 守护 |
| R-46 | 1 码 = 局前约定的量（通常半杯或一杯） | 01 §9.1 | tests/unit/test_settling.py::test_r46_codes_are_integer_stakes | covered | A-04：1 码 = 1 分整数，stake_label 仅显示换算 |
| R-47 | 开杀：普通结算，负方付 1 码；开杀者下注不超过 2 码 | 01 §9.1 | tests/unit/test_settling.py::test_r47_no_stake_cap_special_case_n5_01 | covered | N5-01 裁决：后半句不入引擎结算，只按 §14.2 倍数表 |
| R-48 | 跳杀（劈）：惩罚翻倍，负方付 2 码 | 01 §9.1 | tests/unit/test_settling.py::test_r48_jump_base_double | covered | — |
| R-49 | 反杀：被跳杀者反杀，惩罚再翻倍，负方付 4 码 | 01 §9.1 | tests/unit/test_settling.py::test_r49_counter_chain_quadruples | covered | 链上倍数由编排层组装入 base_multiplier |
| R-50 | 连杀：连赢 3 家及以上时，输家惩罚再翻倍 | 01 §9.1 | tests/unit/test_settling.py::test_r50_multi_win_double_threshold | covered | §12 第 11 项开关两态 |
| R-51 | 通杀：分别结算，倍数不叠加 | 01 §9.1 | tests/unit/test_settling.py::test_r51_settled_separately_no_cross_stacking | covered | — |
| R-52 | 投降：接受当前惩罚的一半，不开盅 | 01 §9.1 | tests/unit/test_settling.py::test_r52_surrender_half_with_floor_one | covered | §12 第 12 项保底 1 码；变异 V-5 守护 |
| R-53 | 豹子加倍：被开/被跳杀者持有围骰或全骰且输了，惩罚加倍 | 01 §9.2 | tests/unit/test_settling.py::test_r53_leopard_double_both_chains | covered | D-04：两链通用；投降不适用 |
| R-54 | 不够一半：实际数量不足 X 的一半，输方惩罚加倍 | 01 §9.2 | tests/unit/test_settling.py::test_r54_under_half_doubles_open_chain_only | covered | D-04：严格限开杀链；恰为 X/2 不加倍 |
| R-55 | 超半：实际数量超过 X 的一半，开杀者惩罚加倍 | 01 §9.2 | tests/unit/test_settling.py::test_r55_over_half_challenger_rhetorical_double; tests/unit/test_scenario.py::test_example1_advanced_on_r55 | covered | D-04：修辞性加倍，不翻转 R-45 |
| R-56 | 跳杀失败惩罚加倍：跳杀者判断错误时惩罚加倍 | 01 §9.2 | tests/unit/test_settling.py::test_r56_jump_fail_double_jump_chain_only; tests/unit/test_scenario.py::test_example3_advanced_on_r56 | covered | D-04：严格限跳杀链 |
| R-57 | 陪饮：负方摇陪饮骰指定一位玩家同罚；摇中自己则再多喝一倍 | 01 §9.2 | tests/unit/test_settling.py::test_r57_drink_along_registered_mapping | covered | 映射细则按计划 §8 D-05 登记约定实现，改判只动 drink_along_pick |
| R-58 | P 版（Partner）：两人一组共用骰盅，负方协商共饮或分饮 | 01 §9.3 | tests/unit/test_settling.py::test_r58_r59_r67_r68_variant_guards | covered | A 类守护：基线契约面无组队支撑（矩阵 §0.8） |
| R-59 | T 版（Team）：两组一对一单挑，输方由下一位队友补上 | 01 §9.3 | tests/unit/test_settling.py::test_r58_r59_r67_r68_variant_guards | covered | A 类守护：同上 |
| R-60 | 顺色：5 颗点数互不相同且连续（12345 / 23456），属散骰必重摇 | 01 §4.1 | tests/unit/test_table.py::test_r60_straight_is_scattered_special_case | covered | 优先报告顺色（散骰特例） |
| R-61 | 局前变体：约定「顺色不重摇」时二选一（顺色计 0 个 / 照常计色） | 01 §4.1 | tests/unit/test_table.py::test_r61_straight_policy_variants_do_not_reshake; tests/unit/test_counting.py::test_r61_and_r09_variant_count_zero_switches | covered | B 类两态：重摇侧 + 计数侧 |
| R-62 | 局前变体「全红」：5 个 1 额外计为 8 个（+3），基线维持 7 个（+2） | 01 §8.2 | tests/unit/test_counting.py::test_r62_all_ones_eight_variant_fly_only | covered | B 类两态；仅飞态 |
| R-63 | 可选玩法「天黑黑」：开盅后无任何一颗为被叫点数 Y 则开骰者输 | 01 §9.2 | tests/unit/test_judging.py::test_r63_darkness_predicate_and_precheck | covered | B 类两态（默认关）；判定前置检查（05 §5） |
| R-64 | 数量上限：任何叫骰数量不得超过在场骰子总数 5N（全局硬约束） | 01 §6.2 | tests/unit/test_bidding.py::test_r64_bid_count_cap_policies; tests/unit/test_bidding.py::test_opening_r64_cap_applies_to_first_call | covered | §12 第 17 项三策略（5N / 5N−1 / 不限） |
| R-65 | 重摇次数上限：同局因叠骰/散骰重摇最多 3 次，第 4 次不合规判负按 1 码受罚 | 01 §4 | tests/unit/test_table.py::test_r65_reroll_limit_variants | covered | 变体放宽/收紧/关闭 |
| R-66 | 围骰/全骰与斋的关系：真同面值 +2（7 个）、靠 1 凑成 +1（6 个） | 01 §8.2 | tests/unit/test_counting.py::test_r66_true_same_vs_wild_assembled | covered | — |
| R-67 | 筹码模式：每次叫骰压一枚最小注，喊开时桌上筹码归赢家 | 01 §9.3 | tests/unit/test_settling.py::test_r58_r59_r67_r68_variant_guards | covered | A 类守护：基线契约面无筹码字段 |
| R-68 | 反弹：对上家数量加 2 改变叫骰顺序，弹 1 次加罚 1 码并递增 | 01 §9.3 | tests/unit/test_settling.py::test_r58_r59_r67_r68_variant_guards | covered | A 类守护：BidKind 动作面无反弹 |

---

## 2. 规则索引与覆盖率统计

### 2.1 按设计稿章节分布

| 设计稿章节 | 规则编号 | 条数 |
| --- | --- | --- |
| 01 §2 道具、人数与通用设定 | R-01 ~ R-06 | 6 |
| 01 §4 摇骰阶段 | R-07 ~ R-10、R-65 | 5 |
| 01 §4.1 顺色 | R-60 ~ R-61 | 2 |
| 01 §5 起叫规则（首叫） | R-11 ~ R-14 | 4 |
| 01 §6.1 点数序 | R-15 ~ R-16 | 2 |
| 01 §6.2 常规接叫 | R-17 ~ R-18、R-64 | 3 |
| 01 §6.3 斋、转斋、飞斋、过 1 | R-19 ~ R-23 | 5 |
| 01 §6.4 叫骰状态机（合法性判定顺序） | R-24 ~ R-28 | 5 |
| 01 §7 开杀、跳杀、连杀、反杀、投降 | R-29 ~ R-36 | 8 |
| 01 §8.1 计数口径 | R-37 ~ R-38 | 2 |
| 01 §8.2 围骰与全骰 | R-39 ~ R-44、R-62、R-66 | 8 |
| 01 §8.3 判定 | R-45 | 1 |
| 01 §9.1 基础层 | R-46 ~ R-52 | 7 |
| 01 §9.2 进阶层（可选） | R-53 ~ R-57、R-63 | 6 |
| 01 §9.3 非基线玩法（登记备查） | R-58 ~ R-59、R-67 ~ R-68 | 4 |
| **合计** | **R-01 ~ R-68** | **68** |

### 2.2 覆盖率统计

| 指标 | 当前值 |
| --- | --- |
| 规则总数 | 68 |
| 已覆盖（`covered`） | 68 |
| 待填充（`pending`） | 0 |
| **覆盖率** | **68 / 68（100%）** |
| 孤儿数 | 0（矩阵已启用，单向棘轮生效——后续任何改动不得让规则退回孤儿态） |

> 统计口径：分母 = §1 的规则行数（68）；分子 = 状态为 `covered` 的行数。
> P1 收口时该表应与 `uv run python scripts/check_traceability.py` 的输出一致。

---

## 3. CI 接入

### 3.1 怎么跑

```bash
uv run python scripts/check_traceability.py
```

自测其它矩阵副本（不触碰仓库真实文件）：

```bash
uv run python scripts/check_traceability.py --path /tmp/xxx/traceability.md
```

- 检查器：**纯标准库**，零第三方依赖，Python 3.12+ 兼容。
- 缺省矩阵路径：`tests/traceability.md`（相对仓库根；仓库根由脚本位置推导）。

### 3.2 退出码含义

| 退出码 | 含义 | CI 表现 |
| --- | --- | --- |
| `0` | 通过（矩阵尚未启用，或全部规则均有测试覆盖） | 绿 |
| `1` | 存在孤儿规则（有 `covered` 行，但仍有规则行没有测试 ID） | **红** —— 对应门禁 `G-trace 追溯孤儿 = 0` |
| `2` | 错误（矩阵缺失、表头缺失、表格结构无法解析、规则 ID 或状态列取值非法） | 红（配置/格式问题，须先修矩阵） |

### 3.3 矩阵在哪填

- 唯一填表位置：**本文件 §1 的规则矩阵**。
- 填写格式与命名约定见 **§0.3**；新增规则的附加义务见 **§0.4**。
- 填完后本地跑一次 `uv run python scripts/check_traceability.py` 确认 exit 0，再提交。

---

## 4. 变更记录

| 版本 | 日期 | 变更 | 作者 |
| --- | --- | --- | --- |
| v1.0 | 2026-11-10 | 初版：建立 R-01 ~ R-68 共 68 条规则的矩阵骨架与格式契约；全部规则状态为 `pending`，测试 ID 留待 P1 填充 | llm-perudo P0 |
| v1.1 | 2026-11-11 | **P1 填充**：68 条规则全部回填测试 ID 并置 `covered`；矩阵启用（单向棘轮生效）。覆盖口径：基线规则用功能测试；A 类变体（R-44/R-58/R-59/R-67/R-68）用守护性测试；B 类局前变体（R-53~R-57/R-61/R-62/R-63）用开关两态功能测试；R-05 并列取先按 A-05；R-47 按 N5-01（下注上限不入结算）；R-55/R-54/R-56/R-53 按 D-04 裁决口径；R-57 映射按 D-05 登记约定。属性测试（tests/properties/）为穷举安全网，按 §0.3 不入矩阵。配套变异清单 V-1~V-8 全部杀灭（G-mut）。 | llm-perudo P1 |
