#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""编排层：串行遍历数据源 -> 契约熔断 -> 多层降级 -> 写快照 -> 聚合 -> 落盘。

本模块只回答一个问题：**按什么顺序、遇到问题怎么办**。
所有「怎么算」都在别处：

    boards.py        榜单有哪些、各自什么口径（单一真值源）
    sources/*.py     怎么取、怎么解析（SourceAdapter）
    domain/*.py      怎么算（纯函数，零 IO，可独立单测）
    models.py        模型名归一（变体折叠 / 厂商 / 国别 / 开源）
    fallback.py      契约熔断 / LKG / 第三方镜像
    schema.py        meta 字段契约
    snapshot.py      快照存储（内存索引）

四条不可动摇的设计原则
--------------------
1. **单源失败不影响整体**：每个适配器独立 try/except。降级链按可信度排序：
       (a) 第三方镜像快照（Internet Archive，独立信任域）
       (b) LKG 最后已知良好（仅记录通过契约的批次）
       (c) 最近历史快照  (d) 人工维护数据 data/manual/<source>.json
2. **数据契约熔断**：实时结果先过契约（行数下限 / 跌幅 / 分数完整度 +
   meta 字段完整性），不合格视为失败、不落盘、不晋级 LKG
   ——坏数据永不进入展示层。
3. **字段缺失降级而非报错**：抓取器内部对行内缺失字段填 None，
   页面显示「—」；但 meta 级字段缺失视为该源失败（见 schema.py）。
4. **不修改原始分数、不跨榜计算综合总分**：merged.json 只做字段对齐、
   升降对比与方法论分组的「共识置信度」标签。

运行：python src/orchestrator.py
产物：data/raw/*.json（快照）、data/merged.json（前端消费）、data/meta.json、
     data/state/lkg.json（最后已知良好）、data/state/failures.json（降级报告）
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import (  # noqa: E402
    RAW_DIR, MANUAL_DIR, DATA_DIR, log, warn, today_str, now_utc_iso,
    write_snapshot, write_json, latest_snapshot_before, load_manual,
)
from models import enrich, canonical_id, registry_stats  # noqa: E402
from schema import validate_meta                          # noqa: E402
from snapshot import STORE                                # noqa: E402
import fallback as fb_engine                               # noqa: E402
import build_trend                                         # noqa: E402
import boards as B                                        # noqa: E402
from sources import load_all                              # noqa: E402
from domain.aggregate import build_merged as _build_merged  # noqa: E402

# 数据编排顺序（跨榜表据此选默认并列的代表榜）。
# 注意与 boards.TAB_ORDER 区分：那是前端 tab 展示顺序，二者刻意不同。
BOARD_ORDER = B.board_order()

# {source_id: 模块}，仅含声明了镜像能力的源。由 _build_adapters() 建立。
_MIRROR_PARSERS = {}


# ---------------------------------------------------------------- 装配

def _build_adapters():
    """加载适配器，并建立「source_id -> 模块」映射（镜像通道按需重解析）。

    适配器声明自己能产出哪些 source_id，编排层因此不必区分单源与多源，
    原先 `if task_key == "_lmarena_group"` 的特例分支也随之消失。

    镜像能力同样由适配器声明（mirror_ok），但重解析需要拿到模块本身
    （要用它的 parse_html），故这里额外建一张按 source_id 的模块索引。
    原本这是 main.py 里一个硬编码字典（指向 aa 适配器模块），
    每加一个 HTML 类源都得记得同步——现在由 source_ids 自动展开。
    """
    global _MIRROR_PARSERS
    adapters = load_all()
    mods = {}
    for ad in adapters:
        mod = sys.modules[type(ad).__module__]
        for sid in ad.source_ids:
            mods[sid] = mod
    _MIRROR_PARSERS = {sid: m for sid, m in mods.items()
                       if getattr(m, "MIRROR_OK", False) and hasattr(m, "parse_html")}
    return adapters


def _mirror_payload(source_id, date_str):
    """B 层：第三方镜像（Internet Archive）。仅对声明支持镜像的适配器启用。"""
    mod = _MIRROR_PARSERS.get(source_id)
    if not mod:
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


def _prev_payload_for_check(source_id, date_str):
    """契约校验的比较基准：优先用 LKG（已通过契约），否则用最近历史快照。"""
    got = fb_engine.lkg_payload(source_id)
    if got:
        return got[0]
    _, prev = latest_snapshot_before(source_id, date_str)
    return prev


def _fallback_payload(source_id, date_str):
    """替代降级链（按可信度排序，全部独立于「活源成功」这一前提）：

      1. mirror   第三方镜像快照（独立信任域，与本站无关）
      2. lkg      最后已知良好（通过契约的批次，可信度高于「最近快照」）
      3. snapshot 最近历史快照（兼容原方案）
      4. manual   人工维护数据（页面明确标注）

    返回 (payload, layer)；全部不可用返回 (None, None)。
    """
    mir = _mirror_payload(source_id, date_str)
    if mir and mir.get("rows"):
        mir["stale"] = True
        mir["stale_from"] = date_str
        log(f"降级[{source_id}] -> 第三方镜像快照（{len(mir['rows'])} 行）")
        return mir, "mirror"

    got = fb_engine.lkg_payload(source_id)
    if got:
        payload, lkg_date = got
        payload = dict(payload)
        payload["stale"] = True
        payload["stale_from"] = lkg_date
        payload["channel"] = "lkg"
        log(f"降级[{source_id}] -> LKG 最后已知良好（{lkg_date}，{len(payload['rows'])} 行）")
        return payload, "lkg"

    prev_date, prev = latest_snapshot_before(source_id, date_str)
    if prev and prev.get("rows"):
        prev = dict(prev)
        prev["stale"] = True
        prev["stale_from"] = prev_date
        prev["channel"] = "snapshot"
        log(f"降级[{source_id}] -> {prev_date} 历史快照（{len(prev['rows'])} 行）")
        return prev, "snapshot"

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


# ---------------------------------------------------------------- 趋势注入

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
                row["trend"] = 0      # 新上榜：与「上期不在榜」相比确无升降，0 是准确表达
                row["is_new"] = True
        else:
            # 该榜没有可比对的上一期数据：用 null 显式表达「无法比较」。
            # 前端据此显示「无对比」而非「持平」——把「未知」渲染成「无变化」
            # 是不实陈述，也与本项目「未知要做成显式状态」的一贯设计冲突。
            row["trend"] = None
            row["is_new"] = False
    payload["compared_with"] = prev_date
    return payload


def _degrade(source_id, date_str, error, failures, collected, status="fallback"):
    """执行降级链并把结果记入 collected / failures。

    兜底数据同样要过数据契约。理由：降级链的目的是「用可信的旧数据顶上」，
    而不是「来什么显示什么」。LKG 层的定义本就是「通过契约的批次」，
    若兜底数据绕过契约检查，那么一份 meta 字段拼错的 manual JSON 会被
    提升进展示层——这恰好是契约要消除的那类静默失败，只是换了个入口。

    这里只校验 meta 契约（行级契约在 LKG 晋级时已保证，且历史快照可能
    因上游合理缩榜而低于当下阈值，用行级阈值会误杀有效的兜底数据）。
    """
    payload, layer = _fallback_payload(source_id, date_str)
    if payload:
        meta_reasons = validate_meta(source_id, payload)
        if meta_reasons:
            # 兜底数据自身残缺：不用它，改记为彻底失败，避免展示半残数据
            warn(f"[降级/{source_id}] 兜底层 {layer} 数据未过 meta 契约: "
                 f"{'; '.join(meta_reasons)}")
            failures.append({"source": source_id, "status": "failed",
                             "layer": layer,
                             "error": error + "；且兜底数据 meta 契约不通过: "
                                       + "; ".join(meta_reasons)})
            return
        collected[source_id] = _add_trend(payload, source_id, date_str)
        failures.append({"source": source_id, "status": status,
                         "layer": layer, "error": error})
    else:
        failures.append({"source": source_id, "status": "failed", "error": error})


# ---------------------------------------------------------------- 主流程

def build_merged(collected, date_str, failures):
    """组装 merged.json。实现见 domain.aggregate.build_merged。

    有 IO 与时间依赖的依赖（滞后天数、当前时间、主数据归一、注册表统计）
    在此注入，使 domain 层保持纯函数。
    """
    return _build_merged(
        collected, date_str, failures,
        board_order=BOARD_ORDER,
        stale_days_fn=fb_engine.stale_days,
        now_iso=now_utc_iso,
        enrich=enrich,
        registry_stats_fn=registry_stats,
    )


def _fetchable_source_ids(date_str):
    """本次运行真正需要重抓的 source_id。

    降频判据见 boards.should_fetch_today 的文档：按各榜实测的内容变化率
    设间隔，而非按「是否已退役」——实测 open_llm（已退役）内容每天都在变
    （分页顺序抖动），而 superclue / livecodebench（正常榜）8~9 期未变。

    跳过的源不会出现在 collected 里，后面的补降级循环会用最新快照顶上，
    因此页面照常展示数据，只是滞后天数如实标注。
    """
    out, skipped = [], []
    for sid in BOARD_ORDER:
        snaps = STORE.list_all(sid)
        last_date = snaps[-1][0] if snaps else None
        if B.should_fetch_today(sid, date_str, last_date):
            out.append(sid)
        else:
            skipped.append(sid)
    if skipped:
        log(f"按频率策略跳过重抓（沿用最新快照）: {', '.join(skipped)}")
    return out


def _last_snapshot_payload(source_id, date_str):
    """取该榜 date_str 之前的最新快照 payload；没有则 None。"""
    _, prev = latest_snapshot_before(source_id, date_str)
    return prev


def run(date_str=None):
    """执行一次完整管道，返回 True 表示产出了 merged.json。"""
    date_str = date_str or today_str()
    os.makedirs(RAW_DIR, exist_ok=True)
    os.makedirs(MANUAL_DIR, exist_ok=True)
    log(f"=== AI 模型排行榜数据抓取开始 {date_str} (UTC) ===")

    # 榜单注册表自检：配置错误（order 重复、并列容差缺出处、tab 顺序漏榜）
    # 属于「代码写错」而非「上游异常」，不该等到某个榜渲染不出来才发现。
    # 在任何网络请求之前拦下——带着错配置跑完全程只会产出口径可疑的数据。
    reg_problems = B.validate()
    if reg_problems:
        warn("榜单注册表自检不通过，已中止本次抓取：")
        for p in reg_problems:
            warn(f"  - {p}")
        return False

    adapters = _build_adapters()
    fetchable = set(_fetchable_source_ids(date_str))
    collected = {}   # source_id -> payload
    failures = []    # 记录失败与降级情况

    for adapter in adapters:
        name = type(adapter).__name__
        # 全部子榜都到低频期时跳过整个适配器，避免无谓的网络请求。
        # lmarena 三个子榜都是每日榜，正常不会走到这里。
        if not any(sid in fetchable for sid in adapter.source_ids):
            log(f"[{name}] 全部子榜均在低频期，跳过本次抓取")
            for sid in adapter.source_ids:
                prev = _last_snapshot_payload(sid, date_str)
                if prev:
                    collected[sid] = _add_trend(dict(prev), sid, date_str)
                else:
                    _degrade(sid, date_str, "低频期且无历史快照可复用",
                             failures, collected)
            continue

        try:
            result = adapter.fetch(date_str)  # {source_id: payload}
        except Exception as exc:  # noqa: BLE001
            warn(f"[{name}] 抓取失败: {exc}")
            # 该适配器声明的所有 source_id 各自降级——不区分单源/多源
            for sid in adapter.source_ids:
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

        # 适配器声明了 source_ids 却没有全部产出（如 lmarena 某个子榜单独失败）
        # 时，为缺失项补降级。不再需要按适配器类型分支。
        for sid in adapter.source_ids:
            if sid not in collected:
                _degrade(sid, date_str, "适配器未产出该子集", failures, collected)

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
        return False

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
    return True


def main():
    run()


if __name__ == "__main__":
    main()
