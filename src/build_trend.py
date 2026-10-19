#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""趋势数据落盘：遍历快照 → 交给 domain.trend 计算 → 写 data/trend.json。

前端的历史趋势折线读 data/trend.json。聚合逻辑已迁入 domain/trend.py
（纯函数、可单测）；本文件只负责 IO：读快照目录、调用、落盘。

只使用快照里的原始 rank，不做任何跨日插值或分数换算。快照越多，折线越长。
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from common import DATA_DIR, read_json, write_json, log, warn, RAW_DIR  # noqa: E402
from models import enrich                                              # noqa: E402
from snapshot import STORE                                             # noqa: E402
from domain.trend import (                                             # noqa: E402
    build_trend_from_store, TOP_N_PER_BOARD, MAX_POINTS,
)


def build_trend():
    if not os.path.isdir(RAW_DIR):
        warn("无 raw 快照目录，跳过趋势聚合")
        return None

    trend = build_trend_from_store(STORE, enrich, read_json,
                                   TOP_N_PER_BOARD, MAX_POINTS)
    trend["generated_from"] = "data/raw snapshots"
    write_json(os.path.join(DATA_DIR, "trend.json"), trend)
    log(f"趋势聚合完成：{len(trend['boards'])} 个榜单")
    return trend


if __name__ == "__main__":
    build_trend()
