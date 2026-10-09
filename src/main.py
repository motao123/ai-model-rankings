#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""入口：串行抓取各源 -> 契约熔断 -> 多层降级 -> 写历史快照 -> 对比上期算升降 -> 合并 merged.json。

设计原则（对齐用户需求）：
1. 单源失败不影响整体：每个源 try/except。降级链按可信度排序，逐层尝试：
   (a) 第三方镜像快照（Internet Archive，独立信任域）
   (b) LKG 最后已知良好（仅记录通过契约的批次）
   (c) 最近历史快照  (d) 人工维护数据 data/manual/<source>.json
2. 数据契约熔断：实时结果先过契约（行数下限/跌幅/分数完整度），
   不合格视为失败、不落盘、不晋级 LKG —— 坏数据永不进入展示层。
3. 字段缺失降级而非报错：各 fetch 脚本内部已对缺失字段填 None。
4. data/raw/<source>_<date>.json 保留每日快照，是趋势折线的真相源。
5. 不修改原始分数、不跨榜计算综合总分：merged.json 只做字段对齐、
   升降对比与方法论分组的"共识置信度"标签。

运行：python src/main.py
产物：data/raw/*.json（快照）、data/merged.json（前端消费）、data/meta.json、
     data/state/lkg.json（最后已知良好）、data/state/failures.json（降级报告）
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
import fallback as fb_engine  # noqa: E402

import fetch_lmarena  # noqa: E402
import fetch_aa  # noqa: E402
import fetch_livecodebench  # noqa: E402
import fetch_openllm  # noqa: E402
import fetch_superclue  # noqa: E402
import build_trend  # noqa: E402


# 声明"支持第三方镜像通道"的源：活源失败时可用 Wayback 快照重解析。
# 数据集型源（HF datasets-server）无对应镜像页面，故不登记。
_MIRROR_REGISTRY = {
    fetch_aa.SOURCE_ID: fetch_aa,
}

# 方法论分组：用于"多源交叉置信度"，绝不做跨榜分数运算
METHOD_GROUPS = {
    "lmarena_text": "human", "lmarena_webdev": "human", "lmarena_agent": "human",
    "aa_intelligence": "objective", "livecodebench": "objective", "open_llm": "objective",
    "superclue": "chinese",
}

# 跨榜对比只呈现「至少出现在 N 个榜」的模型：单榜模型信息量低、会把长尾原始 ID
# 淹没主表；它们仍完整保留在各自的分榜明细里。
CROSS_MIN_BOARDS = 2

# 默认代表榜优先级（用于同分排序与前端默认并列列）
_PREF_BOARDS = ["lmarena_text", "aa_intelligence", "superclue", "lmarena_webdev"]


def _source_ids_for_lmarena():
    return [f"lmarena_{c}" for c in fetch_lmarena.CONFIGS]


# 榜单顺序即前端 tab 顺序；kind 决定「真人偏好 / 客观基准」分区
BOARD_ORDER = [
    "lmarena_text", "aa_intelligence", "superclue",
    "lmarena_webdev", "lmarena_agent", "livecodebench", "open_llm",
]


def _build_task_map(date_str):
    """返回 {task_key: 无参可调用}，调用后得到 {source_id: payload}。

    lmarena 一次抓取产出多个 source_id，用 "_lmarena_group" 聚合处理。"""
    tasks = {}

    def lmarena_task():
        return fetch_lmarena.fetch_all(date_str)  # 返回 {source_id: payload}

    tasks["_lmarena_group"] = lmarena_task
    tasks[fetch_aa.SOURCE_ID] = lambda: {fetch_aa.SOURCE_ID: fetch_aa.fetch(date_str)}
    tasks[fetch_livecodebench.SOURCE_ID] = lambda: {fetch_livecodebench.SOURCE_ID: fetch_livecodebench.fetch(date_str)}
    tasks[fetch_openllm.SOURCE_ID] = lambda: {fetch_openllm.SOURCE_ID: fetch_openllm.fetch(date_str)}
    tasks[fetch_superclue.SOURCE_ID] = lambda: {fetch_superclue.SOURCE_ID: fetch_superclue.fetch(date_str)}
    return tasks


def _prev_payload_for_check(source_id, date_str):
    """契约校验的比较基准：优先用 LKG（已通过契约），否则用最近历史快照。"""
    got = fb_engine.lkg_payload(source_id)
    if got:
        return got[0]
    _, prev = latest_snapshot_before(source_id, date_str)
    return prev


def _mirror_payload(source_id, date_str):
    """B 层：第三方镜像（Internet Archive）。仅对登记在册的 HTML 源启用。"""
    mod = _MIRROR_REGISTRY.get(source_id)
    if not mod or not getattr(mod, "MIRROR_OK", False):
        return None
    src_url = getattr(mod, "SOURCE_URL", None)
    if not src_url:
        return None
    snap = fb_engine.wayback_fetch_text(src_url)
    if not snap:
        return None
    try:
        payload = mod.parse_html(
            snap["html"], date_str,
            channel="wayback-mirror",
            mirror_note=f"活源失败，取自 Internet Archive 快照 {snap['timestamp']}",
        )
    except Exception as exc:  # noqa: BLE001
        warn(f"镜像[{source_id}] 解析失败: {exc}")
        return None
    return payload


def _fallback_payload(source_id, date_str):
    """替代降级链（按可信度排序，全部独立于"活源成功"这一前提）：

      1. mirror   第三方镜像快照（独立信任域，与本站无关）
      2. lkg      最后已知良好（通过契约的批次，可信度高于"最近快照"）
      3. snapshot 最近历史快照（兼容原方案）
      4. manual   人工维护数据（页面明确标注）

    返回 (payload, layer)；全部不可用返回 (None, None)。
    """
    # 1) 镜像通道
    mir = _mirror_payload(source_id, date_str)
    if mir and mir.get("rows"):
        mir["stale"] = True
        mir["stale_from"] = date_str
        log(f"降级[{source_id}] -> 第三方镜像快照（{len(mir['rows'])} 行）")
        return mir, "mirror"

    # 2) LKG：最后已知良好
    got = fb_engine.lkg_payload(source_id)
    if got:
        payload, lkg_date = got
        payload = dict(payload)
        payload["stale"] = True
        payload["stale_from"] = lkg_date
        payload["channel"] = "lkg"
        log(f"降级[{source_id}] -> LKG 最后已知良好（{lkg_date}，{len(payload['rows'])} 行）")
        return payload, "lkg"

    # 3) 最近历史快照
    prev_date, prev = latest_snapshot_before(source_id, date_str)
    if prev and prev.get("rows"):
        prev = dict(prev)
        prev["stale"] = True
        prev["stale_from"] = prev_date
        prev["channel"] = "snapshot"
        log(f"降级[{source_id}] -> {prev_date} 历史快照（{len(prev['rows'])} 行）")
        return prev, "snapshot"

    # 4) 人工数据
    manual = load_manual(source_id)
    if manual and manual.get("rows"):
        manual = dict(manual)
        manual["stale"] = True
        manual["manual"] = True
        manual["channel"] = "manual"
        manual["stale_from"] = manual.get("publish_date")
        log(f"降级[{source_id}] -> 人工维护数据（{len(manual['rows'])} 行）")
        return manual, "manual"

    return None, None


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
        raw_name = row.get("model", "")
        # 厂商以「模型主数据（注册表 / 机构 slug 归一）」为准，原始 slug 另存
        # vendor_raw 供追溯。修复原实现 row.vendor = organization 导致
        # openai / OpenAI / zai / HF 用户名等脏值直接进展示层的问题。
        meta = enrich(raw_name, row.get("organization"))
        cid = meta["id"]
        row["id"] = cid
        row["display_name"] = meta["display_name"]
        row["vendor"] = meta["vendor"]
        row["vendor_raw"] = row.get("organization") or None
        row["region"] = meta["region"]
        row["open"] = meta["open"]
        row["variant"] = meta.get("variant")
        row["registered"] = meta.get("registered", False)
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


def _degrade(source_id, date_str, error, failures, collected, status="fallback"):
    """执行降级链并把结果记入 collected / failures。"""
    payload, layer = _fallback_payload(source_id, date_str)
    if payload:
        collected[source_id] = _add_trend(payload, source_id, date_str)
        failures.append({"source": source_id, "status": status,
                         "layer": layer, "error": error})
    else:
        failures.append({"source": source_id, "status": "failed", "error": error})


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
                _degrade(sid, date_str, f"抓取异常: {exc}", failures, collected)
            continue

        # 成功：先过数据契约（熔断）。不合格视为失败，不落盘、不晋级，
        # 直接进入降级链——坏数据永不进入展示层。
        for sid, payload in result.items():
            prev = _prev_payload_for_check(sid, date_str)
            ok, reasons = fb_engine.check_contract(sid, payload, prev)
            if not ok:
                warn(f"[{sid}] 数据契约不通过: {'; '.join(reasons)}")
                _degrade(sid, date_str, "契约不通过: " + "; ".join(reasons),
                         failures, collected, status="degraded")
                continue
            write_snapshot(sid, payload, date_str)
            fb_engine.promote_lkg(sid, payload, date_str)
            collected[sid] = _add_trend(payload, sid, date_str)

        # lmarena 组内若个别子集失败，补充降级
        if task_key == "_lmarena_group":
            for sid in _source_ids_for_lmarena():
                if sid not in collected:
                    _degrade(sid, date_str, "组内子集缺失", failures, collected)

    # 降级/失败情况落盘（供工作流自动开 Issue 与前端横幅展示）
    fb_engine.write_failures(failures, date_str)

    if not collected:
        warn("所有数据源均失败，保留旧的 merged.json，不覆盖。")
        write_json(os.path.join(DATA_DIR, "meta.json"), {
            "generated_at": now_utc_iso(),
            "status": "all_failed",
            "degraded": len(failures),
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
        "degraded": len([f for f in failures
                         if f.get("status") in ("fallback", "degraded", "failed")]),
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
            "stale_from": payload.get("stale_from"),
            "stale_days": fb_engine.stale_days(payload) if payload.get("stale") else 0,
            "channel": payload.get("channel"),
            "mirror_note": payload.get("mirror_note"),
            "manual": payload.get("manual", False),
            "manual_note": payload.get("manual_note"),
            "retired": payload.get("retired", False),
            "retired_note": payload.get("retired_note"),
            "price_unit": payload.get("price_unit"),
            "rows": payload.get("rows", []),
        }

    cross, cross_meta = build_cross(collected)

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
        "cross_meta": cross_meta,
        "failures": failures,
    }


def _best_rank(model):
    """代表名次：优先取代表榜的名次，都没有则取全部名次里的最好值。"""
    for sid in _PREF_BOARDS:
        ap = model["appearances"].get(sid)
        if ap and isinstance(ap.get("rank"), int):
            return ap["rank"]
    ranks = [a.get("rank") for a in model["appearances"].values()
             if isinstance(a.get("rank"), int)]
    return min(ranks) if ranks else 9999


def build_cross(collected):
    """跨榜同屏对比：以 canonical id 聚合每个模型在各榜的表现。

    返回 (cross, cross_meta)。

    只做「并列展示各榜原始名次与分数」，绝不加总、不合成综合分。
    - 同一模型在同一榜的不同变体（`-high` / `-max` / `(thinking)` / 日期戳）
      通过模型主数据折叠为同一实体，取**最好名次**，变体名记入
      appearances[sid]['variant']；榜单原始快照不被修改。
    - 仅收录出现在 >= CROSS_MIN_BOARDS 个榜的模型；单榜模型不在此表，
      但仍完整保留在分榜明细中（cross_meta 里给出数量）。
    """
    order = [b for b in BOARD_ORDER if b in collected]
    order += [b for b in collected if b not in BOARD_ORDER]

    acc = {}  # cid -> 聚合项
    for sid in order:
        payload = collected.get(sid)
        if not payload:
            continue
        for row in payload.get("rows", []):
            # id 一律由模型主数据重算（不信任 row["id"]），确保同一模型无论来自
            # 哪个榜/哪个变体都落到同一 key，且 id 与 display_name 恒一致。
            meta = enrich(row.get("model", ""), row.get("organization"))
            cid = meta["id"]
            v = acc.get(cid)
            if v is None:
                v = {
                    "id": cid,
                    "display_name": meta["display_name"],
                    "vendor": meta["vendor"],
                    "region": meta["region"],
                    "open": meta["open"],
                    "registered": meta["registered"],
                    "variants": [],
                    "appearances": {},
                }
                acc[cid] = v
            var = meta.get("variant")
            if var and var not in v["variants"]:
                v["variants"].append(var)
            rank = row.get("rank")
            cur = v["appearances"].get(sid)
            # 同榜多变体：保留最好名次（名次数字最小）
            if (cur and isinstance(cur.get("rank"), int)
                    and isinstance(rank, int) and cur["rank"] <= rank):
                continue
            v["appearances"][sid] = {
                "rank": rank,
                "score": row.get("score"),
                "metric": payload.get("metric"),
                "is_new": row.get("is_new", False),
                "trend": row.get("trend", 0),
                "variant": var,
            }

    # 多源共识置信度：按"方法论分组"统计覆盖度。不是跨榜分数运算，而是
    # "该模型是否在相互独立的方法论下都被评测到"的存在性证据分级。
    for v in acc.values():
        groups = {METHOD_GROUPS.get(sid, "other") for sid in v["appearances"]}
        v["group_count"] = len(groups)
        v["appearance_count"] = len(v["appearances"])
        v["has_stale"] = any((collected.get(sid) or {}).get("stale")
                             for sid in v["appearances"])
        if len(groups) >= 2:
            v["confidence"] = "verified"   # 跨方法论多源
        elif len(v["appearances"]) >= 2:
            v["confidence"] = "partial"    # 同方法论多榜
        else:
            v["confidence"] = "single"     # 单源

    all_models = [v for v in acc.values() if v["appearances"]]
    cross = [v for v in all_models if v["appearance_count"] >= CROSS_MIN_BOARDS]
    # 排序规则（前端会原样展示，保证"怎么排的"可解释）：
    #   ① 上榜数降序 ② 方法论覆盖数降序 ③ 代表名次升序 ④ 名称
    cross.sort(key=lambda m: (
        -m["appearance_count"],
        -m["group_count"],
        _best_rank(m),
        m["display_name"],
    ))

    cross_meta = {
        "total_models": len(all_models),
        "multi_board": len(cross),
        "single_board": len(all_models) - len(cross),
        "min_boards": CROSS_MIN_BOARDS,
        "boards": [sid for sid in order if (collected.get(sid) or {}).get("rows")],
        "sort_rule": "上榜数 ↓ · 方法论覆盖 ↓ · 代表名次 ↑ · 名称",
    }
    return cross, cross_meta


if __name__ == "__main__":
    main()
