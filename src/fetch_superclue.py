#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SuperCLUE 中文榜抓取（对官方静态 XLSX 直链取数）。

背景与演进
----------
旧实现（已废弃）假设榜单走混淆后的 /api/chores/ JSON 接口，逐个试候选端点。
实测这些端点全部 404，因此该源长期只能降级到 data/manual/superclue.json。

现方案（2026-10 实测确认）
-------------------------
扒 superclueai.com 前端 bundle 后确认：
1. axios baseURL 为 `/api/chores/`，但该目录下只有 `detect_region`，榜单不走它；
2. 榜单数据是**官方静态资源**：
   - 通用榜：`https://www.superclueai.com/data/generalboard/<期次>.xlsx`
     期次形如 `2026年7月`、`2025年度测评`（前端 availableDates 中的文案即文件名）。
     表内 sheet「总排行榜」列为：排名 / 模型名称 / 机构 / 开闭源 / 总分 / … 。
3. 期次列表前端是硬编码的，会随改版变动，所以这里**不硬编码期次**，而是按
   「近若干年 × 逐月 + 年度测评」生成候选，从新到旧逐个探测存在性，
   命中即用（自带新期次上线后的自适应）。

降级：本通道全部失败 -> 抛错，由 main.py 降级到人工数据（页面有明确标注）。

本脚本不修改任何分数，只搬运官方 XLSX 中的展示值。
"""

import datetime
import io
import re
import urllib.parse

from common import (
    http_get, http_get_bytes, probe_url, log, warn, now_utc_iso,
)

SOURCE_PAGE = "https://www.superclueai.com/generalpage"
SOURCE_ID = "superclue"
DATA_BASE = "https://www.superclueai.com/data/generalboard/"
XLSX_HEADERS = {
    "Accept": "*/*",
    "Referer": SOURCE_PAGE,
}

# 期次探测范围：从当前年份往前覆盖的年数（逐月 + 年度测评）
DISCOVER_YEARS = 4
# 通用榜 sheet 优先级（缺失时退回第一个含"模型名称"列的表）
SHEET_PREFERENCE = ("总排行榜", "通用排行榜")
MODEL_HINTS = ("模型名称", "模型", "model")
ORG_HINTS = ("机构", "厂商", "组织", "company", "organization")
SCORE_HINTS = ("总分", "综合得分", "average", "score")


# ---------------------------------------------------------------- 期次探测

def _candidate_labels():
    """生成候选期次（新 -> 旧）。形如 2026年7月 / 2025年度测评。

    月度榜期次不规律（历史上多为每两月一期），但逐个探测成本很低
    （单次 GET、无重试），因此直接按月穷举，命中即止，换取"零维护自适应"。
    """
    today = datetime.date.today()
    labels = []
    for year in range(today.year, today.year - DISCOVER_YEARS, -1):
        # 本年度只探到当前月，避免未来月份的无效请求
        last_month = today.month if year == today.year else 12
        for month in range(last_month, 0, -1):
            labels.append(f"{year}年{month}月")
        labels.append(f"{year}年度测评")
    return labels


def _discover_workbook():
    """逐个探测候选期次，返回 (期次文案, URL)；全无命中返回 (None, None)。"""
    for label in _candidate_labels():
        url = DATA_BASE + urllib.parse.quote(label) + ".xlsx"
        if probe_url(url, headers=XLSX_HEADERS):
            return label, url
    return None, None


# ---------------------------------------------------------------- XLSX 解析

def _pick_sheet(workbook):
    for name in SHEET_PREFERENCE:
        if name in workbook.sheetnames:
            return workbook[name]
    return workbook[workbook.sheetnames[0]]


def _header_index(header_row):
    """在表头行里定位 模型/机构/总分 三列的下标，做宽松匹配。"""
    idx = {"model": None, "org": None, "score": None}
    for i, cell in enumerate(header_row):
        text = str(cell or "").strip().lower()
        if not text:
            continue
        if idx["model"] is None and any(h.lower() in text for h in MODEL_HINTS):
            idx["model"] = i
        if idx["org"] is None and any(h.lower() in text for h in ORG_HINTS):
            idx["org"] = i
        if idx["score"] is None and any(h.lower() in text for h in SCORE_HINTS):
            idx["score"] = i
    return idx


def _to_float(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "")
    m = re.search(r"-?\d+(?:\.\d+)?", text)
    return float(m.group()) if m else None


def parse_workbook(content: bytes):
    """解析官方 XLSX，返回 [{model, organization, score}, ...]；无法解析返回 None。"""
    try:
        import openpyxl
    except ImportError:  # pragma: no cover - 依赖缺失时交由上层降级
        warn("openpyxl 不可用，SuperCLUE 无法解析 XLSX")
        return None
    try:
        workbook = openpyxl.load_workbook(io.BytesIO(content), data_only=True,
                                          read_only=True)
    except Exception as exc:  # noqa: BLE001
        warn(f"SuperCLUE XLSX 打开失败: {exc}")
        return None

    sheet = _pick_sheet(workbook)
    rows_iter = sheet.iter_rows(values_only=True)

    header, idx = None, None
    for row in rows_iter:
        probe = _header_index(row)
        if probe["model"] is not None and probe["score"] is not None:
            header, idx = row, probe
            break
    if idx is None:
        warn("SuperCLUE XLSX 未找到「模型名称/总分」表头行")
        return None

    out = []
    for row in rows_iter:
        if not row or idx["model"] >= len(row):
            continue
        model = row[idx["model"]]
        if model is None or not str(model).strip():
            continue
        score = _to_float(row[idx["score"]]) if idx["score"] is not None and idx["score"] < len(row) else None
        if score is None:
            continue
        org = None
        if idx["org"] is not None and idx["org"] < len(row):
            org = str(row[idx["org"]]).strip() or None
        out.append({"model": str(model).strip(), "organization": org, "score": score})
    return out or None


def _period_to_iso(label: str) -> str:
    """期次文案 -> ISO 日期（用于 publish_date，便于滞后计算）。"""
    m = re.match(r"(\d{4})年(\d{1,2})月", label or "")
    if m:
        return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-01"
    m = re.match(r"(\d{4})年", label or "")
    if m:
        return f"{int(m.group(1)):04d}-12-31"
    return datetime.date.today().isoformat()


# ---------------------------------------------------------------- HTML 兜底

def _try_html():
    """兜底：解析服务端渲染的 HTML 表格（SPA 首屏一般无表格，成功率低但无害）。"""
    try:
        html = http_get(SOURCE_PAGE, timeout=30)
    except Exception as exc:  # noqa: BLE001
        warn(f"SuperCLUE HTML 抓取失败: {exc}")
        return None
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    for tr in soup.select("table tbody tr"):
        cells = [td.get_text(strip=True) for td in tr.find_all("td")]
        if len(cells) >= 3:
            score = None
            for c in reversed(cells):
                score = _to_float(c)
                if score is not None:
                    break
            if score is not None:
                rows.append({"model": cells[1] if cells[0].isdigit() else cells[0],
                             "organization": cells[2] if len(cells) > 2 else None,
                             "score": score})
    return rows or None


# ---------------------------------------------------------------- 入口

def fetch(date_str: str):
    period, url = _discover_workbook()
    rows = None
    if url:
        log(f"SuperCLUE: 命中官方期次「{period}」-> {url}")
        try:
            content = http_get_bytes(url, timeout=60, retries=2, headers=XLSX_HEADERS)
            rows = parse_workbook(content)
        except Exception as exc:  # noqa: BLE001
            warn(f"SuperCLUE XLSX 下载/解析失败: {exc}")

    if not rows:
        rows = _try_html()
        period = period or date_str
    if not rows:
        raise RuntimeError("SuperCLUE: XLSX 直链与 HTML 通道均失败，需降级到人工数据")

    rows = [r for r in rows if r.get("score") is not None]
    rows.sort(key=lambda r: -r["score"])
    for i, row in enumerate(rows, start=1):
        row["rank"] = i

    log(f"SuperCLUE: 自动抓取 {len(rows)} 个模型（期次 {period}）")
    return {
        "source_id": SOURCE_ID,
        "board": "SuperCLUE 中文大模型综合榜",
        "metric": "综合得分",
        "kind": "objective_benchmark",
        "source_url": SOURCE_PAGE,
        "dataset_url": DATA_BASE,
        "license": "© SuperCLUE，本站仅聚合展示",
        "fetched_at": now_utc_iso(),
        "publish_date": _period_to_iso(period),
        "data_period": period,
        "channel": "auto",
        "rows": rows,
    }


if __name__ == "__main__":
    import json
    from common import today_str
    data = fetch(today_str())
    print(json.dumps({"period": data["data_period"], "rows": data["rows"]},
                     ensure_ascii=False, indent=1))
