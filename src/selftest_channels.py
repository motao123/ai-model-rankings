#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""兜底通道自检（Channel self-test）。

动机
----
多层兜底里，最外层「第三方镜像（Internet Archive Wayback）」长期处于
"代码写了但从没被真实触发过"的状态——历史降级都走了 LKG / 历史快照 / 人工数据，
镜像层等于没演练过。而它恰恰是最不容易在本地验证的一层
（本机网络通常无法访问 archive.org）。

本脚本用于**主动演练**这一层：不依赖真实降级发生，直接调用镜像通道的
完整代码路径（可用性查询 -> id_ 原始捕获 -> 复用 fetch_aa.parse_html 重解析），
把每一步的成功/失败与行数打印出来。

用法：
- 本地：python src/selftest_channels.py
- 线上：Actions -> "Channel self-test" -> Run workflow（在能访问 archive.org 的环境里跑）

退出码：只要脚本本身跑通即为 0（自检结果以 PASS/FAIL 文本呈现，不用于阻断流水线）。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fallback as fb_engine  # noqa: E402
import fetch_aa  # noqa: E402
from common import log  # noqa: E402


def _check_mirror(module):
    """演练某个源走镜像通道的完整路径。返回 dict(ok, rows, detail)。"""
    src_id = getattr(module, "SOURCE_ID", "?")
    url = getattr(module, "SOURCE_URL", None)
    if not getattr(module, "MIRROR_OK", False) or not url:
        return {"source": src_id, "ok": None, "rows": 0,
                "detail": "未登记镜像通道（跳过）"}

    snap = fb_engine.wayback_available(url)
    if not snap:
        return {"source": src_id, "ok": False, "rows": 0,
                "detail": f"Wayback 无可用快照或 archive.org 不可达（{url}）"}

    fetched = fb_engine.wayback_fetch_text(url)
    if not fetched:
        return {"source": src_id, "ok": False, "rows": 0,
                "detail": f"查到快照 {snap.get('timestamp')} 但拉取原始捕获失败"}

    try:
        payload = module.parse_html(
            fetched["html"], "selftest",
            channel="wayback-mirror",
            mirror_note="selftest",
        )
        rows = len((payload or {}).get("rows") or [])
    except Exception as exc:  # noqa: BLE001
        return {"source": src_id, "ok": False, "rows": 0,
                "detail": f"快照拉取成功但重解析失败: {exc}"}

    return {"source": src_id, "ok": rows > 0, "rows": rows,
            "detail": f"快照时间戳 {fetched['timestamp']}，重解析得 {rows} 行"}


def main():
    log("=== 兜底通道自检开始 ===")

    # 1) 第三方镜像通道（Internet Archive）
    results = [_check_mirror(fetch_aa)]
    for r in results:
        if r["ok"] is None:
            log(f"[SKIP] mirror/{r['source']}: {r['detail']}")
        else:
            tag = "PASS" if r["ok"] else "FAIL"
            log(f"[{tag}] mirror/{r['source']}: {r['detail']}")

    # 2) 镜像通道本体可达性（与源无关，单独报告，便于定位是网络还是解析问题）
    reachable = fb_engine.wayback_available("https://example.com")
    log(f"[{'PASS' if reachable else 'FAIL'}] archive.org 可达性: "
        f"{'可用' if reachable else '不可达'}")

    # 3) 本地 LKG / 契约阈值只读概览，便于确认状态文件健康
    lkg = fb_engine.load_lkg()
    log(f"[INFO] LKG 记录源数: {len(lkg)} -> {sorted(lkg.keys())}")

    log("=== 兜底通道自检结束 ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
