#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Artificial Analysis 抓取（Intelligence Index + Blended Price）。

AA 是 Next.js 站点，榜单数据以转义 JSON 形式嵌在首页的 flight payload
（self.__next_f.push(...)）里。没有稳定的官方公开数据文件，因此解析页面：
- Intelligence Index（智能指数，越高越好）
- Blended Price（每百万 token 混合价格，美元，越低越好）

这两组恰好是"性价比象限图"的两个轴。本脚本只读取官方展示值，不做任何
换算或跨榜综合评分。解析模式对 AA 前端改版敏感，失败即降级。

提取锚点（反转义后）：
  "label":"<模型名>","color":"#..","logo":"..","url":"/models/<slug>",
  "value":<数值>,"displayValue":"<展示值>"
价格 series 的 displayValue 带 $ 前缀，据此与 Intelligence Index 区分。
"""

import re

from common import http_get, log, warn, now_utc_iso
from models import normalize

SOURCE_PAGE = "https://artificialanalysis.ai/"
SOURCE_ID = "aa_intelligence"

# 供 fallback 引擎使用的元信息：
# - MIRROR_OK：活源失败时，是否允许走第三方镜像（Wayback）取同一页面 HTML 再解析
# - SOURCE_URL：镜像查询的规范化 URL
MIRROR_OK = True
SOURCE_URL = SOURCE_PAGE

# slug 归一化 -> canonical 名（AA 的 slug 已是标准短横线形式）
_TRIPLE = re.compile(
    r'"label":"([^"]{2,60})","color":"#[0-9a-fA-F]{3,8}",'
    r'"logo":"[^"]*","url":"(/models/[a-z0-9\-]+)",'
    r'"value":([0-9.]+),"displayValue":"([^"]*)"'
)


def _slug_to_name(slug: str) -> str:
    """/models/claude-fable-5-1 -> Claude Fable 5.1 的近似可读名。

    真实展示名以 label 为准，这里仅用于兜底。"""
    base = slug.rsplit("/", 1)[-1]
    return base.replace("-", " ").strip().title()


def _unescape(html_text: str) -> str:
    return html_text.replace('\\"', '"').replace("\\\\", "\\")


def fetch(date_str: str):
    html = http_get(SOURCE_PAGE, timeout=60, max_bytes=6_000_000)
    return parse_html(html, date_str)


def parse_html(html: str, date_str: str, *, channel: str = "html-flight-payload",
               mirror_note: str = None):
    """从 AA 页面 HTML（活源或 Wayback 快照）解析 Intelligence Index + 价格。"""
    s = _unescape(html)
    triples = _TRIPLE.findall(s)
    if not triples:
        raise RuntimeError("AA: 未在 flight payload 中找到任何 series triple")

    intelligence = {}  # slug -> (value, label)
    price = {}         # slug -> (value, label)
    for label, slug, value_s, disp in triples:
        try:
            value = float(value_s)
        except ValueError:
            continue
        if "$" in disp:
            # 价格 series（Blended Price，$/百万 token）
            if slug not in price:
                price[slug] = (value, label)
        else:
            # Intelligence Index：每个 slug 首个非价格值即智能指数
            if slug not in intelligence:
                intelligence[slug] = (value, label)

    if not intelligence:
        raise RuntimeError("AA: 未提取到 Intelligence Index 数据")

    rows = []
    for slug, (value, label) in intelligence.items():
        model_name = _strip_variant(label) or _slug_to_name(slug)
        price_val = price.get(slug, (None,))[0]
        rows.append({
            "model": model_name,
            "slug": slug.rsplit("/", 1)[-1],
            "label": label,                 # 保留 AA 原始展示名（含 (max) 等变体）
            "score": round(value, 2),       # Intelligence Index，原始值
            "price": price_val,             # Blended Price（$/M tokens），可能缺失
        })

    rows.sort(key=lambda r: -r["score"])
    for i, row in enumerate(rows, start=1):
        row["rank"] = i

    log(f"AA: Intelligence Index {len(rows)} 个模型，其中 {sum(1 for r in rows if r['price'] is not None)} 个含价格")
    return {
        "source_id": SOURCE_ID,
        "board": "Artificial Analysis 智能指数榜",
        "metric": "Intelligence Index",
        "kind": "objective_benchmark",
        "source_url": "https://artificialanalysis.ai/text/intelligence-index",
        "dataset_url": SOURCE_PAGE,
        "license": "© Artificial Analysis，本站仅聚合展示",
        "fetched_at": now_utc_iso(),
        "publish_date": date_str,
        "channel": channel,
        "mirror_note": mirror_note,
        "price_unit": "USD per 1M blended tokens",
        "rows": rows,
    }


_VARIANT = re.compile(r"\s*\([^)]*\)\s*$")


def _strip_variant(label: str) -> str:
    """去掉 label 末尾的 (max)/(high) 等推理档位后缀，得到干净模型名。"""
    prev = None
    cur = label or ""
    while prev != cur:
        prev = cur
        cur = _VARIANT.sub("", cur).strip()
    return cur


if __name__ == "__main__":
    import json
    from common import today_str
    result = fetch(today_str())
    print(json.dumps(result["rows"], ensure_ascii=False, indent=1))
