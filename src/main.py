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
from models import enrich, canonical_id, registry_stats  # noqa: E402
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

# 中文任务名：前端以「任务名（原榜名）」双层命名呈现——先让访客看懂"这个榜在测什么"，
# 再让他看到原始榜名。缺失时前端回退到内置映射，不阻断渲染。
BOARD_TASK_LABEL = {
    "lmarena_text": "对话偏好",
    "lmarena_webdev": "前端生成",
    "lmarena_agent": "智能体交互",
    "aa_intelligence": "综合智能",
    "superclue": "中文综合",
    "livecodebench": "代码生成",
    "open_llm": "开源通用",
}

# 统计并列：**只有上游公布了容差口径的榜才启用**，其余榜保留原始名次。
#
# 为什么不用「全距 × 比率」这类自适应阈值：聚合站拿不到各榜的标准误 / 置信区间，
# 用任意比率去合并名次等于凭空制造精度。实测该做法在 LMArena Text（414 行，分数全距
# 700 分，全距被尾部差模型拉大）上把阈值放大到 5.6 分，导致头部真实分差 3~4 分的
# 模型被并成同一名次，414 行里 400 行卷入并列，名次彻底失去区分度。
#
# 因此改为白名单：口径必须有出处，并在页面如实标注；未列入的榜不做并列处理，
# 由前端说明「上游未公布容差，名次按原始排序展示，相邻分差不代表显著性」。
TIE_TOLERANCE = {
    # SuperCLUE 官方口径：「为减少波动影响，榜单将分差 1 分值内的模型视为并列排名」
    "superclue": {
        "abs": 1.0,
        "source": "SuperCLUE 官方口径：分差 1 分以内视为并列排名",
    },
}

# 方法论版本号：每当改动「变体折叠 / 厂商归一 / 跨榜收录门槛 / 排序规则 / 并列规则」
# 任一项就升版，并在页面显式展示。作用对标 Artificial Analysis 的 Intelligence Index
# 版本号——让读者能判断"我看到的这套结论是按哪一版规则算出来的"，也让历史结论可追溯。
METHODOLOGY_VERSION = "cross-v2"
METHODOLOGY_CHANGES = [
    ("cross-v2", "统计并列改为「仅上游公布容差的榜启用」（白名单 + 出处），不再用全距比率自适应阈值；"
                 "厂商与国别都推不出的模型改为「列出但标灰、不参与排序」；已退役归档榜不再产出「当前第一」；"
                 "榜单改「任务名（原榜名）」双层命名"),
    ("cross-v1", "建立模型主数据层：变体折叠 + 厂商归一；跨榜表只收 ≥2 榜模型；id 一律由主数据重算"),
]

# 「各维度当前第一」摘要条的数据来源配置：(榜 id, 中文维度名, 该维度的度量依据)
# 每一项都只是**陈述某个榜上的第一名是谁**（事实），不做任何跨榜加总或换算。
# 某榜缺数据或已退役时该项自动省略，不阻断渲染。
DIMENSION_LEADERS = [
    ("aa_intelligence", "综合智能", "Artificial Analysis Intelligence Index"),
    ("lmarena_text", "对话偏好", "LMArena Text Arena Score"),
    ("livecodebench", "代码生成", "LiveCodeBench pass@1"),
    ("superclue", "中文综合", "SuperCLUE 智能指数"),
]


def _tie_meta(sid):
    """该榜的并列口径：返回 {'abs': 容差或 None, 'source': 出处说明或 None}。

    未列入白名单的榜返回空值 → _apply_tie_ranking 不做合并，前端据此说明
    「上游未公布容差，名次按原始排序展示，相邻分差不代表显著性」。
    """
    t = TIE_TOLERANCE.get(sid)
    if not t:
        return {"abs": None, "source": None}
    return {"abs": t.get("abs"), "source": t.get("source")}


def _apply_tie_ranking(rows, tol=None):
    """为榜单行计算统计并列，返回**新列表**（不修改入参行对象）。

    tol 为 None 时不做任何合并，仅补齐 tie_rank=rank / tie_size=1，保证字段齐整。

    分组规则（tol 为绝对容差时）：按分数降序扫描；若某行与「当前并列组最高分」之差
    不超过 tol，则并入该组，否则另起一组。与**组首**比较而非与相邻行比较，可避免
    链式漂移（A≈B、B≈C 但 A≫C 仍被并成一组）。

    编号规则：并列组按出现顺序密集编号（1,1,2,2,2,3…），即 dense ranking，
    与 SuperCLUE 官方榜单的显示口径一致——本站不改动上游名次，读者交叉核对
    同一榜单时应看到相同数字。仅当全部行都有分数时启用密集编号；若存在无分数的行
    （编号会与原始名次错位），退回「取组内最小原始名次」以保证单调不回退。
    """
    out = [dict(r) for r in rows]

    # 先无条件重置并列字段，再做分组覆盖。
    # 必须重置而非 setdefault：入参行可能已带上一次运行按旧策略算出的
    # tie_rank / tie_size（例如 merged.json 回读、或策略调整后重跑），
    # setdefault 会让旧值存活下来，导致输出与实际策略不符。
    # 顺序上重置必须在分组**之前**——放在末尾会把刚算好的分组结果抹掉。
    for r in out:
        r["tie_rank"] = r.get("rank")
        r["tie_size"] = 1

    if tol is None or tol <= 0:
        return out

    scored = [r for r in out if isinstance(r.get("score"), (int, float))]
    if len(scored) < 2:
        return out

    ordered = sorted(scored, key=lambda r: -r["score"])
    groups, cur, best = [], [], None
    for r in ordered:
        if best is None or (best - r["score"]) <= tol:
            cur.append(r)
            if best is None:
                best = r["score"]
        else:
            groups.append(cur)
            cur, best = [r], r["score"]
    if cur:
        groups.append(cur)

    all_scored = len(scored) == len(out)
    for idx, g in enumerate(groups, start=1):
        ranks = [m["rank"] for m in g if isinstance(m.get("rank"), int)]
        fallback = min(ranks) if ranks else None
        for m in g:
            m["tie_rank"] = idx if all_scored else (fallback if fallback is not None
                                                    else m.get("rank"))
            m["tie_size"] = len(g)

    return out


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
        tie = _tie_meta(sid)
        boards[sid] = {
            "board": payload.get("board"),
            "task_label": BOARD_TASK_LABEL.get(sid, ""),
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
            "tie_tolerance": tie.get("abs"),
            "tie_rule": tie.get("source"),
            # 统计并列：返回新列表，不改动 payload 里的原始行对象。
            # 仅对白名单榜生效，其余榜 tol=None → tie_rank 等于原始 rank。
            "rows": _apply_tie_ranking(payload.get("rows", []), tie.get("abs")),
        }

    cross, cross_meta = build_cross(collected)

    # 跨榜元信息补充：方法论版本、双层命名映射、并列规则、维度冠军、参考组。
    # 放在 build_merged 而非 build_cross 里，因为这几项都要读 boards（含 tie_rank
    # 与 task_label），而 boards 字典正是在这里组装的。
    cross_meta["methodology_version"] = METHODOLOGY_VERSION
    cross_meta["methodology_changes"] = [
        {"version": v, "changes": c} for v, c in METHODOLOGY_CHANGES
    ]
    # 并列口径：逐榜给出「容差 + 出处」，而不是一个全站比率。
    # 前端据此区分两种情况——有出处的榜标 "="，没出处的榜明确说明不做并列。
    tie_policy = {sid: _tie_meta(sid) for sid in boards}
    cross_meta["tie_policy"] = {
        sid: {"tolerance": t["abs"], "source": t["source"]}
        for sid, t in tie_policy.items()
    }
    cross_meta["tie_boards"] = [sid for sid, t in tie_policy.items() if t["abs"]]
    cross_meta["tie_note"] = (
        "仅对上游公布了容差口径的榜启用统计并列（名次前标 =）；其余榜保留原始名次——"
        "聚合站拿不到各榜的标准误，用自定阈值合并名次等于凭空制造精度。"
    )
    cross_meta["task_labels"] = {
        sid: {"task": BOARD_TASK_LABEL.get(sid, ""), "board": b.get("board")}
        for sid, b in boards.items()
    }
    cross_meta["dimension_leaders"] = _compute_dimension_leaders(boards)
    cross_meta["reference_only"] = _compute_reference_only(cross)
    # 主数据层规模：注册表实体数、别名条数，以及「正式名能否解析回自身」的自检结果。
    # 方法论页要展示这些数字，由数据层提供才能保证页面与代码严格同源
    # （前端不应自己从 cross 里估算注册表规模——那只覆盖到出现在榜上的实体）。
    cross_meta["registry"] = registry_stats()

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


def _leader_from_board(boards, sid, label, basis):
    """取某榜当前第一名，返回摘要条所需的最小事实集合；无数据返回 None。

    只陈述"这个榜上排第一的是谁、分数多少"，不做任何换算或跨榜比较。
    并列名次沿用 _apply_tie_ranking 的结果（tie_rank / tie_size 如实带出）。

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


def _cheapest_from_board(boards, sid="aa_intelligence"):
    """取该榜中价格最低的一项（纯事实：官方报价，不做任何性价比换算）。

    与 _leader_from_board 同样跳过已退役归档的榜。
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


def _compute_dimension_leaders(boards):
    """汇总「各维度当前第一」摘要条数据（对标 LLM Stats 首屏摘要）。"""
    out = []
    for sid, label, basis in DIMENSION_LEADERS:
        item = _leader_from_board(boards, sid, label, basis)
        if item:
            out.append(item)
    cheap = _cheapest_from_board(boards)
    if cheap:
        out.append(cheap)
    return out


def _compute_reference_only(cross):
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
        _best_rank(m),
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


if __name__ == "__main__":
    main()
