#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GitHub Issue 运维的公共封装（gh CLI 调用 + 带标签的 open issue 查找）。

抽取动机
--------
原先 report_issue.py 与 check_manual.py 各自持有一份**逐字相同**的
`gh()` 与 `find_open_issue()` 实现（实测确认源码等价）。两份实现在同一
仓库里漂移的风险不是理论问题——改了一边忘了另一边，就是「降级 Issue
正常、人工数据过期 Issue 静默失败」这种极难排查的半失效状态。

本模块只做两件事，不含任何业务判断：
    gh(...)              执行 gh CLI，失败静默返回 None
    find_labeled_issue()  查找指定标签的 open issue

「静默失败」是这个设计的关键：两个调用方都跑在 GitHub Actions 的
`if: always()` 步骤里，gh 不可用（本地无 token、无网络）时必须安静跳过，
绝不能让降级提醒机制本身把流水线搞失败。

用法：
    from gh_util import gh, find_labeled_issue
    issue = find_labeled_issue("data-degraded")
"""

import json
import subprocess
import sys


def gh(*args, check=False):
    """执行 gh CLI。成功返回 stdout（strip），失败返回 None。

    gh 缺失（FileNotFoundError）或超时（TimeoutExpired）一律吞掉并返回
    None——调用方据此静默跳过，不阻断流水线。
    """
    try:
        out = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=60)
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        print(f"[WARN] gh 调用不可用: {exc}", file=sys.stderr)
        return None
    if out.returncode != 0 and check:
        print(f"[WARN] gh {' '.join(args)} -> {out.stderr.strip()}", file=sys.stderr)
    return out.stdout.strip() if out.returncode == 0 else None


def find_labeled_issue(label):
    """查找带指定标签的 open issue（取最新一个）。

    返回 {number, title} 或 None。gh 不可用、输出非 JSON、空列表时均
    返回 None——「找不到」和「查不了」在自愈闭环里的处理方式相同：
    都当作「需要新建 Issue」。
    """
    out = gh("issue", "list", "--label", label, "--state", "open",
             "--json", "number,title", "--limit", "1")
    if not out:
        return None
    try:
        items = json.loads(out)
    except json.JSONDecodeError:
        return None
    return items[0] if items else None


def ensure_label(label, color, description):
    """幂等创建标签（--force 使其可重复调用）。失败静默。"""
    return gh("label", "create", label, "--color", color,
              "--description", description, "--force")


def comment_and_close(issue, body):
    """在 issue 上追加评论并关闭，返回是否都成功。"""
    ok1 = gh("issue", "comment", str(issue["number"]), "--body", body)
    ok2 = gh("issue", "close", str(issue["number"]))
    return bool(ok1) and ok2 is not None
