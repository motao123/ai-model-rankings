#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""领域层：跨榜聚合与摘要组装（纯函数，零 IO）。

本模块回答三个问题，全部不涉及「数据从哪来」：

    build_boards()        各榜 payload 如何整理成前端消费的结构
    build_cross()         同一模型在各榜的表现如何对齐
    compute_dimension_leaders()  各维度当前第一是谁

核心原则（项目底线，改动时勿破坏）
--------------------------------
**不修改任何原始分数，不计算跨榜综合总分。** 跨榜对比只做「并列展示各榜
原始名次与分数」，所谓「共识置信度」是**存在性证据分级**（该模型是否在
相互独立的方法论下都被评测到），不是分数运算。

IO 依赖的处理
-------------
原实现在组装 boards 时调用 `fb_engine.stale_days(payload)` 与
`now_utc_iso()`，二者都会读系统时间。为了让本模块保持纯函数可测，
改为由调用方注入：

    stale_days_fn(payload) -> int
    now_iso()               -> str

这样测试可以直接传 lambda，不必 patch 模块级函数。
"""

import sys

sys.path.insert(0, __file__.rsplit("\\", 1)[0].rsplit("/", 1)[0])

import boards as B                                    # noqa: E402
from domain.tiebreak import apply_tie_ranking, build_tie_meta  # noqa: E402

# 跨榜对比只呈现「至少出现在 N 个榜」的模型：单榜模型信息量低、会把长尾
# 原始 ID 淹没主表；它们仍完整保留在各自的分榜明细里。
CROSS_MIN_BOARDS = B.CROSS_MIN_BOARDS

DISCLAIMER = (
    "本站为第三方数据聚合展示，所有分数与排名均来自 LMArena / Artificial Analysis / "
    "SuperCLUE / LiveCodeBench / Hugging Face 等原始榜单，本站不修改任何分数，"
    "也不自行计算跨榜综合总分。各榜单评测口径不同，分数不可直接横向比较，跨榜对比"
    "仅用于观察同一模型在不同方法论下的相对表现。"
)

TIE_NOTE = (
    "仅对上游公布了容差口径的榜启用统计并列（名次前标 =）；其余榜保留原始名次——"
    "聚合站拿不到各榜的标准误，用自定阈值合并名次等于凭空制造精度。"
)


# ---------------------------------------------------------------- 分榜组装

def build_boards(collected, board_order, stale_days_fn):
    """把各源 payload 组织成前端消费的结构。

    Args:
        collected: {source_id: payload}
        board_order: 展示顺序的 source_id 列表；未列出的排在后面
        stale_days_fn: payload -> 滞后天数（注入以保持本模块纯函数）
    """
    out = {}
    ordered = [b for b in board_order if b in collected]
    ordered += [b for b in collected if b not in board_order]
    for sid in ordered:
        payload = collected[sid]
        tie = build_tie_meta(sid)
        out[sid] = {
            "board": payload.get("board"),
            "task_label": B.BY_ID[sid].task_label if sid in B.BY_ID else "",
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
            "stale_days": stale_days_fn(payload) if payload.get("stale") else 0,
            "channel": payload.get("channel"),
            "mirror_note": payload.get("mirror_note"),
            "manual": payload.get("manual", False),
            "manual_note": payload.get("manual_note"),
            "retired": payload.get("retired", False),
            "retired_note": payload.get("retired_note"),
            "price_unit": payload.get("price_unit"),
            "tie_tolerance": tie.get("abs"),
            "tie_rule": tie.get("source"),
            # 统计并列：返回新列表，不改动 payload 里的原始行对象。
            # 仅对白名单榜生效，其余榜 tol=None → tie_rank 等于原始 rank。
            "rows": apply_tie_ranking(payload.get("rows", []), tie.get("abs")),
        }
    return out


# ---------------------------------------------------------------- 跨榜聚合

def build_cross(collected, board_order, enrich):
    """跨榜同屏对比：以 canonical id 聚合每个模型在各榜的表现。

    Args:
        enrich: (model_name, organization) -> 主数据 dict（由 models 层注入）

    Returns:
        (cross, cross_meta)

    - 同一模型在同一榜的不同变体（`-high` / `-max` / `(thinking)` / 日期戳）
      通过模型主数据折叠为同一实体，取**最好名次**，变体名记入
      appearances[sid]['variant']；榜单原始快照不被修改。
    - 仅收录出现在 >= CROSS_MIN_BOARDS 个榜的模型；单榜模型不在此表，
      但仍完整保留在分榜明细中（cross_meta 里给出数量）。
    """
    order = [b for b in board_order if b in collected]
    order += [b for b in collected if b not in board_order]

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

    groups_map = B.method_groups()

    # 多源共识置信度：按"方法论分组"统计覆盖度。不是跨榜分数运算，而是
    # "该模型是否在相互独立的方法论下都被评测到"的存在性证据分级。
    for v in acc.values():
        groups = {groups_map.get(sid, "other") for sid in v["appearances"]}
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
        # 参考项：**厂商与国别都推不出来**的模型（未登记实体，且名称关键词也认不出）。
        # 不剔除、不猜厂商，改为「列出但标灰、不参与排序」——各榜（如 SuperCLUE 对
        # 海外模型）的通行做法：隐藏数据比标注数据更糟。
        #
        # 注意判据必须是「厂商/国别是否可识别」，而不是 registered（是否在手写注册表
        # 里）。enrich() 的关键词兜底能在未注册时认出 claude-*→Anthropic、
        # gemini-*→Google DeepMind，这类模型厂商明确，不该被标为参考项。
        v["reference_only"] = bool(
            v["vendor"] in (None, "", "未标注") or v["region"] == "other"
        )

    all_models = [v for v in acc.values() if v["appearances"]]
    cross = [v for v in all_models if v["appearance_count"] >= CROSS_MIN_BOARDS]
    # 排序规则（前端会原样展示，保证"怎么排的"可解释）：
    #   ⓪ 参考项沉底（reference_only 为 True 的排最后，不参与名次竞争）
    #   ① 上榜数降序 ② 方法论覆盖数降序 ③ 代表名次升序 ④ 名称
    cross.sort(key=lambda m: (
        bool(m.get("reference_only")),
        -m["appearance_count"],
        -m["group_count"],
        best_rank(m),
        m["display_name"],
    ))

    cross_meta = {
        "total_models": len(all_models),
        "multi_board": len(cross),
        "single_board": len(all_models) - len(cross),
        "min_boards": CROSS_MIN_BOARDS,
        "boards": [sid for sid in order if (collected.get(sid) or {}).get("rows")],
        "sort_rule": "上榜数 ↓ · 方法论覆盖 ↓ · 代表名次 ↑ · 名称（参考项沉底）",
    }
    return cross, cross_meta


def best_rank(model):
    """代表名次：优先取代表榜的名次，都没有则取全部名次里的最好值。"""
    for sid in B.pref_boards():
        ap = model["appearances"].get(sid)
        if ap and isinstance(ap.get("rank"), int):
            return ap["rank"]
    ranks = [a.get("rank") for a in model["appearances"].values()
             if isinstance(a.get("rank"), int)]
    return min(ranks) if ranks else 9999


# 兼容旧名（迁移前 main._best_rank）
_best_rank = best_rank


# ---------------------------------------------------------------- 维度冠军

def leader_from_board(boards, sid, label, basis):
    """取某榜当前第一名，返回摘要条所需的最小事实集合；无数据返回 None。

    只陈述"这个榜上排第一的是谁、分数多少"，不做任何换算或跨榜比较。
    并列名次沿用 apply_tie_ranking 的结果（tie_rank / tie_size 如实带出）。

    已退役归档的榜（retired=True）不产出"当前第一"——归档快照是历史数据，
    拿它当现状陈述会误导读者（如 HF Open LLM Leaderboard 已于 2025-03 停更）。
    """
    b = boards.get(sid)
    if not b or b.get("retired"):
        return None
    rows = b.get("rows") or []
    scored = [r for r in rows if isinstance(r.get("score"), (int, float))]
    if not scored:
        return None
    best = min(scored, key=lambda r: (r.get("tie_rank") if isinstance(r.get("tie_rank"), int)
                                      else (r.get("rank") if isinstance(r.get("rank"), int) else 10**6),
                                      -r["score"]))
    return {
        "key": sid,
        "label": label,
        "basis": basis,
        "board": b.get("board"),
        "id": best.get("id"),
        "model": best.get("display_name") or best.get("model"),
        "vendor": best.get("vendor"),
        "region": best.get("region"),
        "open": best.get("open"),
        "score": best.get("score"),
        "rank": best.get("rank"),
        "tie_rank": best.get("tie_rank"),
        "tie_size": best.get("tie_size", 1),
        "metric": b.get("metric"),
        "value_label": None,
    }


def cheapest_from_board(boards, sid="aa_intelligence"):
    """取该榜中价格最低的一项（纯事实：官方报价，不做任何性价比换算）。

    与 leader_from_board 同样跳过已退役归档的榜。
    """
    b = boards.get(sid)
    if not b or b.get("retired"):
        return None
    rows = b.get("rows") or []
    priced = [r for r in rows if isinstance(r.get("price"), (int, float))]
    if not priced:
        return None
    best = min(priced, key=lambda r: r["price"])
    return {
        "key": f"{sid}_cheapest",
        "label": "最低价格",
        "basis": "Artificial Analysis 混合价格（$/百万 token）",
        "board": b.get("board"),
        "id": best.get("id"),
        "model": best.get("display_name") or best.get("model"),
        "vendor": best.get("vendor"),
        "region": best.get("region"),
        "open": best.get("open"),
        "score": None,
        "rank": best.get("rank"),
        "tie_rank": None,
        "tie_size": 1,
        "metric": b.get("price_unit"),
        "value_label": f"${best['price']:.2f}",
    }


def compute_dimension_leaders(boards):
    """汇总「各维度当前第一」摘要条数据（对标 LLM Stats 首屏摘要）。"""
    out = []
    for sid, label, basis in B.dimension_leaders():
        item = leader_from_board(boards, sid, label, basis)
        if item:
            out.append(item)
    cheap = cheapest_from_board(boards)
    if cheap:
        out.append(cheap)
    return out


def compute_reference_only(cross):
    """统计参考组（列出但不参与排序的模型）。

    口径与 reference_only 一致：上游未提供可识别厂商 / 开源状态（未登记实体），
    或国别无法判定（region=other）。做法对标 SuperCLUE 对海外模型的处理——
    列出但标灰，而不是直接从表里消失（隐藏数据比标注数据更糟）。
    """
    refs = [m for m in cross if m.get("reference_only")]
    return {
        "count": len(refs),
        "rule": "上游未提供可识别厂商/开源状态，或国别无法判定：列出但标灰、不参与排序，本站不猜测",
        "ids": [m["id"] for m in refs][:50],
    }


# ---------------------------------------------------------------- 总装

def build_merged(collected, date_str, failures, *,
                 board_order, stale_days_fn, now_iso, enrich, registry_stats_fn):
    """把各源 payload 组织成前端直接消费的 merged.json，并构建跨榜对比。

    所有有 IO 或时间依赖的函数都由参数注入（见模块文档）。
    """
    boards = build_boards(collected, board_order, stale_days_fn)
    cross, cross_meta = build_cross(collected, board_order, enrich)

    # 跨榜元信息补充：方法论版本、双层命名映射、并列规则、维度冠军、参考组。
    # 放在这里而非 build_cross 里，因为这几项都要读 boards（含 tie_rank 与
    # task_label），而 boards 字典正是在 build_boards 里组装的。
    cross_meta["methodology_version"] = B.METHODOLOGY_VERSION
    cross_meta["methodology_changes"] = [
        {"version": v, "changes": c} for v, c in B.METHODOLOGY_CHANGES
    ]
    # 并列口径：逐榜给出「容差 + 出处」，而不是一个全站比率。
    # 前端据此区分两种情况——有出处的榜标 "="，没出处的榜明确说明不做并列。
    tp = {sid: build_tie_meta(sid) for sid in boards}
    cross_meta["tie_policy"] = {
        sid: {"tolerance": t["abs"], "source": t["source"]}
        for sid, t in tp.items()
    }
    cross_meta["tie_boards"] = [sid for sid, t in tp.items() if t["abs"]]
    cross_meta["tie_note"] = TIE_NOTE
    cross_meta["task_labels"] = {
        sid: {"task": B.BY_ID[sid].task_label if sid in B.BY_ID else "",
              "board": b.get("board")}
        for sid, b in boards.items()
    }
    # 榜单 tab 展示顺序显式下发，供前端摆脱硬编码副本。
    #
    # 刻意用 TAB_ORDER（前端原顺序）而非 list(boards.keys())（数据编排顺序）：
    # 二者原本就不同——boards 是「总榜 → 客观基准 → 子榜」（跨榜表据此选
    # 代表榜），tab 是按机构把 LMArena 三个子榜排在一起。用哪个都会改变
    # 另一侧的可见行为，属于视觉顺序变更，不该在「去重」里夹带。
    cross_meta["board_order"] = list(B.TAB_ORDER)
    cross_meta["dimension_leaders"] = compute_dimension_leaders(boards)
    cross_meta["reference_only"] = compute_reference_only(cross)
    # 主数据层规模：注册表实体数、别名条数，以及「正式名能否解析回自身」的自检结果。
    # 方法论页要展示这些数字，由数据层提供才能保证页面与代码严格同源
    # （前端不应自己从 cross 里估算注册表规模——那只覆盖到出现在榜上的实体）。
    cross_meta["registry"] = registry_stats_fn()

    return {
        "generated_at": now_iso(),
        "date": date_str,
        "disclaimer": DISCLAIMER,
        "boards": boards,
        "cross": cross,
        "cross_meta": cross_meta,
        "failures": failures,
    }
