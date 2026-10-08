#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""入口：串行抓取各源 -> 单源降级 -> 写历史快照 -> 对比上期算升降 -> 合并 merged.json。

设计原则（对齐用户需求）：
1. 单源失败不影响整体：每个源 try/except，失败时依次降级为
   (a) 最近一次历史快照  (b) 人工维护数据 data/manual/<source>.json。
2. 字段缺失降级而非报错：各 fetch 脚本内部已对缺失字段填 None。
3. data/raw/<source>_<date>.json 保留每日快照，是趋势折线的真相源。
4. 不修改原始分数、不跨榜计算综合总分：merged.json 只做字段对齐与
   升降对比，各榜分数保持官方口径原样。

运行：python src/main.py
产物：data/raw/*.json（快照）、data/merged.json（前端消费）、data/meta.json
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import (  # noqa: E402
    RAW_DIR, MANUAL_DIR, DATA_DIR, log, warn, today_str, now_utc_iso,
    write_snapshot, write_json, read_json, list_snapshots,
    latest_snapshot_before, load_manual, snapshot_path,
)
from models import enrich, canonical_id  # noqa: E402

import fetch_lmarena  # noqa: E402
import fetch_aa  # noqa: E402
import fetch_livecodebench  # noqa: E402
import fetch_openllm  # noqa: E402
import fetch_superclue  # noqa: E402
import build_trend  # noqa: E402


def _source_ids_for_lmarena():
    return [f"lmarena_{c}" for c in fetch_lmarena.CONFIGS]


# 榜单顺序即前端 tab 顺序；kind 决定「真人偏好 / 客观基准」分区
BOARD_ORDER = [
    "lmarena_text", "aa_intelligence", "superclue",
    "lmarena_webdev", "lmarena_agent", "livecodebench", "open_llm",
]


def _build_task_map(date_str):
    """source_id -> (可调用 fetch 的函数, 是否 lmarena 子集)。

    lmarena 一次抓取产出多个 source_id，这里特殊处理。"""
    tasks = {}

    def lmarena_task():
        return fetch_lmarena.fetch_all(date_str)  # 返回 {source_id: payload}

    tasks["_lmarena_group"] = lmarena_task
    tasks[fetch_aa.SOURCE_ID] = lambda: {fetch_aa.SOURCE_ID: fetch_aa.fetch(date_str)}
    tasks[fetch_livecodebench.SOURCE_ID] = lambda: {fetch_livecodebench.SOURCE_ID: fetch_livecodebench.fetch(date_str)}
    tasks[fetch_openllm.SOURCE_ID] = lambda: {fetch_openllm.SOURCE_ID: fetch_openllm.fetch(date_str)}
    tasks[fetch_superclue.SOURCE_ID] = lambda: {fetch_superclue.SOURCE_ID: fetch_superclue.fetch(date_str)}
    return tasks


def _fallback_payload(source_id, date_str):
    """降级：先找最近历史快照，再找人工数据。返回 payload 或 None。"""
    prev_date, prev = latest_snapshot_before(source_id, date_str)
    if prev and prev.get("rows"):
        log(f"降级[{source_id}] -> 使用 {prev_date} 历史快照（{len(prev['rows'])} 行）")
        prev = dict(prev)
        prev["stale"] = True
        prev["stale_from"] = prev_date
        return prev
    manual = load_manual(source_id)
    if manual and manual.get("rows"):
        log(f"降级[{source_id}] -> 使用人工维护数据（{len(manual['rows'])} 行）")
        manual = dict(manual)
        manual["stale"] = True
        manual["manual"] = True
        return manual
    return None


def _add_trend(payload, source_id, date_str):
    """对比上期快照，给每行加 trend（rank 变化）与 is_new 标记。不改动分数。"""
    prev_date, prev = latest_snapshot_before(source_id, date_str)
    prev_rank = {}
    if prev and prev.get("rows"):
        for r in prev["rows"]:
            cid = canonical_id(r.get("model", ""))
            if isinstance(r.get("rank"), int):
                prev_rank[cid] = r["rank"]

    for row in payload["rows"]:
        cid = canonical_id(row.get("model", ""))
        row["id"] = cid
        meta = enrich(row.get("model", ""))
        row["display_name"] = meta["display_name"]
        row["vendor"] = row.get("organization") or meta["vendor"]
        row["region"] = meta["region"]
        row["open"] = meta["open"]
        if prev_rank:
            if cid in prev_rank:
                row["trend"] = prev_rank[cid] - row["rank"]  # 正数=上升
                row["is_new"] = False
            else:
                row["trend"] = 0
                row["is_new"] = True
        else:
            row["trend"] = 0
            row["is_new"] = False
    payload["compared_with"] = prev_date
    return payload


def main():
    date_str = today_str()
    os.makedirs(RAW_DIR, exist_ok=True)
    os.makedirs(MANUAL_DIR, exist_ok=True)
    log(f"=== AI 模型排行榜数据抓取开始 {date_str} (UTC) ===")

    tasks = _build_task_map(date_str)
    collected = {}   # source_id -> payload
    failures = []    # 记录失败与降级情况

    for task_key, fn in tasks.items():
        try:
            result = fn()  # {source_id: payload}
        except Exception as exc:  # noqa: BLE001
            warn(f"[{task_key}] 抓取失败: {exc}")
            # 该组下所有 source_id 各自降级
            group_ids = _source_ids_for_lmarena() if task_key == "_lmarena_group" else [task_key]
            for sid in group_ids:
                fb = _fallback_payload(sid, date_str)
                if fb:
                    collected[sid] = _add_trend(fb, sid, date_str)
                    failures.append({"source": sid, "status": "fallback", "error": str(exc)})
                else:
                    failures.append({"source": sid, "status": "failed", "error": str(exc)})
            continue

        # 成功：写快照 + 加 trend
        for sid, payload in result.items():
            write_snapshot(sid, payload, date_str)
            collected[sid] = _add_trend(payload, sid, date_str)

        # lmarena 组内若个别子集失败，补充降级
        if task_key == "_lmarena_group":
            for sid in _source_ids_for_lmarena():
                if sid not in collected:
                    fb = _fallback_payload(sid, date_str)
                    if fb:
                        collected[sid] = _add_trend(fb, sid, date_str)
                        failures.append({"source": sid, "status": "fallback"})

    if not collected:
        warn("所有数据源均失败，保留旧的 merged.json，不覆盖。")
        write_json(os.path.join(DATA_DIR, "meta.json"), {
            "generated_at": now_utc_iso(),
            "status": "all_failed",
            "failures": failures,
        })
        return

    merged = build_merged(collected, date_str, failures)
    write_json(os.path.join(DATA_DIR, "merged.json"), merged)

    # 从历史快照聚合趋势数据（供前端折线图消费）
    try:
        build_trend.build_trend()
    except Exception as exc:  # noqa: BLE001
        warn(f"趋势聚合失败（不影响主数据）: {exc}")

    write_json(os.path.join(DATA_DIR, "meta.json"), {
        "generated_at": merged["generated_at"],
        "status": "ok" if not failures else "partial",
        "boards": list(merged["boards"].keys()),
        "failures": failures,
    })

    log(f"=== 完成：{len(merged['boards'])} 个榜单，模型交叉对比 "
        f"{len(merged.get('cross', []))} 个；失败/降级 {len(failures)} 项 ===")


def build_merged(collected, date_str, failures):
    """把各源 payload 组织成前端直接消费的 merged.json，并构建跨榜对比。"""
    boards = {}
    # 统一 board meta（顺序按 BOARD_ORDER，未知的排后面）
    ordered = [b for b in BOARD_ORDER if b in collected]
    ordered += [b for b in collected if b not in BOARD_ORDER]
    for sid in ordered:
        payload = collected[sid]
        boards[sid] = {
            "board": payload.get("board"),
            "metric": payload.get("metric"),
            "kind": payload.get("kind"),
            "source_url": payload.get("source_url"),
            "dataset_url": payload.get("dataset_url"),
            "license": payload.get("license"),
            "fetched_at": payload.get("fetched_at"),
            "publish_date": payload.get("publish_date"),
            "compared_with": payload.get("compared_with"),
            "stale": payload.get("stale", False),
            "manual": payload.get("manual", False),
            "manual_note": payload.get("manual_note"),
            "retired": payload.get("retired", False),
            "retired_note": payload.get("retired_note"),
            "price_unit": payload.get("price_unit"),
            "rows": payload.get("rows", []),
        }

    cross = build_cross(collected)

    return {
        "generated_at": now_utc_iso(),
        "date": date_str,
        "disclaimer": (
            "本站为第三方数据聚合展示，所有分数与排名均来自 LMArena / Artificial Analysis / "
            "SuperCLUE / LiveCodeBench / Hugging Face 等原始榜单，本站不修改任何分数，"
            "也不自行计算跨榜综合总分。各榜单评测口径不同，分数不可直接横向比较，跨榜对比"
            "仅用于观察同一模型在不同方法论下的相对表现。"
        ),
        "boards": boards,
        "cross": cross,
        "failures": failures,
    }


def build_cross(collected):
    """跨榜同屏对比：以 canonical id 聚合每个模型在各榜的排名/分数。

    注意：这里只做「并列展示各榜原始名次与分数」，绝不加总、不排序成一个
    综合分，严格避免跨榜口径混算。"""
    # 参与交叉对比的三类代表榜：真人偏好(lmarena_text)、客观基准(aa)、中文(superclue)
    focus = ["lmarena_text", "aa_intelligence", "superclue",
             "lmarena_webdev", "livecodebench", "open_llm"]
    acc = {}  # cid -> {display_name, vendor, region, open, appearances:{sid:{rank,score}}}
    for sid in focus:
        payload = collected.get(sid)
        if not payload:
            continue
        for row in payload.get("rows", []):
            cid = row.get("id") or canonical_id(row.get("model", ""))
            if cid not in acc:
                meta = enrich(row.get("model", ""))
                acc[cid] = {
                    "id": cid,
                    "display_name": row.get("display_name") or meta["display_name"],
                    "vendor": row.get("vendor") or meta["vendor"],
                    "region": meta["region"],
                    "open": meta["open"],
                    "appearances": {},
                }
            acc[cid]["appearances"][sid] = {
                "rank": row.get("rank"),
                "score": row.get("score"),
                "metric": payload.get("metric"),
                "is_new": row.get("is_new", False),
                "trend": row.get("trend", 0),
            }

    # 只保留出现在 >=2 个榜的模型才有"交叉对比"意义，但 1 个也留着供浏览
    cross = [v for v in acc.values() if v["appearances"]]
    # 按出现榜单数降序、再按 lmarena_text 名次升序，方便前端默认展示
    cross.sort(key=lambda m: (
        -len(m["appearances"]),
        m["appearances"].get("lmarena_text", {}).get("rank", 999),
        m["display_name"],
    ))
    return cross


if __name__ == "__main__":
    main()
