#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""领域层：历史趋势聚合（纯函数，零 IO）。

从 data/raw 的历史快照聚合出排名时间序列，供前端折线图消费。

只使用快照里的原始 rank，不做任何跨日插值或分数换算。快照越多，折线越长。

原实现在 build_trend.py 里直接遍历目录、读文件、写文件，与编排逻辑
耦合。这里把「给定快照列表，算出趋势结构」抽成纯函数，
「怎么拿到快照、写到哪」交给调用方。
"""

TOP_N_PER_BOARD = 12   # 每个榜追踪前 N 名的历史
MAX_POINTS = 60        # 每条折线最多多少个日期点（防止快照过多导致文件膨胀）


def build_trend_series(snapshot_entries, enrich, top_n=TOP_N_PER_BOARD,
                       max_points=MAX_POINTS):
    """从快照列表构建趋势结构。

    Args:
        snapshot_entries: [(date_str, payload), ...]，按日期升序
        enrich: (model_name, organization) -> 主数据 dict
        top_n: 每榜追踪前 N 名
        max_points: 最多回溯多少个快照点

    Returns:
        趋势 dict；快照不足或无有效行时返回 None（调用方跳过该榜）。
    """
    if not snapshot_entries:
        return None

    # 取最新一期，确定要追踪哪些模型
    latest_date, latest = snapshot_entries[-1]
    latest_rows = (latest or {}).get("rows") or []
    if not latest_rows:
        return None

    # 重点模型 = 最新榜按 rank 升序取前 TOP_N（按 canonical id 去重：
    # 主数据折叠后同一模型的不同变体只保留名次最好的那一条）
    tracked, seen = [], set()
    for row in sorted(latest_rows, key=lambda r: r.get("rank", 999)):
        meta = enrich(row.get("model", ""), row.get("organization"))
        cid = row.get("id") or meta["id"]
        if cid in seen:
            continue
        seen.add(cid)
        tracked.append({
            "id": cid,
            "name": row.get("display_name") or meta["display_name"],
            "variant": meta.get("variant"),
            "vendor": meta["vendor"],
            "region": meta["region"],
            "open": meta["open"],
        })
        if len(tracked) >= top_n:
            break
    tracked_ids = {t["id"] for t in tracked}

    # 遍历每个日期，构建 rank 时间序列
    series = {cid: [] for cid in tracked_ids}
    dates = []
    for date_str, snap in snapshot_entries[-max_points:]:
        rows = (snap or {}).get("rows") or []
        rank_by_cid = {}
        for row in rows:
            meta = enrich(row.get("model", ""), row.get("organization"))
            cid = row.get("id") or meta["id"]
            if cid in tracked_ids and isinstance(row.get("rank"), int):
                prev = rank_by_cid.get(cid)
                if prev is None or row["rank"] < prev:   # 多变体取最好名次
                    rank_by_cid[cid] = row["rank"]
        dates.append(date_str)
        for cid in tracked_ids:
            series[cid].append(rank_by_cid.get(cid))  # None = 当期未上榜

    return {
        "board": latest.get("board"),
        "metric": latest.get("metric"),
        "source_url": latest.get("source_url"),
        "dates": dates,
        "models": [{**t, "ranks": series[t["id"]]} for t in tracked],
    }


def build_trend_from_store(store, enrich, read_json, top_n=TOP_N_PER_BOARD,
                           max_points=MAX_POINTS):
    """遍历所有有快照的源，组装完整趋势结构。

    Args:
        store: SnapshotStore（提供 list_sources / list_all）
        read_json: 读文件（注入以保持纯函数）
    """
    trend = {"boards": {}}
    for src in sorted(store.list_sources()):
        entries = store.list_all(src)
        if not entries:
            continue
        loaded = [(d, read_json(p)) for d, p in entries[-max_points:]]
        panel = build_trend_series(loaded, enrich, top_n, max_points)
        if panel:
            trend["boards"][src] = panel
    return trend
