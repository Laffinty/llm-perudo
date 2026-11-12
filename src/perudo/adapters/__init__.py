"""适配层（L2 消费者侧）：AdapterSDK（03 §1.1）+ 各家适配器。

架构红线（03 §0.2）：不自带规则、只走 02 §4 契约、台词防注入、密钥不落盘。
"六家一个骨架，一家一份 Tuning"（B-03）——差异点只出现在 Tuning 数据表、
Transport、显式钩子。

- ``sdk``：ContextBuilder / ResponseParser / SelfChecker / RetryController /
  CostLedger / Transport + LLMPlayer 组装；
- ``deepseek`` / ``glm``：P3 首批两家（M4a）；MiMo/Qwen/豆包/MiniMax 随 M4b。
"""
