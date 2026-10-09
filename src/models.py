#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""模型主数据层：canonical 实体 + 变体折叠 + 厂商/国别/开源归一。

原实现有三个缺陷，导致跨榜表"数据混乱"：
1. **变体未折叠**：LMArena 把 `claude-opus-5-high` / `claude-opus-5-max` 当成
   两个模型，SuperCLUE 带 `-0902(max)` 日期与档位戳，LiveCodeBench 带 `(High)`。
   本模块把这类"同一基座模型的不同档位/期次"折叠到同一 canonical 实体，
   被剥掉的档位信息保留在 `variant` 字段（**不修改榜单原始名次与分数**）。
2. **厂商未归一**：boards 里的 `organization` 是原始 slug（`openai` / `zai` /
   `google`），甚至混入 HuggingFace 用户名（`Lunzima` / `MaziyarPanahi`）。
   统一走 `normalize_vendor()`，原始值保留在调用方的 `vendor_raw` 以便追溯。
3. **字段缺失**：`region` 默认 `other`、`open` 默认 `None`，造成绝大多数行标签失效。
   现在 region/open 一律"能推就推，推不出显式 unknown"，字段处处必填。

匹配策略（先确定、后猜测，尽量少猜）：
   ① 逐级折叠变体，从"最折叠的基座名"开始试精确匹配注册表 / 别名；
   ② 命中即返回，并给出该层级被剥掉的变体标签；
   ③ 全部未命中 → 判为未注册（id 取折叠后的归一化名），厂商/国别靠
      「机构 slug 归一 → 名称关键词 → 未标注」三级推导。

新增模型：在 MODELS 里补一条 canonical 记录（并在 ALIASES 里补原始写法）即可。
"""

import re

# ---------------------------------------------------------------------------
# 1. canonical 模型注册表
# ---------------------------------------------------------------------------
# canonical_id -> {name, vendor, region(cn/us/fr/...), open(bool/None)}
# region: cn=国产, 其他为厂商所在国；open: 是否开源权重
MODELS = {
    # ---------- OpenAI ----------
    "gpt-6-astra": {"name": "GPT-6 Astra", "vendor": "OpenAI", "region": "us", "open": False},
    "gpt-6.1-sol": {"name": "GPT-6.1 Sol", "vendor": "OpenAI", "region": "us", "open": False},
    "gpt-6-sol": {"name": "GPT-6 Sol", "vendor": "OpenAI", "region": "us", "open": False},
    "gpt-5.6-sol": {"name": "GPT-5.6 Sol", "vendor": "OpenAI", "region": "us", "open": False},
    "gpt-5.5": {"name": "GPT-5.5", "vendor": "OpenAI", "region": "us", "open": False},
    "gpt-5.2": {"name": "GPT-5.2", "vendor": "OpenAI", "region": "us", "open": False},
    "gpt-5.1": {"name": "GPT-5.1", "vendor": "OpenAI", "region": "us", "open": False},
    "gpt-5": {"name": "GPT-5", "vendor": "OpenAI", "region": "us", "open": False},
    "o4-pro": {"name": "o4 Pro", "vendor": "OpenAI", "region": "us", "open": False},
    "o4-mini": {"name": "o4 Mini", "vendor": "OpenAI", "region": "us", "open": False},
    "o3": {"name": "o3", "vendor": "OpenAI", "region": "us", "open": False},
    "o3-mini": {"name": "o3 Mini", "vendor": "OpenAI", "region": "us", "open": False},
    # ---------- Anthropic ----------
    "claude-fable-5.1": {"name": "Claude Fable 5.1", "vendor": "Anthropic", "region": "us", "open": False},
    "claude-fable-5": {"name": "Claude Fable 5", "vendor": "Anthropic", "region": "us", "open": False},
    "claude-opus-5.5": {"name": "Claude Opus 5.5", "vendor": "Anthropic", "region": "us", "open": False},
    "claude-opus-5": {"name": "Claude Opus 5", "vendor": "Anthropic", "region": "us", "open": False},
    "claude-opus-4.8": {"name": "Claude Opus 4.8", "vendor": "Anthropic", "region": "us", "open": False},
    "claude-opus-4.7": {"name": "Claude Opus 4.7", "vendor": "Anthropic", "region": "us", "open": False},
    "claude-opus-4.6": {"name": "Claude Opus 4.6", "vendor": "Anthropic", "region": "us", "open": False},
    "claude-sonnet-5.5": {"name": "Claude Sonnet 5.5", "vendor": "Anthropic", "region": "us", "open": False},
    "claude-sonnet-5": {"name": "Claude Sonnet 5", "vendor": "Anthropic", "region": "us", "open": False},
    "claude-sonnet-4.6": {"name": "Claude Sonnet 4.6", "vendor": "Anthropic", "region": "us", "open": False},
    # ---------- Google ----------
    "gemini-4-argon": {"name": "Gemini 4 Argon", "vendor": "Google DeepMind", "region": "us", "open": False},
    "gemini-3.8-flash": {"name": "Gemini 3.8 Flash", "vendor": "Google DeepMind", "region": "us", "open": False},
    "gemini-3.7-flash": {"name": "Gemini 3.7 Flash", "vendor": "Google DeepMind", "region": "us", "open": False},
    "gemini-3.6-flash": {"name": "Gemini 3.6 Flash", "vendor": "Google DeepMind", "region": "us", "open": False},
    "gemini-3.5-pro": {"name": "Gemini 3.5 Pro", "vendor": "Google DeepMind", "region": "us", "open": False},
    "gemini-3.5-flash": {"name": "Gemini 3.5 Flash", "vendor": "Google DeepMind", "region": "us", "open": False},
    "gemini-3.1-pro": {"name": "Gemini 3.1 Pro", "vendor": "Google DeepMind", "region": "us", "open": False},
    "gemini-3-pro": {"name": "Gemini 3 Pro", "vendor": "Google DeepMind", "region": "us", "open": False},
    "gemini-3-flash": {"name": "Gemini 3 Flash", "vendor": "Google DeepMind", "region": "us", "open": False},
    # ---------- Meta ----------
    "muse-spark-1.3": {"name": "Muse Spark 1.3", "vendor": "Meta", "region": "us", "open": True},
    "muse-spark-1.2": {"name": "Muse Spark 1.2", "vendor": "Meta", "region": "us", "open": True},
    "muse-spark-1.1": {"name": "Muse Spark 1.1", "vendor": "Meta", "region": "us", "open": True},
    # ---------- xAI ----------
    "grok-5": {"name": "Grok 5", "vendor": "xAI", "region": "us", "open": False},
    "grok-4.20": {"name": "Grok 4.20", "vendor": "xAI", "region": "us", "open": False},
    "grok-4.7": {"name": "Grok 4.7", "vendor": "xAI", "region": "us", "open": False},
    "grok-4.5": {"name": "Grok 4.5", "vendor": "xAI", "region": "us", "open": False},
    "grok-3-mini": {"name": "Grok 3 Mini", "vendor": "xAI", "region": "us", "open": False},
    # ---------- 国产：小米 ----------
    "mimo-v2.6-pro": {"name": "MiMo V2.6 Pro", "vendor": "小米", "region": "cn", "open": True},
    "mimo-v2-flash": {"name": "MiMo V2 Flash", "vendor": "小米", "region": "cn", "open": True},
    # ---------- 海外开源厂商 ----------
    "mistral-medium-3.5": {"name": "Mistral Medium 3.5", "vendor": "Mistral AI", "region": "fr", "open": True},
    # ---------- 国产：阶跃星辰 / 美团 ----------
    "step-5-preview": {"name": "阶跃 Step 5 Preview", "vendor": "阶跃星辰", "region": "cn", "open": False},
    "longcat-flash": {"name": "LongCat Flash", "vendor": "美团", "region": "cn", "open": False},
    # ---------- 国产：阿里 ----------
    "qwen3.8-max": {"name": "通义千问 Qwen3.8-Max", "vendor": "阿里巴巴", "region": "cn", "open": False},
    "qwen3.8-flash": {"name": "通义千问 Qwen3.8-Flash", "vendor": "阿里巴巴", "region": "cn", "open": True},
    "qwen3.7-max": {"name": "通义千问 Qwen3.7-Max", "vendor": "阿里巴巴", "region": "cn", "open": False},
    "qwen3-max": {"name": "通义千问 Qwen3-Max", "vendor": "阿里巴巴", "region": "cn", "open": False},
    # ---------- 国产：深度求索 ----------
    "deepseek-v4.1-flash": {"name": "DeepSeek V4.1-Flash", "vendor": "深度求索", "region": "cn", "open": True},
    "deepseek-v4-pro": {"name": "DeepSeek V4-Pro", "vendor": "深度求索", "region": "cn", "open": True},
    "deepseek-v4-flash": {"name": "DeepSeek V4-Flash", "vendor": "深度求索", "region": "cn", "open": True},
    "deepseek-r2": {"name": "DeepSeek R2", "vendor": "深度求索", "region": "cn", "open": True},
    "deepseek-r1": {"name": "DeepSeek R1", "vendor": "深度求索", "region": "cn", "open": True},
    # ---------- 国产：智谱 ----------
    "glm-5.3": {"name": "GLM-5.3", "vendor": "智谱 AI", "region": "cn", "open": True},
    "glm-5.3-flash": {"name": "GLM-5.3-Flash", "vendor": "智谱 AI", "region": "cn", "open": True},
    "glm-5.2": {"name": "GLM-5.2", "vendor": "智谱 AI", "region": "cn", "open": True},
    # ---------- 国产：月之暗面 ----------
    "kimi-k3": {"name": "Kimi K3", "vendor": "月之暗面", "region": "cn", "open": True},
    "kimi-k2.6": {"name": "Kimi K2.6", "vendor": "月之暗面", "region": "cn", "open": True},
    # ---------- 国产：字节 ----------
    "doubao-seed-2.1-pro": {"name": "豆包 Doubao-Seed-2.1 Pro", "vendor": "字节跳动", "region": "cn", "open": False},
    "doubao-seed-2.0-pro": {"name": "豆包 Doubao-Seed-2.0 Pro", "vendor": "字节跳动", "region": "cn", "open": False},
    # ---------- 国产：百度 ----------
    "ernie-5.1": {"name": "文心一言 ERNIE 5.1", "vendor": "百度", "region": "cn", "open": False},
    # ---------- 国产：MiniMax ----------
    "minimax-m3": {"name": "MiniMax M3", "vendor": "稀宇科技", "region": "cn", "open": True},
    # ---------- 国产：腾讯 ----------
    "hunyuan-t2": {"name": "混元 Hunyuan-T2", "vendor": "腾讯", "region": "cn", "open": False},
}

# 补充登记：跨榜出现、但早期注册表未收录的既有世代模型。
# 有了这些条目，跨榜表里就不会再出现 `qwen3.5-122b-a10b` 这类原始小写 slug。
MODELS.update({
    # ---- OpenAI（旧世代）----
    "gpt-4o": {"name": "GPT-4o", "vendor": "OpenAI", "region": "us", "open": False},
    "gpt-4o-mini": {"name": "GPT-4o mini", "vendor": "OpenAI", "region": "us", "open": False},
    "gpt-4-turbo": {"name": "GPT-4 Turbo", "vendor": "OpenAI", "region": "us", "open": False},
    "gpt-6-luna": {"name": "GPT-6 Luna", "vendor": "OpenAI", "region": "us", "open": False},
    # ---- Anthropic（4.x 世代）----
    "claude-opus-4.5": {"name": "Claude Opus 4.5", "vendor": "Anthropic", "region": "us", "open": False},
    "claude-opus-4.1": {"name": "Claude Opus 4.1", "vendor": "Anthropic", "region": "us", "open": False},
    "claude-sonnet-4.5": {"name": "Claude Sonnet 4.5", "vendor": "Anthropic", "region": "us", "open": False},
    "claude-haiku-4.5": {"name": "Claude Haiku 4.5", "vendor": "Anthropic", "region": "us", "open": False},
    "claude-3.5-sonnet": {"name": "Claude 3.5 Sonnet", "vendor": "Anthropic", "region": "us", "open": False},
    # ---- Google ----
    "gemini-2.5-pro": {"name": "Gemini 2.5 Pro", "vendor": "Google DeepMind", "region": "us", "open": False},
    "gemini-3.1-flash-lite": {"name": "Gemini 3.1 Flash Lite", "vendor": "Google DeepMind", "region": "us", "open": False},
    "gemma-4-31b": {"name": "Gemma 4 31B", "vendor": "Google DeepMind", "region": "us", "open": True},
    "gemma-4-26b-a4b": {"name": "Gemma 4 26B-A4B", "vendor": "Google DeepMind", "region": "us", "open": True},
    # ---- 阿里 ----
    "qwen3.8-27b": {"name": "通义千问 Qwen3.8-27B", "vendor": "阿里巴巴", "region": "cn", "open": True},
    "qwen3.7-plus": {"name": "通义千问 Qwen3.7-Plus", "vendor": "阿里巴巴", "region": "cn", "open": None},
    "qwen3.6": {"name": "通义千问 Qwen3.6", "vendor": "阿里巴巴", "region": "cn", "open": None},
    "qwen3.6-plus": {"name": "通义千问 Qwen3.6-Plus", "vendor": "阿里巴巴", "region": "cn", "open": None},
    "qwen3.5-397b-a17b": {"name": "通义千问 Qwen3.5-397B-A17B", "vendor": "阿里巴巴", "region": "cn", "open": True},
    "qwen3.5-122b-a10b": {"name": "通义千问 Qwen3.5-122B-A10B", "vendor": "阿里巴巴", "region": "cn", "open": True},
    "qwen3.5-27b": {"name": "通义千问 Qwen3.5-27B", "vendor": "阿里巴巴", "region": "cn", "open": True},
    "qwen3.5-35b-a3b": {"name": "通义千问 Qwen3.5-35B-A3B", "vendor": "阿里巴巴", "region": "cn", "open": True},
    "qwen3.5-flash": {"name": "通义千问 Qwen3.5-Flash", "vendor": "阿里巴巴", "region": "cn", "open": True},
    "qwen3-coder-480b-a35b": {"name": "通义千问 Qwen3-Coder-480B", "vendor": "阿里巴巴", "region": "cn", "open": True},
    "qwen3-235b-a22b": {"name": "通义千问 Qwen3-235B-A22B", "vendor": "阿里巴巴", "region": "cn", "open": True},
    # ---- 深度求索 ----
    "deepseek-v3": {"name": "DeepSeek V3", "vendor": "深度求索", "region": "cn", "open": True},
    "deepseek-v3.2": {"name": "DeepSeek V3.2", "vendor": "深度求索", "region": "cn", "open": True},
    # ---- xAI ----
    "grok-4.1": {"name": "Grok 4.1", "vendor": "xAI", "region": "us", "open": False},
    "grok-4.3": {"name": "Grok 4.3", "vendor": "xAI", "region": "us", "open": False},
    "grok-4.6": {"name": "Grok 4.6", "vendor": "xAI", "region": "us", "open": False},
    "grok-4-fast": {"name": "Grok 4 Fast", "vendor": "xAI", "region": "us", "open": False},
    "grok-4.1-fast": {"name": "Grok 4.1 Fast", "vendor": "xAI", "region": "us", "open": False},
    # ---- 智谱 ----
    "glm-5": {"name": "GLM-5", "vendor": "智谱 AI", "region": "cn", "open": True},
    "glm-5.1": {"name": "GLM-5.1", "vendor": "智谱 AI", "region": "cn", "open": True},
    "glm-4.6": {"name": "GLM-4.6", "vendor": "智谱 AI", "region": "cn", "open": True},
    "glm-4.7": {"name": "GLM-4.7", "vendor": "智谱 AI", "region": "cn", "open": True},
    "glm-5v-turbo": {"name": "GLM-5V Turbo", "vendor": "智谱 AI", "region": "cn", "open": None},
    # ---- 月之暗面 ----
    "kimi-k2.5": {"name": "Kimi K2.5", "vendor": "月之暗面", "region": "cn", "open": True},
    "kimi-k2.5-instant": {"name": "Kimi K2.5 Instant", "vendor": "月之暗面", "region": "cn", "open": True},
    "kimi-k2-thinking-turbo": {"name": "Kimi K2 Thinking Turbo", "vendor": "月之暗面", "region": "cn", "open": True},
    # ---- 稀宇科技 ----
    "minimax-m2": {"name": "MiniMax M2", "vendor": "稀宇科技", "region": "cn", "open": True},
    "minimax-m2.1": {"name": "MiniMax M2.1", "vendor": "稀宇科技", "region": "cn", "open": True},
    "minimax-m2.5": {"name": "MiniMax M2.5", "vendor": "稀宇科技", "region": "cn", "open": True},
    "minimax-m2.7": {"name": "MiniMax M2.7", "vendor": "稀宇科技", "region": "cn", "open": True},
    # ---- 腾讯 ----
    "hunyuan-hy3": {"name": "混元 Hunyuan-HY3", "vendor": "腾讯", "region": "cn", "open": None},
    "hunyuan-hy4": {"name": "混元 Hunyuan-HY4", "vendor": "腾讯", "region": "cn", "open": None},
    # ---- 小米 ----
    "mimo-v2.5-pro": {"name": "MiMo V2.5 Pro", "vendor": "小米", "region": "cn", "open": True},
    "mimo-v2.5": {"name": "MiMo V2.5", "vendor": "小米", "region": "cn", "open": True},
    "mimo-v2-pro": {"name": "MiMo V2 Pro", "vendor": "小米", "region": "cn", "open": True},
    "mimo-v2.6-flash": {"name": "MiMo V2.6 Flash", "vendor": "小米", "region": "cn", "open": True},
    # ---- 其他海外 ----
    "mistral-large-3": {"name": "Mistral Large 3", "vendor": "Mistral AI", "region": "fr", "open": None},
    "mistral-large-4": {"name": "Mistral Large 4", "vendor": "Mistral AI", "region": "fr", "open": None},
    "muse-glimmer": {"name": "Muse Glimmer", "vendor": "Meta", "region": "us", "open": True},
    "granite-4.1-8b": {"name": "Granite 4.1 8B", "vendor": "IBM", "region": "us", "open": True},
    "solar-pro4": {"name": "Solar Pro 4", "vendor": "Upstage", "region": "kr", "open": None},
    "mercury-2": {"name": "Mercury 2", "vendor": "Inception AI", "region": "us", "open": False},
})

# 归一化片段 -> canonical_id。key 为归一化文本（小写、去掉空格和 . _ - 等符号）。
# 仅作为"折叠后精确匹配"失败时的包含式兜底，按 key 长度降序优先。
ALIASES = {
    "hy3": "hunyuan-hy3",
    "hy4": "hunyuan-hy4",
    "gpt6astra": "gpt-6-astra",
    "gpt61sol": "gpt-6.1-sol",
    "gpt56sol": "gpt-5.6-sol",
    "gpt55": "gpt-5.5",
    "gpt52": "gpt-5.2",
    "gpt51": "gpt-5.1",
    "gpt5": "gpt-5",
    "o4pro": "o4-pro",
    "o4mini": "o4-mini",
    "o3mini": "o3-mini",
    "claudefable51": "claude-fable-5.1",
    "claudefable5": "claude-fable-5",
    "claudeopus55": "claude-opus-5.5",
    "claudeopus5": "claude-opus-5",
    "claudeopus48": "claude-opus-4.8",
    "claudeopus47": "claude-opus-4.7",
    "claudeopus46": "claude-opus-4.6",
    "claudesonnet55": "claude-sonnet-5.5",
    "claudesonnet5": "claude-sonnet-5",
    "claudesonnet46": "claude-sonnet-4.6",
    "gemini4argon": "gemini-4-argon",
    "gemini38flash": "gemini-3.8-flash",
    "gemini37flash": "gemini-3.7-flash",
    "gemini36flash": "gemini-3.6-flash",
    "gemini35pro": "gemini-3.5-pro",
    "gemini35flash": "gemini-3.5-flash",
    "gemini31pro": "gemini-3.1-pro",
    "gemini3pro": "gemini-3-pro",
    "gemini3flash": "gemini-3-flash",
    "musespark13": "muse-spark-1.3",
    "musespark12": "muse-spark-1.2",
    "musespark11": "muse-spark-1.1",
    "grok5": "grok-5",
    "grok420": "grok-4.20",
    "grok47": "grok-4.7",
    "grok45": "grok-4.5",
    "grok3mini": "grok-3-mini",
    "mimov26pro": "mimo-v2.6-pro",
    "mimov2flash": "mimo-v2-flash",
    "qwen38max": "qwen3.8-max",
    "qwen38flash": "qwen3.8-flash",
    "qwen37max": "qwen3.7-max",
    "qwen3max": "qwen3-max",
    "deepseekv41flash": "deepseek-v4.1-flash",
    "deepseekv4pro": "deepseek-v4-pro",
    "deepseekv4flash": "deepseek-v4-flash",
    "deepseekr2": "deepseek-r2",
    "deepseekr1": "deepseek-r1",
    "glm53flash": "glm-5.3-flash",
    "glm53": "glm-5.3",
    "glm52": "glm-5.2",
    "kimik3": "kimi-k3",
    "kimik26": "kimi-k2.6",
    "doubaoseed21pro": "doubao-seed-2.1-pro",
    "doubaoseed20pro": "doubao-seed-2.0-pro",
    "ernie51": "ernie-5.1",
    "minimaxm3": "minimax-m3",
    "hunyuant2": "hunyuan-t2",
}

# ---------------------------------------------------------------------------
# 2. 厂商归一：原始 organization slug -> 规范厂商名
# ---------------------------------------------------------------------------
VENDOR_ALIASES = {
    "openai": "OpenAI", "open-ai": "OpenAI",
    "anthropic": "Anthropic", "claude": "Anthropic",
    "google": "Google DeepMind", "googledeepmind": "Google DeepMind",
    "deepmind": "Google DeepMind", "googleai": "Google DeepMind",
    "meta": "Meta", "metallama": "Meta", "meta-llama": "Meta", "llama": "Meta",
    "xai": "xAI", "x-ai": "xAI",
    "alibaba": "阿里巴巴", "qwen": "阿里巴巴", "tongyi": "阿里巴巴", "阿里巴巴": "阿里巴巴",
    "deepseek": "深度求索", "深度求索": "深度求索",
    "zai": "智谱 AI", "z-ai": "智谱 AI", "zhipu": "智谱 AI", "zhipuai": "智谱 AI",
    "chatglm": "智谱 AI", "智谱ai": "智谱 AI",
    "moonshot": "月之暗面", "moonshotai": "月之暗面", "kimi": "月之暗面",
    "bytedance": "字节跳动", "doubao": "字节跳动",
    "baidu": "百度", "ernie": "百度",
    "minimax": "稀宇科技", "abab": "稀宇科技",
    "tencent": "腾讯", "hunyuan": "腾讯",
    "xiaomi": "小米", "mimo": "小米",
    "stepfun": "阶跃星辰", "step": "阶跃星辰",
    "meituan": "美团", "longcat": "美团",
    "antgroup": "蚂蚁集团", "ant-group": "蚂蚁集团",
    "mistral": "Mistral AI", "mistralai": "Mistral AI",
    "nvidia": "NVIDIA", "amazon": "Amazon", "microsoft": "Microsoft", "ibm": "IBM",
    "allenai": "Allen AI", "allen-ai": "Allen AI", "ai2": "Allen AI",
    "cohere": "Cohere", "inceptionai": "Inception AI", "inception-ai": "Inception AI",
    "poolside": "Poolside", "upstage": "Upstage",
    "sensetime": "商汤", "商汤": "商汤",
    "01ai": "零一万物", "01-ai": "零一万物", "零一万物": "零一万物",
    "baichuan": "百川智能", "百川智能": "百川智能",
    "huawei": "华为", "华为": "华为",
}

# 厂商 -> 国别（用于 region 必填）
REGION_BY_VENDOR = {
    "OpenAI": "us", "Anthropic": "us", "Google DeepMind": "us", "Meta": "us",
    "xAI": "us", "NVIDIA": "us", "Amazon": "us", "Microsoft": "us", "IBM": "us",
    "Allen AI": "us", "Poolside": "us", "Inception AI": "us",
    "Mistral AI": "fr", "Cohere": "ca", "Upstage": "kr",
    "阿里巴巴": "cn", "深度求索": "cn", "智谱 AI": "cn", "月之暗面": "cn",
    "字节跳动": "cn", "百度": "cn", "稀宇科技": "cn", "腾讯": "cn", "小米": "cn",
    "阶跃星辰": "cn", "美团": "cn", "蚂蚁集团": "cn", "商汤": "cn",
    "零一万物": "cn", "百川智能": "cn", "华为": "cn",
}

# ---------------------------------------------------------------------------
# 3. 变体折叠
# ---------------------------------------------------------------------------
_PUNCT = re.compile(r"[\s\-_.:/(),\[\]]+")

# 推理档位 / 运行模式 / 发布态 —— 这些是"同一基座模型的不同变体"，非独立模型。
# 注意：不包含 pro / flash / mini / max（它们常是正式名的一部分，如 Qwen3.8-Max）。
_MODE_WORDS = (
    "xhigh", "xlow", "high", "medium", "low", "minimal",
    "thinking", "nothinking", "nonthinking", "reasoning",
    "instruct", "chat", "preview", "experimental", "exp",
    "beta", "alpha", "nightly", "latest", "online", "max",
)
_MODE_RE = re.compile(r"[\s\-_]+(" + "|".join(_MODE_WORDS) + r")$", re.I)
_PAREN_RE = re.compile(r"\s*[\(（]([^\(（\)）]{1,18})[\)）]\s*$")
_CTX_RE = re.compile(r"[\s\-_]+(\d{1,3}k|\d{1,2}m)$", re.I)   # 上下文长度变体：-32k / -128K / -1M
_DATE_RES = (
    re.compile(r"[\s\-_]*((?:19|20)\d{2})[\-_]?(\d{2})[\-_]?(\d{2})$"),  # 20241022 / 2025-01-31
    re.compile(r"[\s\-_]*(\d{2})[\-_](\d{2})$"),                        # 06-05
    re.compile(r"[\s\-_]*(\d{4})$"),                                    # 0902 / 0528
)
_DATE_LABEL_RE = re.compile(r"^[\s\-_]*\d[\d\-_]*$")


def normalize(name: str) -> str:
    """小写、去标点空格。'GPT-5.6 Sol' -> 'gpt56sol'"""
    return _PUNCT.sub("", (name or "").lower())


def _strip_one(text):
    """剥掉一层"变体尾巴"，返回 (base, label, kind)；无可剥返回 (None, None, None)。

    kind ∈ {'paren', 'date', 'ctx', 'mode'}；label 为被剥掉的内容。"""
    t = (text or "").strip()
    m = _PAREN_RE.search(t)
    if m:
        base = t[:m.start()].strip(" -_")
        if base:
            return base, m.group(1).strip(), "paren"
    for pat in _DATE_RES:
        m = pat.search(t)
        if not m:
            continue
        base = t[:m.start()].strip(" -_")
        if not base:
            continue
        raw = m.group(0).strip(" -_")
        if pat is _DATE_RES[2]:  # 4 位纯数字需像 MM DD，避免误伤 grok-4.20 之类
            if not (1 <= int(raw[:2]) <= 12 and 1 <= int(raw[2:]) <= 31):
                continue
        return base, raw, "date"
    m = _CTX_RE.search(t)
    if m:
        base = t[:m.start()].strip(" -_")
        if base:
            return base, m.group(1), "ctx"
    m = _MODE_RE.search(t)
    if m:
        base = t[:m.start()].strip(" -_")
        if base:
            return base, m.group(1), "mode"
    return None, None, None


def _fold_chain(name):
    """返回 [(text, labels)]，按「最折叠 -> 原串」排列，供按序试匹配。

    labels 为该层级已剥掉的**非日期**变体标记（去重、保序）。"""
    text = (name or "").strip()
    chain = [(text, [])]
    seen = {text}
    for _ in range(8):
        base, lab, kind = _strip_one(text)
        if not base or base in seen or len(base) < 2:
            break
        labels = list(chain[-1][1])
        if kind != "date" and lab:
            low = lab.lower()
            if low not in [x.lower() for x in labels] and not _DATE_LABEL_RE.match(lab):
                labels.append(lab)
        chain.append((base, labels))
        seen.add(base)
        text = base
    return list(reversed(chain))


# 精确查找表：归一化文本 -> canonical_id（注册 id、注册 display name、别名）
_DIRECT = {}
for _cid, _meta in MODELS.items():
    _DIRECT[normalize(_cid)] = _cid
    _DIRECT[normalize(_meta["name"])] = _cid
for _k, _v in ALIASES.items():
    _DIRECT.setdefault(_k, _v)
_ALIAS_KEYS = sorted(ALIASES.keys(), key=len, reverse=True)


def _lookup_exact(text):
    """精确匹配（归一化后）。命中返回 canonical_id，否则 None。"""
    n = normalize(text)
    if not n:
        return None
    return _DIRECT.get(n)


def resolve(name):
    """模型名 -> 解析结果。

    返回 dict：id / display_name / vendor / region / open / variant / registered
    其中 vendor、region 恒为非空字符串（推不出时分别给 '未标注' / 'other'），
    open 为 True/False/None（None 表示上游未声明，显式表达"未知"而非当作 False）。"""
    raw = (name or "").strip()
    chain = _fold_chain(raw)

    cid, matched_labels = None, None
    for text, labels in chain:            # ① 从最折叠的基座名开始精确匹配
        hit = _lookup_exact(text)
        if hit:
            cid, matched_labels = hit, labels
            break

    if not cid:                            # ② 包含式别名兜底（老逻辑）
        n = normalize(chain[0][0])
        for key in _ALIAS_KEYS:
            if key in n:
                cid, matched_labels = ALIASES[key], chain[0][1]
                break

    base = chain[0][0]
    if cid:
        meta = MODELS[cid]
        return {
            "id": cid,
            "display_name": meta["name"],
            "vendor": meta["vendor"],
            "region": meta["region"],
            "open": meta["open"],
            "variant": _variant_label(matched_labels),
            "registered": True,
        }
    # ③ 未注册：id 取折叠后的归一化名（保证同一基座的不同档位折叠为同一 id）
    vendor = "未标注"
    region = "other"
    return {
        "id": normalize(base) or "unknown",
        "display_name": base or raw,
        "vendor": vendor,
        "region": region,
        "open": None,
        "variant": _variant_label(chain[0][1]),
        "registered": False,
    }


def _variant_label(labels):
    if not labels:
        return None
    out = []
    for l in labels:
        ll = str(l).strip().lower()
        if ll and ll not in out:
            out.append(ll)
    return " / ".join(out) if out else None


def canonical_id(name: str) -> str:
    """模型名 -> canonical id（兼容旧接口）。"""
    return resolve(name)["id"]


def normalize_vendor(org) -> str:
    """原始机构 slug -> 规范厂商名；无法识别返回 ''。"""
    if not org:
        return ""
    s = str(org).strip()
    if not s:
        return ""
    key = _PUNCT.sub("", s.lower())
    if key in VENDOR_ALIASES:
        return VENDOR_ALIASES[key]
    # 中文机构名（含 CJK）直接保留
    if re.search(r"[\u4e00-\u9fff]", s):
        return s.replace("智谱AI", "智谱 AI")
    return ""


def guess_vendor(name: str) -> str:
    """按模型名关键词猜厂商；猜不出返回 ''。"""
    low = (name or "").lower()
    rules = [
        ("gpt-6-astra", "OpenAI"), ("gpt", "OpenAI"), ("o4", "OpenAI"), ("o3", "OpenAI"),
        ("claude", "Anthropic"),
        ("gemini", "Google DeepMind"),
        ("llama", "Meta"), ("muse", "Meta"),
        ("grok", "xAI"),
        ("qwen", "阿里巴巴"), ("通义", "阿里巴巴"),
        ("deepseek", "深度求索"),
        ("glm", "智谱 AI"), ("chatglm", "智谱 AI"),
        ("kimi", "月之暗面"), ("moonshot", "月之暗面"),
        ("doubao", "字节跳动"), ("豆包", "字节跳动"),
        ("ernie", "百度"), ("文心", "百度"),
        ("minimax", "稀宇科技"), ("abab", "稀宇科技"),
        ("hunyuan", "腾讯"), ("混元", "腾讯"),
        ("mimo", "小米"), ("longcat", "美团"),
        ("step", "阶跃星辰"), ("baichuan", "百川智能"),
        ("yi-", "零一万物"), ("sensechat", "商汤"),
        ("mistral", "Mistral AI"), ("command", "Cohere"),
        ("nemotron", "NVIDIA"), ("phi", "Microsoft"), ("olmo", "Allen AI"),
    ]
    for kw, vendor in rules:
        if kw in low:
            return vendor
    return ""


def enrich(name: str, organization=None) -> dict:
    """补充厂商/国别/开源标签（字段必填）。兼容旧位置参数签名。

    厂商优先级：注册表 > 机构 slug 归一 > 名称关键词 > '未标注'。
    国别由厂商推导（注册表未登记时也保持一致）。"""
    r = resolve(name)
    if not r["registered"]:
        v = normalize_vendor(organization) or guess_vendor(name)
        r["vendor"] = v or "未标注"
        r["region"] = REGION_BY_VENDOR.get(r["vendor"], "other")
    return r
