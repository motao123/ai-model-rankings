#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把降级报告同步为 GitHub Issue（自愈闭环的一部分）。

行为：
- 有降级：找到带 data-degraded 标签的 open issue 就追加评论；没有就新建。
- 无降级：若存在该标签的 open issue，则自动评论并关闭（"已恢复"）。
- gh 不可用（本地/无 token）时静默跳过，绝不让工作流失败。

用法：python src/report_issue.py
依赖：gh CLI + GH_TOKEN 环境变量（GitHub Actions 默认提供）
"""

import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
FAILREPORT = os.path.join(HERE, "..", "data", "state", "failures.json")
LABEL = "data-degraded"
LAYER_TXT = {
    "mirror": "第三方镜像快照（Internet Archive）",
    "lkg": "已知良好回退（LKG）",
    "snapshot": "历史快照",
    "manual": "人工维护数据",
}


def gh(*args, check=False):
    try:
        out = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=60)
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        print(f"[WARN] gh 调用不可用: {exc}", file=sys.stderr)
        return None
    if out.returncode != 0 and check:
        print(f"[WARN] gh {' '.join(args)} -> {out.stderr.strip()}", file=sys.stderr)
    return out.stdout.strip() if out.returncode == 0 else None


def find_open_issue():
    out = gh("issue", "list", "--label", LABEL, "--state", "open",
             "--json", "number,title", "--limit", "1")
    if not out:
        return None
    try:
        items = json.loads(out)
    except json.JSONDecodeError:
        return None
    return items[0] if items else None


def read_report():
    try:
        with open(FAILREPORT, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None


def build_body(rep):
    items = [i for i in rep.get("items", [])
             if i.get("status") in ("fallback", "degraded", "failed")]
    lines = [
        f"**日期**：{rep.get('date')}",
        f"**降级数**：{rep.get('degraded')} / {rep.get('total')}",
        "",
        "| 数据源 | 状态 | 兜底层级 | 原因 |",
        "| --- | --- | --- | --- |",
    ]
    for i in items:
        layer = LAYER_TXT.get(i.get("layer"), i.get("layer") or "—")
        err = (i.get("error") or "").replace("|", "/").replace("\n", " ")[:160]
        lines.append(f"| `{i.get('source')}` | {i.get('status')} | {layer} | {err} |")
    lines += [
        "",
        "> 站点已按「镜像快照 → 已知良好回退 → 历史快照 → 人工数据」自动兜底，"
        "页面不白屏、展示旧数据处均有标注。若连续多日出现同一源降级，"
        "通常意味着上游改版，需要更新对应的解析器。",
    ]
    return "\n".join(lines)


def main():
    rep = read_report()
    existing = find_open_issue()

    if not rep:
        print("[INFO] 无降级报告，跳过。")
        return

    degraded = rep.get("degraded", 0)
    if degraded == 0:
        if existing:
            gh("issue", "comment", str(existing["number"]),
               "--body", f"✅ {rep.get('date')} 定时抓取已全部恢复，无降级。自动关闭。")
            gh("issue", "close", str(existing["number"]))
            print(f"[INFO] 已恢复，关闭 issue #{existing['number']}")
        else:
            print("[INFO] 无降级且无遗留 issue。")
        return

    title = f"数据源降级：{degraded} 项（{rep.get('date')}）"
    body = build_body(rep)
    if existing:
        gh("issue", "comment", str(existing["number"]), "--body", body)
        print(f"[INFO] 已在 issue #{existing['number']} 追加降级报告")
    else:
        gh("label", "create", LABEL, "--color", "FBCA04",
           "--description", "定时抓取有数据源降级", "--force")
        out = gh("issue", "create", "--label", LABEL, "--title", title, "--body", body)
        print(f"[INFO] 已创建降级 issue：{out or '(gh 不可用)'}")


if __name__ == "__main__":
    main()
