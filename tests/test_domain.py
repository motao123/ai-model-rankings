#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""领域层单元测试（零 IO，不需要 mock 网络）。

domain/ 下的函数全部是纯函数，因此可以直接用构造数据测——不需要
临时目录、不需要 mock requests。这正是把它们从 main.py 里拆出来的
主要收益：原先并列排名算法埋在编排代码中，要测它就得把整条抓取链路
都搭起来。

运行：python tests/test_domain.py
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))

from domain.tiebreak import apply_tie_ranking, build_tie_meta      # noqa: E402
from domain.trend import build_trend_series                        # noqa: E402
from domain import aggregate as AG                                 # noqa: E402

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
        print(f"         got ={got!r}"[:170])
        print(f"        want ={want!r}"[:170])


def section(title):
    print()
    print("-" * 66)
    print(title)
    print("-" * 66)


def rows(*spec):
    """构造 rows：spec 为 (model, score, rank)。"""
    return [{"model": m, "score": s, "rank": r} for m, s, r in spec]


def tie_map(rs):
    return [(r["model"], r["tie_rank"], r["tie_size"]) for r in rs]


# ================================================================ tiebreak
section("1. 统计并列")

src = rows(("a", 90, 1), ("b", 89.5, 2), ("c", 85, 3))
res = apply_tie_ranking(src, None)
check("tol=None -> 不合并，补齐 tie_rank", tie_map(res), [("a", 1, 1), ("b", 2, 1), ("c", 3, 1)])
check("tol=None -> 不修改入参",
      [(r["model"], r["rank"]) for r in src], [("a", 1), ("b", 2), ("c", 3)])
check("返回新列表（不是同一对象）", res is src, False)

res = apply_tie_ranking(src, 1.0)
check("tol=1.0 -> a/b 并列", tie_map(res), [("a", 1, 2), ("b", 1, 2), ("c", 2, 1)])

# 组首比较而非相邻比较：防止链式漂移
drift = rows(("a", 100, 1), ("b", 99.5, 2), ("c", 98.2, 3))
res = apply_tie_ranking(drift, 1.0)
check("组首比较：A/B 并列，C 不并入（防链式漂移）",
      tie_map(res), [("a", 1, 2), ("b", 1, 2), ("c", 2, 1)])

# 已有旧值必须被重置，不能 setdefault
stale = [{"model": "a", "score": 90, "rank": 1, "tie_rank": 99, "tie_size": 99},
         {"model": "b", "score": 89.5, "rank": 2, "tie_rank": 99, "tie_size": 99}]
res = apply_tie_ranking(stale, None)
check("旧 tie_rank/tie_size 被重置（防 setdefault 残留）",
      tie_map(res), [("a", 1, 1), ("b", 2, 1)])

# 无分数的行存在时，退回组内最小原始名次（a/c 分差 0.5 应并列，
# 但因存在无分数行，密集编号会与原始名次错位，故退回「取组内最小 rank」）
withnone = [{"model": "a", "score": 90, "rank": 1},
            {"model": "b", "score": None, "rank": 2},
            {"model": "c", "score": 89.5, "rank": 3}]
res = apply_tie_ranking(withnone, 1.0)
check("含无分数行时退回组内最小 rank",
      tie_map(res), [("a", 1, 2), ("b", 2, 1), ("c", 1, 2)])
check("无分数行不参与分组，tie_size 保持 1",
      res[1]["tie_size"], 1)

check("空列表 -> 返回空列表", apply_tie_ranking([], 1.0), [])
check("单行 -> 不合并", tie_map(apply_tie_ranking(rows(("a", 1, 1)), 1.0)), [("a", 1, 1)])
check("tol=0 视为不合并",
      tie_map(apply_tie_ranking(rows(("a", 1, 1), ("b", 1, 2)), 0)),
      [("a", 1, 1), ("b", 2, 1)])
check("tol 为负视为不合并",
      tie_map(apply_tie_ranking(rows(("a", 1, 1), ("b", 1, 2)), -1)),
      [("a", 1, 1), ("b", 2, 1)])

# 密集编号（1,1,2,2,3）
dense = rows(("a", 90, 1), ("b", 89.5, 2), ("c", 85, 3), ("d", 84.5, 4), ("e", 70, 5))
check("密集编号 1,1,2,2,3",
      [r["tie_rank"] for r in apply_tie_ranking(dense, 1.0)], [1, 1, 2, 2, 3])

section("2. 并列口径（元数据）")
check("白名单榜返回容差与出处",
      build_tie_meta("superclue"),
      {"abs": 1.0, "source": "SuperCLUE 官方口径：分差 1 分以内视为并列排名"})
check("非白名单榜返回空容差", build_tie_meta("lmarena_text"), {"abs": None, "source": None})
check("未登记的榜返回空容差", build_tie_meta("nope"), {"abs": None, "source": None})


# ================================================================ aggregate
section("3. 跨榜聚合")

def fake_enrich(name, org=None):
    """最小主数据替身：按名字前缀给固定厂商/国别。"""
    vendor = {"claude": "Anthropic", "gemini": "Google DeepMind",
              "gpt": "OpenAI", "qwen": "阿里巴巴"}.get(
        name.split("-")[0], "未标注")
    region = {"Anthropic": "us", "Google DeepMind": "us", "OpenAI": "us",
              "阿里巴巴": "cn"}.get(vendor, "other")
    return {"id": name.lower(), "display_name": name, "vendor": vendor,
            "region": region, "open": None, "variant": None, "registered": True}


ORDER = ["lmarena_text", "aa_intelligence", "lmarena_agent"]
# 直接用真实注册表里的榜，不伪造 BY_ID：method_groups() 从 BOARDS 派生，
# 往 BY_ID 里塞临时条目不会影响分组，反而会让人误以为分组生效了。
collected = {
    "lmarena_text": {"metric": "Arena Score", "stale": False, "rows": [
        {"model": "claude-x", "score": 10, "rank": 1},
        {"model": "gemini-y", "score": 8, "rank": 2}]},
    "aa_intelligence": {"metric": "Index", "stale": True, "rows": [
        {"model": "claude-x", "score": 20, "rank": 3},
        {"model": "gemini-y", "score": 9, "rank": 1}]},
    "lmarena_agent": {"metric": "IPS", "stale": False, "rows": [
        {"model": "gpt-z", "score": 5, "rank": 1}]},
}
# lmarena_text 与 lmarena_agent 同属 human；aa_intelligence 属 objective。
# 因此 claude-x 跨 2 类方法论 -> verified；gpt-z 仅单榜 -> 不进 cross。

cross, cmeta = AG.build_cross(collected, ORDER, fake_enrich)

check("仅收录 >=2 榜的模型", sorted(m["id"] for m in cross), ["claude-x", "gemini-y"])
check("单榜模型计入 single_board", cmeta["single_board"], 1)
check("cross_meta.boards 顺序遵循 board_order", cmeta["boards"], ORDER)
cl = next(m for m in cross if m["id"] == "claude-x")
check("上榜数正确", cl["appearance_count"], 2)
check("含降级源的模型标记 has_stale", cl["has_stale"], True)
check("厂商归一（Anthropic）", cl["vendor"], "Anthropic")
check("跨方法论覆盖 -> verified", (cl["group_count"], cl["confidence"]), (2, "verified"))
gm = next(m for m in cross if m["id"] == "gemini-y")
check("跨方法论 2 类 -> verified", (gm["group_count"], gm["confidence"]), (2, "verified"))

section("3b. 未推知厂商的模型 -> 参考项（列出但标灰，不隐藏）")
# 同一模型出现在两个榜，才进得了 cross（单榜模型不进跨榜表）
ref_cross, ref_cm = AG.build_cross(
    {"lmarena_text": {"metric": "M", "rows": [{"model": "weird-one", "score": 1, "rank": 1}]},
     "aa_intelligence": {"metric": "M", "rows": [{"model": "weird-one", "score": 2, "rank": 1}]}},
    ["lmarena_text", "aa_intelligence"], fake_enrich)
weird = next(m for m in ref_cross if m["id"] == "weird-one")
check("厂商不可识别 -> reference_only", weird["reference_only"], True)
check("国别为 other", weird["region"], "other")
check("参考项仍收录（隐藏数据比标注数据更糟）", len(ref_cross), 1)

# 与可识别厂商的模型混排时，参考项沉底
mixed, _ = AG.build_cross(
    {"lmarena_text": {"metric": "M", "rows": [
        {"model": "weird-one", "score": 99, "rank": 1},
        {"model": "claude-x", "score": 1, "rank": 2}]},
     "aa_intelligence": {"metric": "M", "rows": [
        {"model": "weird-one", "score": 99, "rank": 1},
        {"model": "claude-x", "score": 1, "rank": 2}]}},
    ["lmarena_text", "aa_intelligence"], fake_enrich)
check("参考项沉底排序（即使名次更好）",
      [m["id"] for m in mixed], ["claude-x", "weird-one"])

section("3c. 未列出的源排到末尾")
extra = dict(collected, livecodebench={"metric": "M", "rows": [{"model": "z", "score": 1, "rank": 1}]})
_, cm2 = AG.build_cross(extra, ORDER, fake_enrich)
check("未列出的源排到末尾", cm2["boards"], ORDER + ["livecodebench"])

section("4. 同榜多变体取最好名次")
multi = {"lmarena_text": {"metric": "M", "rows": [
    {"model": "claude-x", "score": 9, "rank": 5, "id": "claude-x"},
    {"model": "claude-x", "score": 10, "rank": 2, "id": "claude-x"}]},
    "aa_intelligence": {"metric": "M", "rows": [
        {"model": "claude-x", "score": 8, "rank": 1, "id": "claude-x"}]}}
c2, _ = AG.build_cross(multi, ["lmarena_text", "aa_intelligence"], fake_enrich)
m2 = next(m for m in c2 if m["id"] == "claude-x")
check("同榜多变体取最好名次", m2["appearances"]["lmarena_text"]["rank"], 2)

section("5. 榜单组装")
boards = AG.build_boards(
    {"superclue": {"board": "SuperCLUE", "metric": "综合得分",
                   "kind": "objective_benchmark", "source_url": "https://x",
                   "fetched_at": "2026-10-19T00:00:00Z", "stale": True,
                   "stale_from": "2026-10-01",
                   "rows": [{"model": "m1", "score": 90, "rank": 1},
                            {"model": "m2", "score": 89.5, "rank": 2}]}},
    ["superclue"], lambda p: 18)
b = boards["superclue"]
check("task_label 从注册表取", b["task_label"], "中文综合")
check("stale_days 由注入函数计算", b["stale_days"], 18)
check("tie_tolerance 取自白名单", b["tie_tolerance"], 1.0)
check("tie_rule 带有出处", "SuperCLUE 官方口径" in (b["tie_rule"] or ""), True)
check("stale=False 时 stale_days 为 0",
      AG.build_boards({"superclue": {"board": "b", "metric": "m", "kind": "objective_benchmark",
                                     "source_url": "u", "fetched_at": "t", "rows": [],
                                     "stale": False}}, ["superclue"], lambda p: 99
                       )["superclue"]["stale_days"], 0)

section("6. 维度冠军")
lb = {"aa_intelligence": {"metric": "Index", "retired": False, "rows": [
        {"model": "a", "score": 50, "rank": 1, "price": 3.0, "id": "a"},
        {"model": "b", "score": 40, "rank": 2, "price": 1.0, "id": "b"}]},
      "open_llm": {"metric": "Avg", "retired": True, "rows": [
        {"model": "z", "score": 99, "rank": 1, "id": "z"}]}}
leaders = AG.compute_dimension_leaders(lb)
lead_map = {x["key"]: x["model"] for x in leaders}
check("综合智能冠军为 a", lead_map.get("aa_intelligence"), "a")
check("最低价格单独成项", lead_map.get("aa_intelligence_cheapest"), "b")
check("已退役榜不产出冠军", "open_llm" not in lead_map, True)
check("退役榜也不参与最低价", len(leaders) == 2, True)

check("空榜 -> None", AG.leader_from_board({}, "aa_intelligence", "x", "y"), None)
check("全无分数 -> None",
      AG.leader_from_board({"aa_intelligence": {"rows": [{"model": "a", "rank": 1}]}},
                           "aa_intelligence", "x", "y"), None)

section("7. 参考组统计")
cross2 = [{"id": "x", "reference_only": True}, {"id": "y", "reference_only": False}]
ref = AG.compute_reference_only(cross2)
check("参考组计数", ref["count"], 1)
check("参考组 id 列表", ref["ids"], ["x"])
check("规则文案非空", len(ref["rule"]) > 10, True)


# ================================================================ trend
section("8. 趋势序列")

def simple_enrich(name, org=None):
    return {"id": name.lower(), "display_name": name, "vendor": "V",
            "region": "us", "open": None, "variant": None, "registered": True}


snaps = [
    ("2026-10-01", {"board": "B", "metric": "M", "source_url": "u", "rows": [
        {"model": "A", "rank": 2}, {"model": "B", "rank": 1}, {"model": "C", "rank": 3}]}),
    ("2026-10-02", {"board": "B", "metric": "M", "source_url": "u", "rows": [
        {"model": "A", "rank": 1}, {"model": "B", "rank": 2}]}),
    ("2026-10-03", {"board": "B", "metric": "M", "source_url": "u", "rows": [
        {"model": "A", "rank": 1}]}),
]
t = build_trend_series(snaps, simple_enrich, top_n=3)
check("日期序列", t["dates"], ["2026-10-01", "2026-10-02", "2026-10-03"])
ranks = {m["id"]: m["ranks"] for m in t["models"]}
check("A 的名次轨迹", ranks["a"], [2, 1, 1])
# 追踪名单取自**最新一期**的 Top N：B 在 10-03 已掉出最新榜，
# 因此不会被追踪——这不是「未上榜记 None」，是「压根不在追踪名单里」。
check("追踪名单取自最新一期 TopN", sorted(ranks), ["a"])
check("A 在三期的名次完整", len(ranks["a"]), 3)

section("8b. 追踪名单内的模型某期缺席 -> None")
snaps2 = [
    ("2026-10-01", {"board": "B", "rows": [
        {"model": "A", "rank": 1}, {"model": "B", "rank": 2}]}),
    ("2026-10-02", {"board": "B", "rows": [{"model": "A", "rank": 1}]}),
]
t2 = build_trend_series(snaps2, simple_enrich, top_n=2)
r2 = {m["id"]: m["ranks"] for m in t2["models"]}
check("追踪名单来自最新一期，故只有 A", sorted(r2), ["a"])
check("A 两期都在榜", r2["a"], [1, 1])

# 若最新一期含 B 而早期缺 B，则 B 会被追踪且缺口为 None
snaps3 = [
    ("2026-10-01", {"board": "B", "rows": [{"model": "A", "rank": 1}]}),
    ("2026-10-02", {"board": "B", "rows": [
        {"model": "A", "rank": 2}, {"model": "B", "rank": 1}]}),
]
t3 = build_trend_series(snaps3, simple_enrich, top_n=2)
r3 = {m["id"]: m["ranks"] for m in t3["models"]}
check("早期缺席记为 None（不补 0、不插值）", r3["b"], [None, 1])

check("空快照列表 -> None", build_trend_series([], simple_enrich), None)
check("最新快照无 rows -> None",
      build_trend_series([("d", {"rows": []})], simple_enrich), None)

# max_points 截断
long_snaps = [(f"2026-10-{i:02d}", {"rows": [{"model": "A", "rank": 1}]}) for i in range(1, 8)]
t2 = build_trend_series(long_snaps, simple_enrich, max_points=3)
check("max_points 截断生效", len(t2["dates"]), 3)

print()
print("=" * 66)
print(f"共 {_count} 项检查，{len(_fails)} 项失败")
if _fails:
    for f in _fails:
        print(f"  - {f}")
print("=" * 66)
sys.exit(1 if _fails else 0)
