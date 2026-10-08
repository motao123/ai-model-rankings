#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""LMArena / Arena.ai（原 Chatbot Arena，LMSYS）真人盲测榜抓取。

数据来源：官方 Hugging Face 数据集 lmarena-ai/leaderboard-dataset（CC-BY-4.0）。
子集即各 Arena：
- text              文本总榜（Bradley-Terry 评分）
- webdev            Code Arena / WebDev 前端榜
- agent             Agent Arena
- text_style_control 风格控制文本榜

抓取策略（按优先级）：
1. HF datasets-server REST API（免下载整库，最稳）
2. 直接下载 data/<config>/<split>/0000.parquet 并解析（datasets-server 挂掉时兜底）
两者都失败 -> 抛错，由 main.py 降级到最近快照或人工数据。

schema: model_name, organization, license, rating, rating_lower, rating_upper,
        variance, vote_count, rank, category, leaderboard_publish_date
（agent 子集字段为 score / score_ci_* / observation_count / session_count）
"""

import io
import json

from common import http_get, log, warn, now_utc_iso

DATASET = "lmarena-ai/leaderboard-dataset"
HF_DATASETS_SERVER = "https://datasets-server.huggingface.co"
HF_RESOLVE = f"https://huggingface.co/datasets/{DATASET}/resolve/main/refs%2Fconvert%2Fparquet"

SOURCE_PAGE = "https://lmarena.ai/leaderboard"

# 本站收录的子榜：config -> (榜单标题, 指标名)
CONFIGS = {
    "text": ("LMArena 文本总榜（真人盲测）", "Arena Score"),
    "webdev": ("Code Arena / WebDev 榜（真人盲测）", "Arena Score"),
    "agent": ("Agent Arena 榜（真人盲测）", "IPS Score"),
}


def _fetch_via_api(config: str):
    """datasets-server /rows 分页拉取 split=latest、category=overall 的行。"""
    rows, offset, page_len = [], 0, 100
    while True:
        url = (
            f"{HF_DATASETS_SERVER}/rows?dataset={DATASET.replace('/', '%2F')}"
            f"&config={config}&split=latest&offset={offset}&length={page_len}"
        )
        data = http_get(url, as_json=True)
        batch = data.get("rows") or []
        for item in batch:
            rows.append(item.get("row", item))
        total = data.get("num_rows_total", 0)
        offset += len(batch)
        if not batch or offset >= total:
            break
        if offset > 2000:  # 保险丝：latest 不应该这么大
            break
    return rows


def _fetch_via_parquet(config: str):
    """直接下载转换后的 parquet 文件（需要 pyarrow；未安装则跳过）。"""
    try:
        import pyarrow.parquet as pq
    except ImportError:
        warn("pyarrow 未安装，跳过 parquet 兜底通道")
        return []
    url = f"{HF_RESOLVE}/{config}/latest/0000.parquet"
    content = http_get(url)
    if isinstance(content, str):
        content = content.encode("utf-8", errors="ignore")
    table = pq.read_table(io.BytesIO(content))
    return table.to_pylist()


def _clean_row(row: dict, config: str, rank_seq: list):
    """统一字段；容忍 agent 子集与普通子集的差异；字段缺失降级为 None 而非报错。"""
    model = row.get("model_name") or row.get("model") or ""
    if not model:
        return None
    score = row.get("rating")
    if score is None:
        score = row.get("score")  # agent 子集
    category = row.get("category") or "overall"
    # 只保留总榜口径，避免把 coding/math 等子分类混入（不同榜单口径不可比）
    if category not in ("overall", "agent") and config != "agent":
        return None
    try:
        score_val = float(score) if score is not None else None
    except (TypeError, ValueError):
        score_val = None
    rank_seq.append(model)
    return {
        "model": model,
        "organization": row.get("organization"),
        "license": row.get("license"),
        "score": score_val,
        "votes": row.get("vote_count"),
        "rank_src": row.get("rank"),
        "publish_date": row.get("leaderboard_publish_date"),
        "category": category,
    }


def fetch_config(config: str, date_str: str):
    """抓单个子榜。返回统一结构 dict，失败抛 RuntimeError。"""
    title, metric = CONFIGS[config]
    rows = _fetch_via_api(config)
    channel = "hf-datasets-server"
    if not rows:
        rows = _fetch_via_parquet(config)
        channel = "hf-parquet"
    if not rows:
        raise RuntimeError(f"LMArena {config}: 两条通道均无数据")

    rank_seq = []
    cleaned = []
    for row in rows:
        item = _clean_row(row, config, rank_seq)
        if item:
            cleaned.append(item)

    # 源 rank 缺失时按分数补排（不改动分数本身）
    cleaned.sort(key=lambda r: (r["score"] is None, -(r["score"] or 0)))
    final = []
    for i, item in enumerate(cleaned, start=1):
        item["rank"] = item["rank_src"] if isinstance(item["rank_src"], int) else i
        item.pop("rank_src", None)
        final.append(item)

    if not final:
        raise RuntimeError(f"LMArena {config}: 清洗后无有效行")

    log(f"LMArena/{config}: 获取 {len(final)} 个模型（通道 {channel}）")
    return {
        "source_id": f"lmarena_{config}",
        "board": title,
        "metric": metric,
        "kind": "human_preference",  # 真人偏好类
        "source_url": SOURCE_PAGE,
        "dataset_url": f"https://huggingface.co/datasets/{DATASET}",
        "license": "CC-BY-4.0",
        "fetched_at": now_utc_iso(),
        "publish_date": final[0].get("publish_date"),
        "channel": channel,
        "rows": final,
    }


def fetch_all(date_str: str):
    """抓全部子榜；单个子榜失败不影响其他。返回 {source_id: payload}。"""
    out = {}
    for config in CONFIGS:
        try:
            payload = fetch_config(config, date_str)
            out[payload["source_id"]] = payload
        except Exception as exc:  # noqa: BLE001
            warn(f"LMArena/{config} 抓取失败: {exc}")
    if not out:
        raise RuntimeError("LMArena 全部子榜抓取失败")
    return out


if __name__ == "__main__":
    from common import today_str
    result = fetch_all(today_str())
    print(json.dumps({k: v["rows"][:3] for k, v in result.items()},
                     ensure_ascii=False, indent=1))
