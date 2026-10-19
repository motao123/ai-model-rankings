#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""数据契约：榜单 payload 的元信息（meta）字段校验。

动机
----
原先「数据契约」只校验 rows（行数下限 / 跌幅 / 分数完整度），而 11 个
meta 字段由 5 个 fetch_* 各自手写字符串键、main.py 用 payload.get() 静默
兜底。后果是：某个抓取器把 `"metric"` 写成 `"metrics"`，流水线不会报错、
不会告警、不会降级——页面只是安静地显示「—」。

这与项目一贯的立场冲突：README 写「字段缺失一律显示『—』，不报错、
不中断」，那条说的是**行内**字段（某个模型没有价格、没有 votes），
可以降级展示；而**榜单级** meta 字段缺失意味着这个源根本没被正确构造，
属于「坏数据进展示层」，应当拒绝。

本模块只负责把这条边界写清楚，并保持最小：

    validate_meta(source_id, payload) -> list[str]

返回违反项列表（空列表 = 通过）。刻意采用「返回理由列表」而非抛异常，
以便直接并入 check_contract 现有的 reasons 列表——降级链、Issue 上报、
日志措辞都无需改动，行为变化局限在「该不该拒绝」这一个判断上。

与 fallback.check_contract 的分工
--------------------------------
    行级契约（行数 / 跌幅 / 分数完整度）  → fallback.py
    元信息契约（本模块）                  → schema.py

两者同属「数据契约」，任一不通过即视为该源失败并进入降级链。
"""

# 榜单级必填字段。缺失任一即判该源失败。
#
# 字段口径：
#   board       原始榜名，展示用，不改写
#   metric      指标名（如 Arena Score / Avg. pass@1）
#   kind        榜单类别，决定前端「真人偏好 / 客观基准」分区
#   source_url  原始出处链接，前端必须可点验
#   rows        行数组
REQUIRED_META = ("board", "metric", "kind", "source_url", "rows")

# source_id 不在 REQUIRED_META 里，这是刻意为之：
# 它由调用方（check_contract 的 source_id 形参 / 降级链的字典键）承载，
# 抓取器返回的 payload 里带它是**可选**的。实测确认 merged.json 的
# boards[sid] 就不含该字段——main.build_merged 组装时由字典键代替。
# 若把 source_id 列为必填，会把 7 个在用源全部误拒——这是写契约时
# 「按理想模型而非实际产物」会踩的坑，故在此显式记录边界。
SOURCE_ID_OPTIONAL = True

# 时间戳刻意列为「三者有其一」而非固定某一个，因为三类数据源表达
# 「这份数据多新」的方式本就不同：
#   活源 / 镜像 / LKG / 历史快照 → fetched_at（抓取时刻）
#   人工兜底 data/manual/        → as_of（数据所属期次）+ reviewed_at（复核日）
#
# 实测确认 4 份人工文件全部只有 as_of/reviewed_at、没有 fetched_at。
# 若把 fetched_at 列为必填，会让**全部人工兜底数据被拒**——等于亲手
# 废除最后一层降级能力，这正是契约收紧最容易造成的反效果。
#
# 真正该拦的是「一个时间口径都没有」：那种情况前端无法计算滞后天数，
# 会把明显过期的数据静默呈现成无降级迹象的样子。
TIME_KEYS = ("fetched_at", "as_of", "publish_date")

# 合法取值枚举：拼错值的兜底是静默显示异常分类，比缺字段更难发现
VALID_KINDS = ("human_preference", "objective_benchmark")

# 允许缺失的可选字段：缺失只影响该字段对应的展示位，不阻断整个源
OPTIONAL_META = ("dataset_url", "license", "publish_date", "channel",
                 "price_unit", "retired", "retired_note", "manual",
                 "manual_note", "mirror_note", "data_period")


def validate_meta(source_id: str, payload) -> list:
    """校验榜单 meta 字段。返回违反项列表（空 = 通过）。

    与行级契约同构：只报告问题、不自己决定降级——是否降级由调用方
    （check_contract -> main 降级链）统一裁决，避免校验逻辑分裂成两套。
    """
    reasons = []
    if not isinstance(payload, dict):
        return ["payload 非 dict"]

    # 必填字段：空串 / None / 空列表都算缺失。
    # 刻意不用「键不存在」一种判断——上游若返回 `rows: []`，那是
    # 「抓到壳没抓到肉」，必须同样拒绝（行级契约也会拦，这里是双保险）。
    missing = []
    for key in REQUIRED_META:
        val = payload.get(key)
        if val is None or val == "" or val == [] or val == {}:
            missing.append(key)
    if missing:
        reasons.append(f"meta 缺必填字段: {missing}")

    # 时间口径：三选其一即可，全缺则无法呈现滞后天数
    if not any(payload.get(k) for k in TIME_KEYS):
        reasons.append(
            f"meta 缺时间字段（{'/'.join(TIME_KEYS)} 至少需其一）"
        )

    # kind 取值合法性：枚举值拼错时，前端会渲染成空分类标签，
    # 而页面各处都按 kind 分区——这类错误必须在上游拦住。
    kind = payload.get("kind")
    if kind is not None and kind != "" and kind not in VALID_KINDS:
        reasons.append(
            f"meta.kind 取值非法: {kind!r}（应为 {VALID_KINDS} 之一）"
        )

    # source_id 与注册名一致性：抓取器内部写错自己的 id，会导致
    # 契约阈值、LKG 记录、降级记录三方对不上（同一个源出现两条记录）。
    pid = payload.get("source_id")
    if pid and source_id and pid != source_id:
        reasons.append(
            f"meta.source_id 不匹配: payload={pid!r} 期望={source_id!r}"
        )

    return reasons


def describe_contract() -> dict:
    """契约口径自述，供方法论页展示（数字与代码同源，前端不得自行估算）。"""
    return {
        "required_meta": list(REQUIRED_META),
        "optional_meta": list(OPTIONAL_META) + (["source_id"] if SOURCE_ID_OPTIONAL else []),
        "time_keys_any_of": list(TIME_KEYS),
        "valid_kinds": list(VALID_KINDS),
        "source_id_optional": SOURCE_ID_OPTIONAL,
    }


if __name__ == "__main__":
    import json
    print(json.dumps(describe_contract(), ensure_ascii=False, indent=1))
