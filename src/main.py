#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""入口薄封装：把调用转给 orchestrator.run()。

为什么保留这个文件
------------------
`python src/main.py` 是项目的既定入口，GitHub Actions 的 cron.yml、
README、以及若干运维脚本都按这个名字调用。直接改名会让这些位置
同时失效，而重命名能得到的收益仅是「文件名更好看」。

若调用方只想要一次管道执行，用 orchestrator.run()；
本文件仅为兼容保留，内部不含任何逻辑。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from orchestrator import run, build_merged, BOARD_ORDER  # noqa: E402,F401


def main():
    """执行一次完整管道。"""
    return run()


if __name__ == "__main__":
    main()
