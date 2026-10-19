#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""统计并列：把「名次接近」标成 1=1，只在上游公布容差时启用。

口径来源见 domain/__init__.py 的历史教训。此处只实现算法本身。
"""

import sys
from typing import Any

sys.path.insert(0, __file__.rsplit("\\", 1)[0].rsplit("/", 1)[0])

import boards as B  # noqa: E402


def build_tie_meta(source_id: str):
    """该榜的并列口径。返回 {'abs': 容差或 None, 'source': 出处或 None}。

    未列入白名单的榜返回空值 → apply_tie_ranking 不做合并，前端据此说明
    「上游未公布容差，名次按原始排序展示，相邻分差不代表显著性」。
    """
    t = B.tie_tolerances().get(source_id)
    if not t:
        return {"abs": None, "source": None}
    return {"abs": t.get("abs"), "source": t.get("source")}


def apply_tie_ranking(rows, tol=None):
    """为榜单行计算统计并列，返回**新列表**（不修改入参行对象）。

    tol 为 None 时不做任何合并，仅补齐 tie_rank=rank / tie_size=1，保证字段齐整。

    分组规则（tol 为绝对容差时）：按分数降序扫描；若某行与「当前并列组最高分」
    之差不超过 tol，则并入该组，否则另起一组。与**组首**比较而非与相邻行比较，
    可避免链式漂移（A≈B、B≈C 但 A≫C 仍被并成一组）。

    编号规则：并列组按出现顺序密集编号（1,1,2,2,2,3…），即 dense ranking，
    与 SuperCLUE 官方榜单的显示口径一致——本站不改动上游名次，读者交叉核对
    同一榜单时应看到相同数字。仅当全部行都有分数时启用密集编号；若存在无分数
    的行（编号会与原始名次错位），退回「取组内最小原始名次」以保证单调不回退。
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


def tie_policy(boards_keys):
    """逐榜并列口径汇总，供 cross_meta.tie_policy 使用。

    返回 {sid: {"tolerance": 容差或 None, "source": 出处或 None}}，
    覆盖传入的全部榜（含未列入白名单的），让前端能区分两种情况。
    """
    meta = build_tie_meta_all()
    return {sid: {"tolerance": meta[sid]["abs"], "source": meta[sid]["source"]}
            for sid in boards_keys}


def build_tie_meta_all():
    """所有已登记榜的并列口径。"""
    return {b.source_id: {"abs": b.tie_tolerance, "source": b.tie_rule}
            for b in B.BOARDS}


if __name__ == "__main__":
    # 快速自测：无容差时不合并，有容差时按组首比较
    demo = [{"model": "a", "score": 90, "rank": 1},
            {"model": "b", "score": 89.5, "rank": 2},
            {"model": "c", "score": 85, "rank": 3}]
    for tol in (None, 1.0):
        res = apply_tie_ranking(demo, tol)
        print(f"tol={tol}: {[(r['model'], r['tie_rank'], r['tie_size']) for r in res]}")
