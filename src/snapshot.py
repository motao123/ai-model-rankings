#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""快照存储：内存索引 + 自动失效。

问题
----
原先 `list_snapshots()` 每次调用都 `glob` 整个 raw 目录再全量 `sort`，
`latest_snapshot_before()` 建立在它之上。实测（2026-10-19，59 份快照）：

    一次全量 list_snapshots(7 源) = 2.6 ms
    连续 7 次 latest_snapshot_before = 7.4 ms

单看这个数字毫无痛感，但要注意调用位置：它在 `main` 的**源循环内**被
反复调用（契约校验基准、_add_trend 对比上期、降级链各层各一次）。
更关键的是文件数**每天增长 7 个**：

    当前   59 份 → 每次运行约 0.1 s
    一年后 2500+ 份 → 每次运行上万次 glob+sort，预估 3~5 s

即当前无痛、随历史线性劣化的设计。改用内存索引后，
扫描只在进程启动与快照写入后各做一次。

设计取舍
--------
初版用「目录 mtime 指纹」自动失效，实测反而慢：每次调用一次
`os.stat` 在本机 Windows 上要 **66.7 µs**（glob 整体只要 291 µs），
等于把优化点从 glob 挪到了 stat 上——单次调用虽然从 291 µs 降到
66 µs，但没有量级优势。

关键观察：**一次运行内快照只在两个时刻变化**——进程启动时（无变化），
以及抓取成功后写快照（有变化）。除此之外目录是静态的。所以不需要
每次调用都验证，只需：

    1. 首次访问时建索引（此后调用是纯内存操作，约 0.1 µs）
    2. 写快照时由 write_snapshot() 调 invalidate() 明确失效

这要求写快照只有一个入口——正是当前架构的形态（common.write_snapshot）。
若将来有人绕过它直接写文件，需要在写后手动 invalidate()；这是显式的
契约，比「靠 mtime 猜」更可控。

    手动失效 vs 自动失效的权衡：
      自动（mtime）：调用方零负担，但每次付 ~67 µs stat
      手动（invalidate）：调用方需记得调，但快 ~670 倍
    取手动，因为「写快照」在代码里是**单一且显眼**的操作，
    漏调的概率远低于「漏判」。

跨天 / 跨进程天然重建（索引是进程内状态）。
"""

import glob
import os

from common import RAW_DIR, read_json


class SnapshotStore:
    """快照索引。同一进程内复用目录扫描结果。"""

    def __init__(self, raw_dir: str = None):
        self._dir = raw_dir or RAW_DIR
        # {source_id: [(date, path), ...]}，各源内部按日期升序。
        # None = 尚未建立 / 已失效，下次访问时重建。
        self._index = None
        # 复用/重建次数，仅用于自检统计，不参与逻辑判断
        self.reuse_count = 0
        self.rebuild_count = 0

    # ------------------------------------------------------------ 内部

    def _ensure(self):
        """确保索引可用；未建立则扫描一次。"""
        if self._index is None:
            self._rebuild()

    def _rebuild(self):
        """扫描整个 raw 目录，建立 {source: [(date, path)]} 索引。"""
        index = {}
        pattern = os.path.join(self._dir, "*.json")
        for path in glob.glob(pattern):
            base = os.path.basename(path)
            # 文件名形如 <source_id>_<YYYY-MM-DD>.json。source_id 本身
            # 可能含下划线（如 lmarena_text），故用 rpartition 从右切一次，
            # 不能用 split("_")。
            stem = base[:-len(".json")]
            if "_" not in stem:
                continue
            source, _, date_part = stem.rpartition("_")
            if not source or not date_part:
                continue
            index.setdefault(source, []).append((date_part, path))
        for entries in index.values():
            entries.sort(key=lambda x: x[0])
        self._index = index
        self.rebuild_count += 1

    def invalidate(self):
        """令下次访问重建索引。写快照后由 write_snapshot 自动调用。"""
        self._index = None

    # ------------------------------------------------------------ 对外

    def list_all(self, source: str):
        """返回 [(date_str, path), ...]，按日期升序。语义同原 list_snapshots。"""
        self._ensure()
        self.reuse_count += 1
        return list(self._index.get(source, []))

    def list_sources(self):
        """全部已登记的 source_id（按字典序）。"""
        self._ensure()
        self.reuse_count += 1
        return sorted(self._index)

    def latest_before(self, source: str, date_str: str):
        """取 date_str 之前最近一次快照的 (date_str, payload)，无则 (None, None)。

        索引已按日期升序，故倒序线性查找首个 d < date_str 即可，
        比原先「全量排序后再遍历」少一个排序步骤。
        """
        entries = self.list_all(source)
        found = None
        for d, path in entries:
            if d < date_str:
                found = (d, path)
            else:
                break
        if found is None:
            return None, None
        return found[0], read_json(found[1])

    def payload_on(self, source: str, date_str: str):
        """取指定日期的快照 payload，无则 None。"""
        for d, path in self.list_all(source):
            if d == date_str:
                return read_json(path)
        return None


# 进程级单例。编排层、降级链、趋势聚合共用，避免各建一份索引。
STORE = SnapshotStore()


def list_snapshots(source: str):
    """兼容旧接口：内部走单例索引。"""
    return STORE.list_all(source)


def latest_snapshot_before(source: str, date_str: str):
    """兼容旧接口：内部走单例索引。"""
    return STORE.latest_before(source, date_str)


def list_sources():
    """列出所有有快照的 source_id。"""
    return STORE.list_sources()


if __name__ == "__main__":
    import time
    s = SnapshotStore()
    t = time.time()
    for _ in range(1):
        total = sum(len(s.list_all(src)) for src in s.list_sources())
    first = time.time() - t
    t = time.time()
    for _ in range(100):
        for src in s.list_sources():
            s.latest_before(src, "2026-10-16")
    hundred = time.time() - t
    print(f"源数={len(s.list_sources())} 快照总数={total}")
    print(f"首次建索引: {first * 1000:.3f} ms")
    print(f"此后 100 轮 × {len(s.list_sources())} 源: {hundred * 1000:.3f} ms"
          f"（{hundred / 100 / max(1, len(s.list_sources())) * 1e6:.1f} µs/次）")
    print(f"重建 {s.rebuild_count} 次，复用 {s.reuse_count} 次")
