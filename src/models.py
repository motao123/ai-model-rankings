#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""模型注册表：厂商、国别、开源状态、跨榜别名归一化。

用途：
1. 前端展示"国产模型"标签与厂商标签；
2. 三榜同屏对比时把不同榜单的同一模型对齐到 canonical id。

注意：alias 匹配为小写、去空格/标点后的包含式匹配，按 key 长度降序优先，
避免 "gpt-5" 误吞 "gpt-5.5"。新模型出现时在此表补充即可，未命中时
canonical = 归一化后的模型名本身（不影响渲染，只是跨榜对齐少一条）。
"""

import re

# canonical_id -> {name, vendor, region(cn/us/...), open(bool/None)}
# region: cn=国产, 其他为海外厂商所在国
MODELS = {
    # ---------- OpenAI ----------
    "gpt-6-astra": {"name": "GPT-6 Astra", "vendor": "OpenAI", "region": "us", "open": False},
    "gpt-6.1-sol": {"name": "GPT-6.1 Sol", "vendor": "OpenAI", "region": "us", "open": False},
    "gpt-5.6-sol": {"name": "GPT-5.6 Sol", "vendor": "OpenAI", "region": "us", "open": False},
    "gpt-5.5": {"name": "GPT-5.5", "vendor": "OpenAI", "region": "us", "open": False},
    "gpt-5.2": {"name": "GPT-5.2", "vendor": "OpenAI", "region": "us", "open": False},
    "gpt-5.1": {"name": "GPT-5.1", "vendor": "OpenAI", "region": "us", "open": False},
    "gpt-5": {"name": "GPT-5", "vendor": "OpenAI", "region": "us", "open": False},
    "o4-pro": {"name": "o4 Pro", "vendor": "OpenAI", "region": "us", "open": False},
    # ---------- Anthropic ----------
    "claude-fable-5.1": {"name": "Claude Fable 5.1", "vendor": "Anthropic", "region": "us", "open": False},
    "claude-fable-5": {"name": "Claude Fable 5", "vendor": "Anthropic", "region": "us", "open": False},
    "claude-opus-5": {"name": "Claude Opus 5", "vendor": "Anthropic", "region": "us", "open": False},
    "claude-opus-5.5": {"name": "Claude Opus 5.5", "vendor": "Anthropic", "region": "us", "open": False},
    "claude-opus-4.8": {"name": "Claude Opus 4.8", "vendor": "Anthropic", "region": "us", "open": False},
    "claude-opus-4.7": {"name": "Claude Opus 4.7", "vendor": "Anthropic", "region": "us", "open": False},
    "claude-opus-4.6": {"name": "Claude Opus 4.6", "vendor": "Anthropic", "region": "us", "open": False},
    "claude-sonnet-5": {"name": "Claude Sonnet 5", "vendor": "Anthropic", "region": "us", "open": False},
    "claude-sonnet-5.5": {"name": "Claude Sonnet 5.5", "vendor": "Anthropic", "region": "us", "open": False},
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
    # ---------- 国产：小米 ----------
    "mimo-v2.6-pro": {"name": "MiMo V2.6 Pro", "vendor": "小米", "region": "cn", "open": True},
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

# 归一化片段 -> canonical_id。key 为归一化文本（小写、去掉空格和 . _ - 等符号后做包含匹配）
# 匹配时按 key 长度降序，最长优先。
ALIASES = {
    "gpt6astra": "gpt-6-astra",
    "gpt61sol": "gpt-6.1-sol",
    "gpt56sol": "gpt-5.6-sol",
    "gpt55": "gpt-5.5",
    "gpt52": "gpt-5.2",
    "gpt51": "gpt-5.1",
    "gpt5": "gpt-5",
    "o4pro": "o4-pro",
    "claudefable51": "claude-fable-5.1",
    "claudefable5": "claude-fable-5",
    "claudeopus5": "claude-opus-5",
    "claudeopus55": "claude-opus-5.5",
    "claudeopus48": "claude-opus-4.8",
    "claudeopus47": "claude-opus-4.7",
    "claudeopus46": "claude-opus-4.6",
    "claudesonnet55": "claude-sonnet-5.5",
    "claudesonnet5": "claude-sonnet-5",
    "claudesonnet46": "claude-sonnet-4.6",
    "gemini4argonhigh": "gemini-4-argon",
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
    "mimov26pro": "mimo-v2.6-pro",
    "qwen38max0902": "qwen3.8-max",
    "qwen38max": "qwen3.8-max",
    "qwen38flash": "qwen3.8-flash",
    "qwen37max": "qwen3.7-max",
    "qwen3max": "qwen3-max",
    "tongyiqianwen": "qwen3-max",
    "deepseekv41flash": "deepseek-v4.1-flash",
    "deepseekv4pro": "deepseek-v4-pro",
    "deepseekv4flash": "deepseek-v4-flash",
    "deepseekr2": "deepseek-r2",
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

_PUNCT = re.compile(r"[\s\-_.:/(),\[\]]+")


def normalize(name: str) -> str:
    """小写、去标点空格。'GPT-5.6 Sol' -> 'gpt56sol'"""
    return _PUNCT.sub("", (name or "").lower())


_ALIAS_KEYS = sorted(ALIASES.keys(), key=len, reverse=True)


def canonical_id(name: str) -> str:
    """模型名 -> canonical id。未命中注册表时用归一化名兜底。"""
    norm = normalize(name)
    if not norm:
        return "unknown"
    for key in _ALIAS_KEYS:
        if key in norm:
            return ALIASES[key]
    # 直接以 canonical id 形式命中
    if norm in MODELS:
        return norm
    return norm


def enrich(name: str) -> dict:
    """补充厂商/国别/开源标签。未命中注册表时给出保守默认值。"""
    cid = canonical_id(name)
    meta = MODELS.get(cid)
    if meta:
        return {
            "id": cid,
            "display_name": meta["name"],
            "vendor": meta["vendor"],
            "region": meta["region"],
            "open": meta["open"],
        }
    return {
        "id": cid,
        "display_name": name,
        "vendor": guess_vendor(name),
        "region": "other",
        "open": None,
    }


def guess_vendor(name: str) -> str:
    """未注册模型按名称猜测厂商（仅用于展示标签，不做跨榜对齐）。"""
    low = (name or "").lower()
    rules = [
        ("gpt", "OpenAI"), ("o4", "OpenAI"), ("o3", "OpenAI"),
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
        ("step", "阶跃星辰"), ("baichuan", "百川智能"),
        ("yi-", "零一万物"), ("sensechat", "商汤"),
        ("mistral", "Mistral AI"),
        ("command", "Cohere"),
    ]
    for kw, vendor in rules:
        if kw in low:
            return vendor
    return "其他"
