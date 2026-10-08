#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""趋势聚合：从 data/raw/<source>_<date>.json 历史快照生成 data/trend.json。

前端的历史趋势折线读这个文件。逻辑：对每个榜单，按日期遍历所有快照，
取出重点模型（默认各榜最新一期 Top N）在每个日期的 rank，形成时间序列。

只使用快照里的原始 rank，不做任何跨日插值或分数换算。快照越多，折线越长。
"""

import os

from common import (
    RAW_DIR, DATA_DIR, list_snapshots, read_json, write_json, log, warn,
)
from models import canonical_id

TOP_N_PER_BOARD = 12   # 每个榜追踪前 N 名的历史
MAX_POINTS = 60        # 每条折线最多多少个日期点（防止快照过多导致文件膨胀）


def build_trend():
    if not os.path.isdir(RAW_DIR):
        warn("无 raw 快照目录，跳过趋势聚合")
        return None

    # 收集所有出现过的 source_id
    sources = set()
    for fname in os.listdir(RAW_DIR):
        if not fname.endswith(".json") or "_" not in fname:
            continue
        src = fname.rsplit("_", 1)[0]
        sources.add(src)

    trend = {"boards": {}}
    for src in sorted(sources):
        snaps = list_snapshots(src)
        if not snaps:
            continue
        # 取最新一期，确定要追踪哪些模型
        latest_date, latest_path = snaps[-1]
        latest = read_json(latest_path, {})
        latest_rows = latest.get("rows", []) if isinstance(latest, dict) else []
        if not latest_rows:
            continue

        # 重点模型 = 最新榜按 rank 升序取前 TOP_N
        tracked = []
        for row in sorted(latest_rows, key=lambda r: r.get("rank", 999))[:TOP_N_PER_BOARD]:
            cid = row.get("id") or canonical_id(row.get("model", ""))
            tracked.append({
                "id": cid,
                "name": row.get("display_name") or row.get("model"),
                "vendor": row.get("vendor"),
                "region": row.get("region"),
            })
        tracked_ids = {t["id"] for t in tracked}

        # 遍历每个日期，构建 rank 时间序列
        series = {cid: [] for cid in tracked_ids}
        dates = []
        for date_str, path in snaps[-MAX_POINTS:]:
            snap = read_json(path, {})
            rows = snap.get("rows", []) if isinstance(snap, dict) else []
            rank_by_cid = {}
            for row in rows:
                cid = row.get("id") or canonical_id(row.get("model", ""))
                if cid in tracked_ids and isinstance(row.get("rank"), int):
                    rank_by_cid[cid] = row["rank"]
            dates.append(date_str)
            for cid in tracked_ids:
                series[cid].append(rank_by_cid.get(cid))  # None = 当期未上榜

        trend["boards"][src] = {
            "board": latest.get("board"),
            "metric": latest.get("metric"),
            "source_url": latest.get("source_url"),
            "dates": dates,
            "models": [
                {**t, "ranks": series[t["id"]]}
                for t in tracked
            ],
        }

    trend["generated_from"] = "data/raw snapshots"
    write_json(os.path.join(DATA_DIR, "trend.json"), trend)
    log(f"趋势聚合完成：{len(trend['boards'])} 个榜单")
    return trend


if __name__ == "__main__":
    build_trend()
