#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""数据源适配器：定义「一个榜单从哪来、怎么解析」的契约。

解决的问题
----------
此前 5 个 fetch_* 模块各自 import 到 main.py，main.py 再用
`_build_task_map()` 手工把它们组装成 {task_key: callable}：

    tasks["_lmarena_group"] = lambda: ...   # 多源特例
    tasks[aa.SOURCE_ID]      = lambda: {...}
    ...

新增一个榜要同时改三处：新写 fetch_xxx.py、在 boards.py 加 BoardSpec、
在 main.py 的 _build_task_map 加一行。更糟的是 lmarena 是「一次抓取产出
多个 source_id」，只能用 `_lmarena_group` 这种特例 key 绕开，与其余
四个单 id 源的形态不一致，编排层因此出现 `if task_key == "_lmarena_group"`
的分支判断。

本模块把这件事统一为：**适配器声明自己能产出哪些 source_id**。
编排层只遍历适配器列表，不再关心单源还是多源。

新增一个榜 = 新增一个 sources/xxx.py 适配器 + boards.py 一条 BoardSpec，
main.py 不需要改动。
"""

import sys
from typing import Protocol

HERE = __file__.rsplit("\\", 1)[0].rsplit("/", 1)[0]
if HERE not in sys.path:
    sys.path.insert(0, HERE)


class SourceAdapter(Protocol):
    """一个数据源适配器。

    实现者只需提供 `fetch()`；其余方法有合理默认。
    """

    #: 产出的 source_id 列表。一个适配器可产出多个（见 lmarena）
    source_ids: list

    def fetch(self, date_str: str) -> dict:
        """抓取并返回 {source_id: payload}。

        约定：
        - 失败必须抛异常，由编排层决定降级；**不得**返回 None 或空 rows
        - payload 结构由 schema.validate_meta 校验
        """

    @property
    def mirror_ok(self) -> bool:
        """是否支持第三方镜像通道（默认 False）。"""

    @property
    def source_url(self) -> str | None:
        """镜像查询用的规范化 URL（mirror_ok 为 True 时必填）。"""


# 适配器表：key 仅为调试可读性，编排层遍历 values()
ADAPTERS = []


def register(adapter):
    """注册一个适配器实例。返回该实例，便于模块尾部直接赋值。"""
    ADAPTERS.append(adapter)
    return adapter


def load_all():
    """导入并注册全部内置适配器。返回适配器列表。"""
    if ADAPTERS:
        return ADAPTERS
    from sources import aa, lmarena, livecodebench, openllm, superclue  # noqa: F401
    return ADAPTERS


def all_source_ids():
    """全部适配器产出的 source_id（按注册顺序，自动去重）。"""
    out = []
    for ad in load_all():
        for sid in ad.source_ids:
            if sid not in out:
                out.append(sid)
    return out
