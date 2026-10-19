#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""数据契约与榜单注册表的自检套件。

不依赖 pytest（项目刻意不引入构建/测试框架，见架构文档「方案对比」——
上游改版时的适配成本比工程完备性更重要）。约定：

    python tests/test_contracts.py     全部检查，非零退出码表示失败

覆盖：
  1. schema.validate_meta —— meta 契约的各类违反项
  2. fallback.check_contract —— 行级 + meta 双层契约、未登记源的 fail-safe
  3. boards.validate —— 榜单注册表自洽性
  4. 模型注册表自检（正式名能否解析回自身）
  5. 真实数据抽样：7 个在用源 + 人工兜底 + 历史快照均应通过

新增约束时在这里补一条断言，而不是散落到各处临时脚本——
契约的价值恰恰在于「不变量被持续强制」，一次性验证等于没验证。
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))

import boards as B        # noqa: E402
import fallback as fb     # noqa: E402
from common import read_json, list_snapshots  # noqa: E402
from models import registry_stats            # noqa: E402
from schema import validate_meta             # noqa: E402

_fails = []
_count = 0


def check(label, got, want):
    global _count
    _count += 1
    ok = got == want
    if not ok:
        _fails.append(label)
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    if not ok:
        print(f"         got ={got!r}"[:150])
        print(f"        want ={want!r}"[:150])


def section(title):
    print()
    print("-" * 66)
    print(title)
    print("-" * 66)


def mk(sid, n):
    """构造一个 meta 齐备、n 行的合法榜单 payload。"""
    return {
        "source_id": sid,
        "board": "B", "metric": "M",
        "kind": "human_preference" if sid.startswith("lmarena") else "objective_benchmark",
        "source_url": "https://example.invalid/x", "fetched_at": "2026-10-19T00:00:00Z",
        "rows": [{"model": f"m{i}", "score": 1.0} for i in range(n)],
    }


# ---------------------------------------------------------------- schema
section("1. meta 契约")
good = mk("aa_intelligence", 8)
check("齐备 payload 通过", validate_meta("aa_intelligence", good), [])

for field in ("board", "metric", "kind", "source_url", "fetched_at", "rows"):
    miss = dict(good)
    miss.pop(field)
    check(f"缺 {field} -> 拒绝",
          any(field in x for x in validate_meta("aa_intelligence", miss)), True)

typo = dict(good)
typo["metrics"] = typo.pop("metric")
check("metric 拼成 metrics -> 仍识别为缺失",
      any("metric" in x for x in validate_meta("aa_intelligence", typo)), True)

check("kind 非法值 -> 拒绝",
      any("kind" in x for x in validate_meta("aa_intelligence", dict(good, kind="objective"))), True)
check("source_id 不匹配 -> 拒绝",
      any("source_id" in x for x in validate_meta("aa_intelligence", dict(good, source_id="x"))), True)

notime = dict(good)
notime.pop("fetched_at")
check("时间口径全缺 -> 拒绝",
      any("时间字段" in x for x in validate_meta("aa_intelligence", notime)), True)

nosid = dict(good)
nosid.pop("source_id")
check("不带 source_id -> 允许（由调用方承载）",
      validate_meta("aa_intelligence", nosid), [])

manual = {"source_id": "superclue", "board": "B", "metric": "M",
          "kind": "objective_benchmark", "source_url": "https://example.invalid/x",
          "as_of": "2026-10-02", "reviewed_at": "2026-10-09",
          "rows": [{"model": "m", "score": 1.0}]}
check("人工兜底口径（as_of 而非 fetched_at）-> 允许",
      validate_meta("superclue", manual), [])

check("非 dict payload -> 拒绝", validate_meta("aa_intelligence", "x"),
      ["payload 非 dict"])

# ---------------------------------------------------------------- fallback
section("2. 行级契约与未登记源 fail-safe")
check("未登记源 / 4 行 -> 拒绝", fb.check_contract("brand_new", mk("brand_new", 4), None)[0], False)
check("未登记源 / 25 行 -> 仍拒绝", fb.check_contract("brand_new", mk("brand_new", 25), None)[0], False)
check("未登记源拒绝理由含「契约未登记」",
      any("契约未登记" in x for x in fb.check_contract("brand_new", mk("brand_new", 4), None)[1]), True)

check("已登记 lmarena_text / 3 行 -> 拒绝", fb.check_contract("lmarena_text", mk("lmarena_text", 3), None)[0], False)
check("已登记 lmarena_text / 30 行 -> 通过", fb.check_contract("lmarena_text", mk("lmarena_text", 30), None)[0], True)
check("已登记 superclue / 4 行 -> 通过（宽松阈值保留）", fb.check_contract("superclue", mk("superclue", 4), None)[0], True)
check("已登记 livecodebench / 2 行 -> 拒绝（下限 5）", fb.check_contract("livecodebench", mk("livecodebench", 2), None)[0], False)
check("已登记源不报「契约未登记」",
      any("契约未登记" in x for x in fb.check_contract("superclue", mk("superclue", 4), None)[1]), False)

noScore = mk("lmarena_text", 30)
for r in noScore["rows"]:
    r["score"] = None
check("分数全缺失 -> 拒绝", fb.check_contract("lmarena_text", noScore, None)[0], False)

# ---------------------------------------------------------------- boards
section("3. 榜单注册表")
check("validate() 无问题", B.validate(), [])
check("TAB_ORDER 覆盖全部榜", sorted(B.TAB_ORDER), sorted(b.source_id for b in B.BOARDS))
check("BOARD_ORDER 覆盖全部榜", sorted(B.board_order()), sorted(b.source_id for b in B.BOARDS))
check("并列白名单只含公布容差的榜",
      list(B.tie_tolerances().keys()),
      [b.source_id for b in B.BOARDS if b.tie_tolerance is not None])

# ---------------------------------------------------------------- models
section("4. 模型主数据层")
rs = registry_stats()
check("正式名可解析回自身（变体折叠无误伤）", rs["self_check_pass"], True)
if not rs["self_check_pass"]:
    for f in rs["self_check_failures"]:
        print(f"         失败: {f}")

# ---------------------------------------------------------------- 真实数据
section("5. 真实数据抽样（7 源 + 人工兜底 + 历史快照）")
merged = read_json(os.path.join(ROOT, "data", "merged.json"), default={}) or {}
for sid, board in (merged.get("boards") or {}).items():
    check(f"在用源 {sid:16s} 通过 meta 契约", validate_meta(sid, board), [])

mdir = os.path.join(ROOT, "data", "manual")
if os.path.isdir(mdir):
    for name in sorted(os.listdir(mdir)):
        if name.endswith(".json"):
            sid = name[:-5]
            check(f"人工兜底 {sid:14s} 通过", validate_meta(sid, read_json(os.path.join(mdir, name))), [])

for sid in (merged.get("boards") or {}):
    snaps = list_snapshots(sid)
    if snaps:
        check(f"最新快照 {sid:14s} 通过", validate_meta(sid, read_json(snaps[-1][1])), [])

# ---------------------------------------------------------------- snapshot
section("6. 快照索引（与旧 glob 实现语义一致）")
from snapshot import SnapshotStore          # noqa: E402
import tempfile                              # noqa: E402

s = SnapshotStore()
# 索引结果须与「全量 glob + 排序」完全一致
for sid in sorted(s.list_sources()):
    entries = s.list_all(sid)
    dates = [d for d, _ in entries]
    check(f"索引 {sid:16s} 日期升序", dates, sorted(dates))
    check(f"索引 {sid:16s} 无重复日期", len(dates) == len(set(dates)), True)

# latest_before 边界：早于全部快照 / 晚于全部快照 / 恰好等于某日期
probe_source = sorted(s.list_sources())[0]
entries = s.list_all(probe_source)
if entries:
    first_d = entries[0][0]
    mid_d = entries[len(entries) // 2][0]
    check("latest_before 早于全部快照 -> (None, None)",
          s.latest_before(probe_source, "2000-01-01"), (None, None))
    check("latest_before 晚于全部快照 -> 返回最新",
          s.latest_before(probe_source, "2099-01-01")[0], entries[-1][0])
    check("latest_before 命中该日期本身不返回自己",
          s.latest_before(probe_source, mid_d)[0] < mid_d, True)

# 失效机制：新建文件后必须 invalidate 才能看到
with tempfile.TemporaryDirectory() as td:
    t = SnapshotStore(td)
    check("空目录无源", t.list_sources(), [])
    import os as _os
    with open(_os.path.join(td, "foo_2026-01-01.json"), "w") as fh:
        fh.write("{}")
    check("新建文件后（未 invalidate）仍为空", t.list_sources(), [])
    t.invalidate()
    check("invalidate 后可见", t.list_sources(), ["foo"])
    # source_id 含下划线时按右切解析，不能用 split("_")
    with open(_os.path.join(td, "lmarena_text_2026-01-02.json"), "w") as fh:
        fh.write("{}")
    t.invalidate()
    check("source_id 含下划线解析正确", t.list_all("lmarena_text"),
          [("2026-01-02", _os.path.join(td, "lmarena_text_2026-01-02.json"))])
    # 无日期部分的文件名应被跳过而非误解析
    with open(_os.path.join(td, "nounderscore.json"), "w") as fh:
        fh.write("{}")
    t.invalidate()
    check("无下划线文件名被跳过", "nounderscore" not in t.list_sources(), True)

# ---------------------------------------------------------------- sources
section("7. 数据源适配器注册")
from sources import load_all, all_source_ids      # noqa: E402
import boards as _B                               # noqa: E402

ads = load_all()
check("适配器已注册", len(ads) > 0, True)
check("适配器产出的 source_id 与注册表完全一致",
      sorted(all_source_ids()), sorted(b.source_id for b in _B.BOARDS))
check("source_id 无重复", len(all_source_ids()) == len(set(all_source_ids())), True)

for ad in ads:
    name = type(ad).__name__
    check(f"{name:22s} 声明了 source_ids", bool(ad.source_ids), True)
    check(f"{name:22s} source_id 已在注册表登记",
          all(s in _B.BY_ID for s in ad.source_ids), True)
    check(f"{name:22s} mirror_ok 为布尔", isinstance(ad.mirror_ok, bool), True)
    # 声明支持镜像就必须给出可查询的 URL
    if ad.mirror_ok:
        check(f"{name:22s} 声明镜像则必须有 source_url", bool(ad.source_url), True)
    check(f"{name:22s} 有可调用的 fetch", callable(getattr(ad, "fetch", None)), True)

# 镜像声明与 boards.BoardSpec.mirror_ok 必须一致：两处都可能成为唯一真值源
for ad in ads:
    mod = sys.modules[type(ad).__module__]
    for sid in ad.source_ids:
        check(f"{sid:16s} 适配器与注册表的 mirror_ok 一致",
              bool(ad.mirror_ok) == bool(_B.BY_ID[sid].mirror_ok), True)

# ---------------------------------------------------------------- fetch policy
section("8. 重抓频率策略")
check("未登记源默认每日抓", _B.fetch_every_days("nope"), 0)
check("从未抓过的源必须抓", _B.should_fetch_today("superclue", "2026-10-19", None), True)
check("每日榜：刚抓过也要抓",
      _B.should_fetch_today("lmarena_text", "2026-10-19", "2026-10-19"), True)
check("每周榜：同一天不重复抓",
      _B.should_fetch_today("superclue", "2026-10-19", "2026-10-19"), False)
check("每周榜：第 7 天抓", _B.should_fetch_today("superclue", "2026-10-26", "2026-10-19"), True)
check("每周榜：第 6 天不抓", _B.should_fetch_today("superclue", "2026-10-25", "2026-10-19"), False)
check("日期不可解析时保守抓取",
      _B.should_fetch_today("superclue", "2026-10-19", "not-a-date"), True)

# 关键回归：降频判据不能与 retired 标签挂钩（实测 open_llm retired=True
# 但内容每天变，superclue/livecodebench retired=False 但内容不变）
for b in _B.BOARDS:
    if b.retired:
        check(f"{b.source_id:16s} retired=True 但未降频（分页顺序抖动，需每日）",
              b.fetch_every_days, 0)
check("superclue 已降频（双月期次）", _B.fetch_every_days("superclue"), 7)
check("livecodebench 已降频（实测无新题）", _B.fetch_every_days("livecodebench"), 7)

print()
print("=" * 66)
print(f"共 {_count} 项检查，{len(_fails)} 项失败")
if _fails:
    for f in _fails:
        print(f"  - {f}")
print("=" * 66)
sys.exit(1 if _fails else 0)
