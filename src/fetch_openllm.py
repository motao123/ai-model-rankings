#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Hugging Face Open LLM Leaderboard v2 抓取（开源模型客观基准）。

⚠️ 该榜单已于 2025-03 由 HF 官方退役，但结果数据仍作为归档保留：
   数据集 open-llm-leaderboard/contents（主表）与 open-llm-leaderboard/results。
本站抓取归档主表用于「开源模型客观基准」子榜，页面会显著标注
「榜单已退役，数据为归档快照，截至 2025-03」，避免误导。

抓取通道：HF datasets-server /rows 分页 API（GitHub Actions 内可正常访问）。
6 项基准：IFEval / BBH / MATH Lvl 5 / GPQA / MuSR / MMLU-PRO，Average 为总分。
只保留 chat/instruct 类型，按 Average 降序取前 N，不修改任何分数。
"""

from common import http_get, log, warn, now_utc_iso

SOURCE_PAGE = "https://huggingface.co/spaces/open-llm-leaderboard/open_llm_leaderboard"
SOURCE_ID = "open_llm"

# 主表数据集（contents = 可下载的主榜表）
DATASETS = ["open-llm-leaderboard/contents", "open-llm-leaderboard/results"]
HF_DATASETS_SERVER = "https://datasets-server.huggingface.co"

TOP_N = 60
# Average 字段与各分项字段的候选名（宽松匹配）
AVG_KEYS = ["Average ⭐", "Average", "average", "Average (%)"]
NAME_KEYS = ["fullname", "model", "Model", "name", "model_name"]
TYPE_KEYS = ["type", "Type"]
SUB_KEYS = {
    "ifeval": ["IFEval", "IFEval (0-Shot)", "ifeval"],
    "bbh": ["BBH", "BBH (3-Shot)", "bbh"],
    "math": ["MATH Lvl 5", "MATH Lvl 5 (4-Shot)", "MATH", "math"],
    "gpqa": ["GPQA", "GPQA (0-shot)", "gpqa"],
    "musr": ["MuSR", "MuSR (0-shot)", "MUSR", "musr"],
    "mmlu_pro": ["MMLU-PRO", "MMLU-PRO (5-shot)", "mmlu_pro"],
}


def _pick(row, keys):
    for k in keys:
        if k in row and row[k] not in (None, ""):
            return row[k]
    return None


def _to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _fetch_rows(dataset):
    rows, offset, page = [], 0, 100
    while True:
        url = (
            f"{HF_DATASETS_SERVER}/rows?dataset={dataset.replace('/', '%2F')}"
            f"&config=default&split=train&offset={offset}&length={page}"
        )
        data = http_get(url, as_json=True)
        batch = data.get("rows") or []
        for item in batch:
            rows.append(item.get("row", item))
        total = data.get("num_rows_total", 0)
        offset += len(batch)
        if not batch or offset >= total or offset > 6000:
            break
    return rows


def fetch(date_str: str):
    raw_rows = []
    used_dataset = None
    for ds in DATASETS:
        try:
            raw_rows = _fetch_rows(ds)
            if raw_rows:
                used_dataset = ds
                break
        except Exception as exc:  # noqa: BLE001
            warn(f"OpenLLM {ds} 拉取失败: {exc}")

    if not raw_rows:
        raise RuntimeError("Open LLM Leaderboard: 归档数据集不可用")

    cleaned = []
    for row in raw_rows:
        name = _pick(row, NAME_KEYS)
        avg = _to_float(_pick(row, AVG_KEYS))
        if not name or avg is None:
            continue
        rtype = (_pick(row, TYPE_KEYS) or "").lower()
        # 只保留对话/指令微调模型（排除 base pretrained），聚焦可用模型
        if rtype and "chat" not in rtype and "instruct" not in rtype:
            continue
        subs = {}
        for key, keys in SUB_KEYS.items():
            subs[key] = _to_float(_pick(row, keys))
        cleaned.append({
            "model": str(name),
            "organization": str(name).split("/")[0] if "/" in str(name) else None,
            "score": round(avg, 2),
            "type": rtype or None,
            "subscores": subs,
        })

    if not cleaned:
        raise RuntimeError("Open LLM Leaderboard: 清洗后无 chat 模型")

    cleaned.sort(key=lambda r: -r["score"])
    cleaned = cleaned[:TOP_N]
    for i, row in enumerate(cleaned, start=1):
        row["rank"] = i

    log(f"OpenLLM: 归档数据集 {used_dataset}，取 {len(cleaned)} 个 chat 模型")
    return {
        "source_id": SOURCE_ID,
        "board": "HF Open LLM Leaderboard v2（开源·已退役归档）",
        "metric": "Average (%)",
        "kind": "objective_benchmark",
        "source_url": SOURCE_PAGE,
        "dataset_url": f"https://huggingface.co/datasets/{used_dataset}",
        "license": "归档数据（榜单已于 2025-03 退役）",
        "retired": True,
        "retired_note": "该榜单已于 2025 年 3 月退役，此处为归档快照，仅供开源模型横向参考。",
        "fetched_at": now_utc_iso(),
        "publish_date": "2025-03",
        "channel": "hf-datasets-server",
        "rows": cleaned,
    }


if __name__ == "__main__":
    import json
    from common import today_str
    print(json.dumps(fetch(today_str())["rows"][:5], ensure_ascii=False, indent=1))
