#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""榜单注册表：一个榜单的完整静态定义，声明一次就够。

解决的问题
----------
此前同一个「有哪些榜、各榜什么口径」的知识散落在 7 个地方：

    main.py 的 BOARD_ORDER          tab 顺序
    main.py 的 BOARD_TASK_LABEL     中文任务名
    main.py 的 METHOD_GROUPS        方法论分组（human/objective/chinese）
    main.py 的 _PREF_BOARDS         默认代表榜
    main.py 的 TIE_TOLERANCE        并列容差 + 出处
    main.py 的 DIMENSION_LEADERS    冠军摘要槽位
    fallback.py 的 CONTRACTS        契约阈值

新增一个榜要改 6 处（还不算前端的 BOARD_TAB_ORDER），漏一处不报错，
只是静默用旧值。最直接的证据是 index.html 里那句注释——
「与 src/main.py 的 BOARD_TASK_LABEL 保持一致」：作者用注释承认了
这���双份真相源。

本模块把这些收敛成一个声明式元组：BOARDS。每个榜的信息只写一遍，
其余模块（编排层、契约层、前端展示元信息）都从��里派生。

设计约束
--------
1. 纯声明，无逻辑、无 IO。可被任意模块 import，也可被测试直接比对。
2. 迁移是「等价搬移」：所有默认值与 main.py 原值逐字一致，由
   .tmp 阶段的常量基线比对脚本保证，不做任何顺手优化——避免重构
   夹带行为变更。
3. 方法论版本号与变更记录也放在这里：它们描述的是「这套规则表长
   什么样」，与规则表同源，避免再次分叉。
"""

import datetime
from dataclasses import dataclass


@dataclass(frozen=True)
class BoardSpec:
    """一个榜单的完整静态定义。

    用 frozen=True 是刻意的：注册表是只读的真值源，运行期任何试图
    修改它的代码都是 bug，应当立刻暴露而不是静默生效。
    """

    source_id: str
    board: str                    # 原始榜名（展示用，不改写）
    task_label: str               # 中文任务名（双层命名的「任务名」层）
    metric: str                   # 指标名
    kind: str                     # human_preference | objective_benchmark
    method_group: str             # human | objective | chinese（共识置信度分组）
    order: int                    # 前端 tab / 展示顺序
    min_rows: int = 20            # 契约：行数下限
    max_drop_ratio: float = 0.35  # 契约：较上期行数跌幅容忍度

    # 统计并列：仅上游公布容差口径的榜才启用，其余保留原始名次。
    # tie_rule 必须给出处（供页面引用），否则前端会说明「未公布容差」。
    tie_tolerance: float | None = None
    tie_rule: str | None = None

    retired: bool = False         # 已退役归档榜（不产出「当前第一」）
    retired_note: str = ""

    # 抓取频率：0 = 每日（默认）；N = 每 N 天至少抓一次。
    #
    # 判据不是「是否已退役」——实测证明 retired 完全不能预测内容变化：
    #   open_llm（retired=True）9 期里内容 checksum 变了 8 次，
    #   因为 HF datasets-server 的分页顺序不稳定，同分数模型位置随机抖动，
    #   降频只会加剧展示层抖动；
    #   superclue / livecodebench（retired=False）8~9 期里内容一次没变，
    #   前者是双月/年度期次，后者是滚动更新但当日无新题。
    #
    # 真正的判据是 publish_date 是否推进（见 fetch_policy 模块文档）。
    # 实测：publish_date 变化次数与内容变化次数高度一致，唯二例外是
    # open_llm（publish_date 恒定而内容抖动 = 重排噪声，不是新数据）。
    fetch_every_days: int = 0

    # 默认并列展示的代表榜（跨榜表代表名次取值优先级）
    pref_for_display: bool = False

    # 冠军摘要槽位：只陈述「某榜上排第一的是谁」这一事实，不做跨榜换算
    leader_slot: str = ""         # 中文维度名；空表示不入摘要
    leader_basis: str = ""        # 该维度的度量依据（必须可溯源）

    mirror_ok: bool = False       # 是否支持第三方镜像（Wayback）通道


# 榜单顺序即前端 tab 顺序（order 字段），kind 决定「真人偏好 / 客观基准」分区。
BOARDS = (
    BoardSpec(
        source_id="lmarena_text",
        board="LMArena 文本总榜（真人盲测）",
        task_label="对话偏好",
        metric="Arena Score",
        kind="human_preference",
        method_group="human",
        order=1,
        min_rows=20, max_drop_ratio=0.35,
        pref_for_display=True,
        leader_slot="对话偏好",
        leader_basis="LMArena Text Arena Score",
    ),
    BoardSpec(
        source_id="aa_intelligence",
        board="Artificial Analysis 智能指数榜",
        task_label="综合智能",
        metric="Intelligence Index",
        kind="objective_benchmark",
        method_group="objective",
        order=2,
        min_rows=5, max_drop_ratio=0.30,
        pref_for_display=True,
        leader_slot="综合智能",
        leader_basis="Artificial Analysis Intelligence Index",
        mirror_ok=True,
    ),
    BoardSpec(
        source_id="superclue",
        board="SuperCLUE 中文大模型综合榜",
        task_label="中文综合",
        metric="综合得分",
        kind="objective_benchmark",
        method_group="chinese",
        order=3,
        min_rows=3, max_drop_ratio=0.40,
        # SuperCLUE 官方口径：「为减少波动影响，榜单将分差 1 分值内的模型
        # 视为并列排名」。出处必须随规则一起走，否则无法在页面溯源。
        tie_tolerance=1.0,
        tie_rule="SuperCLUE 官方口径：分差 1 分以内视为并列排名",
        pref_for_display=True,
        leader_slot="中文综合",
        leader_basis="SuperCLUE 智能指数",
        # 上游是双月 / 年度期次，实测 8 期快照内容 checksum 一次未变
        # （publish_date 恒为 2026-07-01）。每日重抓纯属浪费配额。
        fetch_every_days=7,
    ),
    BoardSpec(
        source_id="lmarena_webdev",
        board="Code Arena / WebDev 榜（真人盲测）",
        task_label="前端生成",
        metric="Arena Score",
        kind="human_preference",
        method_group="human",
        order=4,
        min_rows=10, max_drop_ratio=0.35,
        pref_for_display=True,
    ),
    BoardSpec(
        source_id="lmarena_agent",
        board="Agent Arena 榜（真人盲测）",
        task_label="智能体交互",
        metric="IPS Score",
        kind="human_preference",
        method_group="human",
        order=5,
        min_rows=5, max_drop_ratio=0.35,
    ),
    BoardSpec(
        source_id="livecodebench",
        board="LiveCodeBench 编程榜（防污染滚动更新）",
        task_label="代码生成",
        metric="Avg. pass@1 (%)",
        kind="objective_benchmark",
        method_group="objective",
        order=6,
        min_rows=5, max_drop_ratio=0.30,
        leader_slot="代码生成",
        leader_basis="LiveCodeBench pass@1",
        # 名义上是「滚动更新」，但实测 9 期快照内容 checksum 一次未变——
        # 官方每天并不真的出新题。降为每周一次，题目更新仍能在 7 天内跟上。
        fetch_every_days=7,
    ),
    BoardSpec(
        source_id="open_llm",
        board="HF Open LLM Leaderboard v2（开源·已退役归档）",
        task_label="开源通用",
        metric="Average (%)",
        kind="objective_benchmark",
        method_group="objective",
        order=7,
        min_rows=10, max_drop_ratio=0.30,
        retired=True,
        retired_note="该榜单已于 2025 年 3 月退役，此处为归档快照，仅供开源模型横向参考。",
        # 注意：这里**不**降频，尽管它是已退役归档榜。
        # 实测 9 期里内容 checksum 变了 8 次，第一名在两个模型间反复跳动——
        # HF datasets-server 分页顺序不稳定，而本榜按 Average 降序取 Top 60，
        # 同分数模型的相对位置随分页顺序抖动。这是「排序不稳定」而非
        # 「每日新数据」，降频只会让展示层长期停在一个随机的切片上。
        fetch_every_days=0,
    ),
)

BY_ID = {b.source_id: b for b in BOARDS}

# ---------------------------------------------------------------- 派生视图
# 下面这些是从 BOARDS 推导出的兼容视图。它们不是「第二份真相」，
# 而是为了让调用方不必每次都写推导表达式——派生关系在定义处唯一。


def board_order() -> list:
    """tab / 展示顺序的 source_id 列表。"""
    return [b.source_id for b in sorted(BOARDS, key=lambda x: x.order)]


# 前端 tab 的展示顺序：**按机构归类**，把 LMArena 的三个子榜排在一起，
# 让同一来源的榜单在切换时连续。
#
# 与 board_order()（数据编排顺序：总榜 → 客观基准 → 子榜）刻意不同——
# 后者服务于「跨榜表默认并列哪几列」的代表榜选择，前者服务于读者浏览。
# 两者不一致是原设计的既有事实，本次迁移原样保留，不在去重时夹带
# 视觉顺序变更。若将来要统一，应作为一次独立的视觉调整并先行确认。
TAB_ORDER = (
    "lmarena_text", "lmarena_webdev", "lmarena_agent",
    "aa_intelligence", "superclue", "livecodebench", "open_llm",
)


def task_labels() -> dict:
    return {b.source_id: b.task_label for b in BOARDS}


def method_groups() -> dict:
    return {b.source_id: b.method_group for b in BOARDS}


def pref_boards() -> list:
    """默认代表榜优先级（跨榜表「代表名次」取值顺序）。"""
    return [b.source_id for b in BOARDS if b.pref_for_display]


def tie_tolerances() -> dict:
    """统计并列白名单：{sid: {"abs": 容差, "source": 出处}}。

    只收录**上游公布容差口径**的榜（当前仅 superclue），其余榜不出现在
    这个字典里。

    刻意不返回「全部 7 个源、容差为 null」的完整映射：调用方
    （main._tie_meta / cross_meta.tie_policy）依赖「键不存在 = 该榜不做
    并列」这一语义来区分两种情况，页面上据此显示两种不同的说明。返回
    全量 null 映射会让「没公布容差」与「公布了但容差为 0」混为一谈，
    并改变 merged.json 里 tie_policy 的结构。
    """
    return {
        b.source_id: {"abs": b.tie_tolerance, "source": b.tie_rule}
        for b in BOARDS if b.tie_tolerance is not None
    }


def dimension_leaders() -> list:
    """冠军摘要槽位 [(sid, 中文维度名, 度量依据)]。

    顺序由 LEADER_SLOTS 显式声明，不用 BOARDS 的 order 排序——两者本就是
    不同维度：order 决定 tab 与榜单排列，摘要条则是按「读者最关心的几个维度」
    编排（例如综合智能在前）。实测原 DIMENSION_LEADERS 顺序为
    aa → lmarena_text → livecodebench → superclue，与 BOARD_ORDER
    （text → aa → superclue → webdev → agent → lcb → open_llm）不同，
    派生时会悄悄改变摘要条排列，故在此显式固定。
    """
    return [(sid, BY_ID[sid].leader_slot, BY_ID[sid].leader_basis)
            for sid in LEADER_SLOTS if sid in BY_ID]


# 「各维度当前第一」摘要条的槽位顺序。每一项都只是**陈述某个榜上的第一名
# 是谁**（事实），不做任何跨榜加总或换算。某榜缺数据或已退役时该项自动
# 省略，不阻断渲染。
LEADER_SLOTS = ("aa_intelligence", "lmarena_text", "livecodebench", "superclue")


def contracts() -> dict:
    """契约阈值，供 fallback.check_contract 使用。"""
    return {
        b.source_id: {"min_rows": b.min_rows, "max_drop_ratio": b.max_drop_ratio}
        for b in BOARDS
    }


def mirror_board_ids() -> list:
    """登记了第三方镜像通道的 source_id。"""
    return [b.source_id for b in BOARDS if b.mirror_ok]


# 跨榜对比只呈现「至少出现在 N 个榜」的模型：单榜模型信息量低、会把长尾
# 原始 ID 淹没主表；它们仍完整保留在各自的分榜明细里。
CROSS_MIN_BOARDS = 2

# 方法论版本号：每当改动「变体折叠 / 厂商归一 / 跨榜收录门槛 / 排序规则 /
# 并列规则」任一项就升版，并在页面显式展示。作用对标 Artificial Analysis 的
# Intelligence Index 版本号——让读者能判断"我看到的这套结论是按哪一版规则
# 算出来的"，也让历史结论可追溯。
METHODOLOGY_VERSION = "cross-v2"
METHODOLOGY_CHANGES = (
    ("cross-v2",
     "统计并列改为「仅上游公布容差的榜启用」（白名单 + 出处），不再用全距比率自适应阈值；"
     "厂商与国别都推不出的模型改为「列出但标灰、不参与排序」；已退役归档榜不再产出「当前第一」；"
     "榜单改「任务名（原榜名）」双层命名"),
    ("cross-v1",
     "建立模型主数据层：变体折叠 + 厂商归一；跨榜表只收 ≥2 榜模型；id 一律由主数据重算"),
)


def fetch_every_days(source_id: str) -> int:
    """该榜的重抓间隔（天）。0 表示每日。"""
    b = BY_ID.get(source_id)
    return b.fetch_every_days if b else 0


def should_fetch_today(source_id: str, date_str: str, last_fetch_date: str | None) -> bool:
    """今天是否需要重抓该榜。

    判据：距上次成功抓取是否已过 fetch_every_days 天。

    为什么不用「是否已退役」：实测证明 retired 完全不能预测内容变化。
    见 BoardSpec.fetch_every_days 的注释——open_llm（retired=True）内容
    每天都在变（分页顺序抖动），superclue / livecodebench（retired=False）
    8~9 期一次没变。

    last_fetch_date 为 None（从未抓过）时必须抓，否则新源永远拿不到数据。
    """
    every = fetch_every_days(source_id)
    if every <= 0:
        return True
    if not last_fetch_date:
        return True
    try:
        last = datetime.date.fromisoformat(str(last_fetch_date)[:10])
        today = datetime.date.fromisoformat(str(date_str)[:10])
    except ValueError:
        return True     # 日期不可解析时保守抓取
    return (today - last).days >= every


def registry_summary() -> dict:
    """注册表规模自述（供方法论页与自检展示）。"""
    return {
        "boards": len(BOARDS),
        "retired": sum(1 for b in BOARDS if b.retired),
        "tie_boards": [b.source_id for b in BOARDS if b.tie_tolerance],
        "mirror_boards": mirror_board_ids(),
        "cross_min_boards": CROSS_MIN_BOARDS,
        "methodology_version": METHODOLOGY_VERSION,
        # 两种顺序一致性自检：不一致是既有设计，非缺陷，但显式暴露出来
        # 便于将来决定是否统一。
        "board_order": board_order(),
        "tab_order": list(TAB_ORDER),
    }


def validate() -> list:
    """注册表自洽性检查，返回问题列表（空 = 通过）。

    与其让这些约束散落在各处文档里，不如让它们可执行——注册表是
    纯声明结构，声明错了（比如 order 重复、并列容差没给出处）应该在
    启动时就报错，而不是等到某个榜渲染异常才被发现。
    """
    problems = []
    ids = [b.source_id for b in BOARDS]
    dup_ids = {i for i in ids if ids.count(i) > 1}
    if dup_ids:
        problems.append(f"source_id 重复: {sorted(dup_ids)}")

    orders = [b.order for b in BOARDS]
    if len(set(orders)) != len(orders):
        problems.append(f"order 重复: {sorted(orders)}")
    if sorted(orders) != list(range(1, len(BOARDS) + 1)):
        problems.append(f"order 非连续 1..{len(BOARDS)}: {sorted(orders)}")

    for b in BOARDS:
        if b.kind not in ("human_preference", "objective_benchmark"):
            problems.append(f"{b.source_id}: kind 非法 {b.kind!r}")
        if b.method_group not in ("human", "objective", "chinese"):
            problems.append(f"{b.source_id}: method_group 非法 {b.method_group!r}")
        # 并列容差必须带出处：页面要向读者展示「这个容差从哪来」，
        # 没有出处的容差等于凭空制造精度。
        if b.tie_tolerance is not None and not b.tie_rule:
            problems.append(f"{b.source_id}: 有并列容差但缺出处 tie_rule")
        if b.tie_tolerance is not None and b.tie_tolerance <= 0:
            problems.append(f"{b.source_id}: 并列容差非正 {b.tie_tolerance}")
        # 冠军摘要必须能溯源：只陈述「某榜第一是谁」也要说清依据的是哪个指标。
        if b.leader_slot and not b.leader_basis:
            problems.append(f"{b.source_id}: 有冠军槽位但缺度量依据 leader_basis")
        if b.leader_basis and not b.leader_slot:
            problems.append(f"{b.source_id}: 有度量依据但无冠军槽位（配置矛盾）")

    for sid in LEADER_SLOTS:
        if sid not in BY_ID:
            problems.append(f"LEADER_SLOTS 引用了未登记的榜: {sid}")

    unknown = set(TAB_ORDER) - set(ids)
    if unknown:
        problems.append(f"TAB_ORDER 引用了未登记的榜: {sorted(unknown)}")
    missing = set(ids) - set(TAB_ORDER)
    if missing:
        problems.append(f"TAB_ORDER 漏掉了已登记的榜: {sorted(missing)}")

    return problems


if __name__ == "__main__":
    import json
    print(json.dumps(registry_summary(), ensure_ascii=False, indent=1))
    print()
    for b in BOARDS:
        flag = " [已退役]" if b.retired else ""
        tie = f" [并列±{b.tie_tolerance}]" if b.tie_tolerance else ""
        print(f"{b.order}. {b.source_id:16s} {b.task_label}{tie}{flag}")
