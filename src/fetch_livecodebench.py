#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""LiveCodeBench 编程榜抓取（官方静态 JSON，最稳）。

数据来源：https://livecodebench.github.io/performances_generation.json
官方逐题 pass@1 明细（question_id / model / date / difficulty / pass@1 / platform），
本脚本按模型聚合出平均分（不修改任何原始分数，仅做官方口径的平均，
与 livecodebench.github.io 页面的 Avg. pass@1 展示逻辑一致）。

文件较大（约 7MB），下载超时放宽；失败抛错由 main.py 降级。
"""

import json
from collections import defaultdict

from common import http_get, log, warn, now_utc_iso

DATA_URL = "https://livecodebench.github.io/performances_generation.json"
SOURCE_PAGE = "https://livecodebench.github.io/leaderboard.html"

SOURCE_ID = "livecodebench"


def fetch(date_str: str):
    raw = http_get(DATA_URL, as_json=True, timeout=120)
    performances = raw.get("performances") or []
    if not performances:
        raise RuntimeError("LiveCodeBench: performances 为空")

    # 官方页面口径：每个模型取全部题目 pass@1 的算术平均（generation 赛道）
    agg = defaultdict(list)
    latest_ts = 0
    for item in performances:
        model = item.get("model")
        score = item.get("pass@1")
        if model is None or score is None:
            continue
        try:
            agg[model].append(float(score))
        except (TypeError, ValueError):
            continue
        ts = item.get("date") or 0
        if isinstance(ts, (int, float)) and ts > latest_ts:
            latest_ts = ts

    if not agg:
        raise RuntimeError("LiveCodeBench: 聚合后无有效模型")

    rows = []
    for model, scores in agg.items():
        rows.append({
            "model": model,
            "organization": None,   # 官方 JSON 不含厂商，由 models.py 补齐
            "score": round(sum(scores) / len(scores), 2),
            "n_questions": len(scores),
        })
    rows.sort(key=lambda r: -r["score"])
    for i, row in enumerate(rows, start=1):
        row["rank"] = i

    publish_date = None
    if latest_ts:
        import datetime
        publish_date = datetime.datetime.fromtimestamp(
            latest_ts / 1000, datetime.timezone.utc).strftime("%Y-%m-%d")

    log(f"LiveCodeBench: 聚合 {len(rows)} 个模型（共 {len(performances)} 条逐题记录）")
    return {
        "source_id": SOURCE_ID,
        "board": "LiveCodeBench 编程榜（防污染滚动更新）",
        "metric": "Avg. pass@1 (%)",
        "kind": "objective_benchmark",  # 客观基准类
        "source_url": SOURCE_PAGE,
        "dataset_url": DATA_URL,
        "license": "官方公开数据",
        "fetched_at": now_utc_iso(),
        "publish_date": publish_date,
        "channel": "official-json",
        "rows": rows,
    }


if __name__ == "__main__":
    from common import today_str
    result = fetch(today_str())
    print(json.dumps(result["rows"][:5], ensure_ascii=False, indent=1))
