#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""多层独立冗余的兜底引擎（替代"历史快照 + 人工 JSON"的单一自引用降级）。

设计动机
--------
原降级链（历史快照 → 人工数据）共享同一个信任域：同一个仓库、同一条流水线、
同一个解析器。一旦仓库历史损坏、流水线产出的都是坏数据、或解析器长期失效，
"自引用"的兜底会一起失效——即单点故障（SPOF）。

替代思路把"信任域"和"失败模式"都拆散，共四层，互为独立：

  A. 契约熔断（Data Contract / Circuit Breaker）
     实时抓取结果先过数据契约（行数下限、较上期跌幅、分数完整度）。
     不合格 = 视为失败，不落盘、不得晋级，直接进入下一层。
     目的：坏数据永不进入展示层（比"抓到就算成功"更安全）。

  B. 第三方镜像通道（Independent Mirror）
     活源宕机时，改从与本站完全无关的第三方取数：
     Internet Archive Wayback Machine 的最近快照（id_ 原始捕获）。
     独立于本站仓库与流水线，是真正的"外部冗余"。

  C. LKG 最后已知良好（Last-Known-Good）
     data/state/lkg.json 只记录"通过契约"的批次（日期 + 行数 + 校验和）。
     回填时从对应日期的 raw 快照读取，比"取最近一次快照"更可信
     （最近快照可能是坏数据）。

  D. 极旧回退（历史快照 → 人工数据 → 上一版 merged.json）
     保留原方案作为最后两级，但全部标注 stale/manual 与来源日期。

所有降级都在 payload 上留下 provenance 字段（stale/stale_from/channel/
manual/stale_days），前端据此展示"数据新鲜度横幅"，做到降级透明。

不修改任何原始分数，不跨榜求和。
"""

import datetime
import hashlib
import json
import os

from common import (
    DATA_DIR, RAW_DIR, log, warn, read_json, write_json, http_get,
    today_str, now_utc_iso, snapshot_path,
)

STATE_DIR = os.path.join(DATA_DIR, "state")
LKG_PATH = os.path.join(STATE_DIR, "lkg.json")
FAILREPORT_PATH = os.path.join(STATE_DIR, "failures.json")
# 运维逃生口：上游榜单合理改版（例如重置、大幅扩榜/缩榜）导致契约长期误拒时，
# 维护者可在 data/state/contract_overrides.json 里按源覆盖阈值，无需改代码。
# 形如：{"lmarena_text": {"min_rows": 10, "max_drop_ratio": 0.1}}
OVERRIDE_PATH = os.path.join(STATE_DIR, "contract_overrides.json")

# ---------------------------------------------------------------- 数据契约
# 每源独立阈值。min_rows 为硬下限；max_drop_ratio 为"较上期行数跌幅"容忍度
# （新行数 < 上期 * ratio 即判为异常，多为解析器失效导致的"抓到壳但没抓到肉"）。
CONTRACTS = {
    "lmarena_text":     {"min_rows": 20, "max_drop_ratio": 0.35},
    "lmarena_webdev":   {"min_rows": 10, "max_drop_ratio": 0.35},
    "lmarena_agent":    {"min_rows": 5,  "max_drop_ratio": 0.35},
    "aa_intelligence":  {"min_rows": 5,  "max_drop_ratio": 0.30},
    "livecodebench":    {"min_rows": 5,  "max_drop_ratio": 0.30},
    "open_llm":         {"min_rows": 10, "max_drop_ratio": 0.30},
    "superclue":        {"min_rows": 3,  "max_drop_ratio": 0.40},
}
_DEFAULT_CONTRACT = {"min_rows": 3, "max_drop_ratio": 0.30}

# 分数完整度：某源超过该比例的行使 score 缺失，判为解析异常。
MAX_MISSING_SCORE_RATIO = 0.6


def rows_checksum(payload) -> str:
    """对"模型名+分数"序列取稳定哈希，用于判断批次是否真的变化。"""
    rows = (payload or {}).get("rows") or []
    key = "|".join(
        f"{r.get('model')}={r.get('score')}" for r in rows
    )
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def check_contract(source_id: str, payload, prev_payload):
    """数据契约校验。返回 (ok: bool, reasons: list[str])。

    prev_payload 用于行数跌幅比较，可为 None（首次运行则跳过跌幅检查）。
    阈值可被 data/state/contract_overrides.json 覆盖（运维逃生口）。
    """
    reasons = []
    if not payload:
        return False, ["payload 为空"]
    rows = payload.get("rows") or []
    conf = dict(_DEFAULT_CONTRACT)
    conf.update(CONTRACTS.get(source_id, {}))
    overrides = read_json(OVERRIDE_PATH, default={}) or {}
    if isinstance(overrides.get(source_id), dict):
        conf.update(overrides[source_id])

    if len(rows) < conf["min_rows"]:
        reasons.append(f"行数 {len(rows)} < 下限 {conf['min_rows']}")

    if rows:
        missing = sum(1 for r in rows if r.get("score") is None)
        if missing / len(rows) > MAX_MISSING_SCORE_RATIO:
            reasons.append(f"分数缺失率 {missing}/{len(rows)} 过高（疑似解析失效）")

    prev_rows = (prev_payload or {}).get("rows") or []
    if prev_rows and len(prev_rows) >= 10:
        floor = int(len(prev_rows) * conf["max_drop_ratio"])
        if len(rows) < floor:
            reasons.append(
                f"行数骤降 {len(prev_rows)} -> {len(rows)}（低于上期 {conf['max_drop_ratio']:.0%}）"
            )

    return (len(reasons) == 0), reasons


# ---------------------------------------------------------------- LKG 状态库

def load_lkg() -> dict:
    return read_json(LKG_PATH, default={}) or {}


def save_lkg(state: dict) -> None:
    os.makedirs(STATE_DIR, exist_ok=True)
    write_json(LKG_PATH, state)


def promote_lkg(source_id: str, payload, date_str: str) -> None:
    """把通过契约的批次记为"最后已知良好"。"""
    state = load_lkg()
    rows = payload.get("rows") or []
    state[source_id] = {
        "date": date_str,
        "rows": len(rows),
        "checksum": rows_checksum(payload),
        "promoted_at": now_utc_iso(),
    }
    save_lkg(state)


def lkg_payload(source_id: str):
    """按 LKG 记录的日期回填通过契约的原始快照。返回 payload 或 None。"""
    state = load_lkg()
    rec = state.get(source_id)
    if not rec:
        return None
    date = rec.get("date")
    payload = read_json(snapshot_path(source_id, date))
    if payload and payload.get("rows"):
        return payload, date
    return None


# ---------------------------------------------------------------- 镜像通道
# 与本站无关的第三方持久快照：Internet Archive Wayback Machine。
# 仅在活源失败时启用，避免无谓占用其配额（官方 API 有 429 限流）。

def wayback_available(url: str, timestamp: str = None):
    """查询 Wayback 最近可用快照。返回 {url, timestamp} 或 None。"""
    api = "https://archive.org/wayback/available"
    q = f"{api}?url={url}"
    if timestamp:
        q += f"&timestamp={timestamp}"
    try:
        data = http_get(q, as_json=True, timeout=30, retries=2)
    except Exception as exc:  # noqa: BLE001
        warn(f"Wayback 可用性查询失败: {exc}")
        return None
    closest = (data.get("archived_snapshots") or {}).get("closest") or {}
    if closest.get("available") and closest.get("url"):
        return {"url": closest["url"], "timestamp": closest.get("timestamp")}
    return None


def wayback_fetch_text(url: str, timestamp: str = None, max_bytes=8_000_000):
    """取 Wayback 原始捕获的 HTML（id_ 修饰符去掉归档工具栏）。"""
    snap = wayback_available(url, timestamp)
    if not snap:
        return None
    raw_url = snap["url"]
    # 在快照时间戳后加 id_ 请求原始字节，避免注入 Wayback 工具栏脚本
    if "id_" not in raw_url:
        raw_url = raw_url.replace(
            f"/web/{snap['timestamp']}/", f"/web/{snap['timestamp']}id_/", 1
        )
    try:
        html = http_get(raw_url, timeout=90, retries=2, max_bytes=max_bytes)
    except Exception as exc:  # noqa: BLE001
        warn(f"Wayback 快照拉取失败: {exc}")
        return None
    return {"html": html, "timestamp": snap["timestamp"], "snapshot_url": snap["url"]}


# ---------------------------------------------------------------- 失败报告

def write_failures(failures, date_str: str = None) -> None:
    """把降级/失败情况落盘，供工作流读取并自动开 Issue。"""
    os.makedirs(STATE_DIR, exist_ok=True)
    bad = [f for f in failures if f.get("status") in ("fallback", "failed", "degraded")]
    write_json(FAILREPORT_PATH, {
        "generated_at": now_utc_iso(),
        "date": date_str or today_str(),
        "total": len(failures),
        "degraded": len(bad),
        "items": failures,
    })


def stale_days(payload) -> int:
    """降级数据距今天数，用于前端新鲜度提示。"""
    prev = payload.get("stale_from") or payload.get("publish_date")
    if not prev:
        return 0
    try:
        d0 = datetime.date.fromisoformat(str(prev)[:10])
        return max(0, (datetime.date.today() - d0).days)
    except ValueError:
        return 0
