#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SuperCLUE 中文榜抓取。

SuperCLUE（superclueai.com）是 Vue SPA，榜单数据通过混淆后的 /api/chores/ 接口
动态加载，端点不稳定。策略：
1. 依次尝试若干候选 JSON 端点（带 Referer / XHR 头）；
2. 兜底解析渲染后的 HTML 表格；
3. 全部失败 -> 抛错，由 main.py 降级到 data/manual/superclue.json
   （人工按 SuperCLUE 官方月度报告维护，页面会标注"人工更新"）。

本脚本不修改任何分数，只搬运官方展示值。
"""

import json
import re

from common import http_get, log, warn, now_utc_iso

SOURCE_PAGE = "https://www.superclueai.com/benchmark-list"
SOURCE_ID = "superclue"

# 候选数据端点（baseURL 来自前端 bundle：/api/chores/）
CANDIDATE_ENDPOINTS = [
    "https://www.superclueai.com/api/chores/benchmark-list",
    "https://www.superclueai.com/api/chores/benchmarklist",
    "https://www.superclueai.com/api/chores/rank-list",
    "https://www.superclueai.com/api/chores/general-list",
]
XHR_HEADERS = {
    "Accept": "application/json,text/plain,*/*",
    "Referer": SOURCE_PAGE,
    "X-Requested-With": "XMLHttpRequest",
}


def _try_endpoints():
    for url in CANDIDATE_ENDPOINTS:
        for method in ("GET",):
            try:
                data = http_get(url, as_json=True, timeout=25, headers=XHR_HEADERS)
            except Exception:
                continue
            rows = _extract_rows(data)
            if rows:
                log(f"SuperCLUE: 端点命中 {url}，{len(rows)} 条")
                return rows
    return None


def _extract_rows(data):
    """从各种可能的 JSON 结构里提取 (model, vendor, score) 行。字段名做宽松匹配。"""
    if not isinstance(data, dict):
        return None
    # 常见包装：{code,data:{list:[...]}} / {data:[...]} / {list:[...]}
    candidates = []
    for key in ("list", "rows", "records", "data", "result", "benchmarkList"):
        node = data.get(key)
        if isinstance(node, list):
            candidates.append(node)
        elif isinstance(node, dict):
            for k2 in ("list", "rows", "records", "data"):
                if isinstance(node.get(k2), list):
                    candidates.append(node[k2])
    for arr in candidates:
        rows = []
        for item in arr:
            if not isinstance(item, dict):
                continue
            model = _first(item, ["model", "modelName", "name", "model_name", "title"])
            vendor = _first(item, ["vendor", "org", "organization", "company", "institution", "factory"])
            score = _first(item, ["score", "totalScore", "total", "value", "rank_score"])
            if model is None:
                continue
            try:
                score_val = float(score) if score is not None else None
            except (TypeError, ValueError):
                score_val = None
            rows.append({"model": str(model), "organization": vendor, "score": score_val})
        if rows:
            return rows
    return None


def _first(d, keys):
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return None


def _try_html():
    """兜底：解析渲染后 HTML 表格（多数情况下 SPA 首屏无表格，成功率低）。"""
    try:
        html = http_get(SOURCE_PAGE, timeout=30)
    except Exception as exc:
        warn(f"SuperCLUE HTML 抓取失败: {exc}")
        return None
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    for tr in soup.select("table tbody tr"):
        cells = [td.get_text(strip=True) for td in tr.find_all("td")]
        if len(cells) >= 3:
            score = None
            for c in reversed(cells):
                try:
                    score = float(c.replace(",", ""))
                    break
                except ValueError:
                    continue
            if score is not None:
                rows.append({"model": cells[1] if cells[0].isdigit() else cells[0],
                             "organization": cells[2] if len(cells) > 2 else None,
                             "score": score})
    return rows or None


def fetch(date_str: str):
    rows = _try_endpoints() or _try_html()
    if not rows:
        raise RuntimeError("SuperCLUE: 所有自动通道失败，需降级到人工数据")

    rows = [r for r in rows if r.get("score") is not None]
    rows.sort(key=lambda r: -r["score"])
    for i, row in enumerate(rows, start=1):
        row["rank"] = i

    log(f"SuperCLUE: 自动抓取 {len(rows)} 个模型")
    return {
        "source_id": SOURCE_ID,
        "board": "SuperCLUE 中文大模型综合榜",
        "metric": "综合得分",
        "kind": "objective_benchmark",
        "source_url": SOURCE_PAGE,
        "dataset_url": "https://www.superclueai.com/",
        "license": "© SuperCLUE，本站仅聚合展示",
        "fetched_at": now_utc_iso(),
        "publish_date": date_str,
        "channel": "auto",
        "rows": rows,
    }


if __name__ == "__main__":
    from common import today_str
    print(json.dumps(fetch(today_str())["rows"], ensure_ascii=False, indent=1))
