"""AdapterSDK（03 §1.1）：与引擎对接的唯一骨架，全六家复用。

模块：config（参数骨架与 TOML 装载）/ context（提示词装配）/ parsing（响应
解析与思考剥离）/ transport（HTTP 传输 + 网络重试）/ ledger（成本信封）/
tuning（各家差异点）/ player（LLMPlayer 组装，实现 02 §4 玩家契约）。
"""
