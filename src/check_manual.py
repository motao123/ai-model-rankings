#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""人工兜底数据的过期监控（自愈闭环的补充）。

背景
----
data/manual/<source>.json 是抓取全部失败时的最后一级兜底，但它是**手工维护**的：
没有更新机制时，它会悄悄变旧，页面就会展示一份过期的"兜底数据"而不自知
（降级是透明的，但"兜底本身就过期"这件事此前没有提醒）。

行为
----
- 扫描 data/manual/*.json，按 as_of（缺省退回 publish_date）计算已过天数；
- retired=True 的源（如已退役的 HF Open LLM 归档）属于"永久快照"，不参与判定；
- 超过阈值（默认 45 天）判为过期：
    * 有 open 的 manual-stale issue -> 仅当"过期集合"变化时追加评论（避免每日刷屏）
    * 没有 -> 新建；
- 全部新鲜：若存在 manual-stale 的 open issue，则评论并关闭（"已更新"）。
- gh 不可用时静默跳过，绝不让工作流失败。

用法：python src/check_manual.py
依赖：gh CLI + GH_TOKEN（GitHub Actions 默认提供）
"""

import datetime
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from common import read_json, write_json   # noqa: E402  统一 JSON 读写（原脚本自带一份）
from gh_util import (                       # noqa: E402  gh 调用与 Issue 查找
    gh, find_labeled_issue, ensure_label, comment_and_close,
)

ROOT = os.path.dirname(HERE)
MANUAL_DIR = os.path.join(ROOT, "data", "manual")
STATE_PATH = os.path.join(ROOT, "data", "state", "manual_check.json")

LABEL = "manual-stale"
STALE_DAYS = 45


def find_open_issue():
    """保留旧名，内部转调公共实现（外部调用方无需改动）。"""
    return find_labeled_issue(LABEL)


def _as_of(payload):
    return payload.get("as_of") or payload.get("publish_date")


def _reviewed_at(payload):
    """最近一次人工复核日期。缺失时退回数据日期（as_of/publish_date）。

    提醒判定用 reviewed_at 而非数据日期：上游期次本身可能不规律
    （例如 SuperCLUE 是双月/年度期次），用数据日期会误报；
    "这份人工文件多久没人看过了"才是可执行、且与上游节奏无关的语义。
    """
    return payload.get("reviewed_at") or _as_of(payload)


def scan():
    """返回 (stale, fresh, skipped)；每项为 dict(source, as_of, reviewed_at, age_days, rows)。"""
    stale, fresh, skipped = [], [], []
    if not os.path.isdir(MANUAL_DIR):
        return stale, fresh, skipped
    today = datetime.date.today()
    for name in sorted(os.listdir(MANUAL_DIR)):
        if not name.endswith(".json"):
            continue
        payload = read_json(os.path.join(MANUAL_DIR, name))
        if not payload:
            continue
        src = payload.get("source_id") or name[:-5]
        if payload.get("retired"):
            skipped.append(src)
            continue
        reviewed = _reviewed_at(payload)
        try:
            d0 = datetime.date.fromisoformat(str(reviewed)[:10])
            age = (today - d0).days
        except (ValueError, TypeError):
            age = None
        item = {"source": src, "as_of": _as_of(payload), "reviewed_at": reviewed,
                "age_days": age, "rows": len(payload.get("rows") or [])}
        (stale if (age is None or age > STALE_DAYS) else fresh).append(item)
    return stale, fresh, skipped


def build_body(stale):
    lines = [
        f"**日期**：{datetime.date.today().isoformat()}",
        f"**过期项**：{len(stale)}（阈值 {STALE_DAYS} 天，按 `reviewed_at` 最近人工复核日计）",
        "",
        "| 数据源 | 数据日期(as_of) | 最近复核(reviewed_at) | 已过天数 | 行数 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for i in stale:
        age = "—" if i["age_days"] is None else i["age_days"]
        lines.append(f"| `{i['source']}` | {i['as_of']} | {i['reviewed_at']} | {age} | {i['rows']} |")
    lines += [
        "",
        f"> `data/manual/` 是抓取全失败时的最后一级兜底，需人工维护。"
        f"请按上游最新一期报告更新对应文件，并把 `reviewed_at` 改为本次复核日期"
        f"（距上次复核超过 {STALE_DAYS} 天即触发本提醒）。",
        "> 说明：`retired=true` 的源（如已退役的 HF Open LLM 归档）为永久快照，不参与本判定。",
    ]
    return "\n".join(lines)


def main():
    stale, fresh, skipped = scan()
    state_path = STATE_PATH
    prev = read_json(state_path, default={}) or {}
    prev_sources = sorted(prev.get("stale_sources") or [])
    stale_sources = sorted(i["source"] for i in stale)

    write_json(state_path, {
        "checked_at": datetime.datetime.now(datetime.timezone.utc)
                              .strftime("%Y-%m-%dT%H:%M:%SZ"),
        "stale_sources": stale_sources,
        "fresh_sources": sorted(i["source"] for i in fresh),
        "skipped_retired": sorted(skipped),
        "threshold_days": STALE_DAYS,
    })

    existing = find_open_issue()

    if not stale:
        if existing:
            comment_and_close(
                existing,
                "✅ 所有人工兜底数据均已在其 `as_of` 阈值内更新，自动关闭。")
            print(f"[INFO] 人工数据均新鲜，关闭 issue #{existing['number']}")
        else:
            print("[INFO] 人工数据均新鲜，无遗留 issue。")
        return

    body = build_body(stale)
    if existing:
        if stale_sources != prev_sources:
            gh("issue", "comment", str(existing["number"]), "--body", body)
            print(f"[INFO] 过期集合变化，已在 issue #{existing['number']} 追加提醒")
        else:
            print(f"[INFO] 过期集合未变（{stale_sources}），跳过评论以避免刷屏")
    else:
        ensure_label(LABEL, "D4C5F9", "人工兜底数据已过期，需按上游最新期更新")
        title = f"人工兜底数据过期：{len(stale)} 项（{datetime.date.today().isoformat()}）"
        out = gh("issue", "create", "--label", LABEL, "--title", title, "--body", body)
        print(f"[INFO] 已创建人工数据过期 issue：{out or '(gh 不可用)'}")


if __name__ == "__main__":
    main()
