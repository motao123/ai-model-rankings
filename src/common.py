#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""公共工具：带 UA / 超时 / 重试的 HTTP 请求，JSON 读写，快照文件管理。

约定：
- data/raw/<source>_<YYYY-MM-DD>.json  每日原始快照（真相源，git 保留历史）
- data/manual/<source>.json            人工整理的兜底数据（无法稳定抓取的源）
- data/merged.json                     清洗合并后前端直接消费
"""

import datetime
import glob
import json
import os
import sys
import time

import requests

# 明确标识来源的 UA，附仓库地址，符合合规抓取要求
USER_AGENT = (
    "Mozilla/5.0 (compatible; ai-model-rankings/1.0; "
    "+https://github.com/motao123/ai-model-rankings)"
)
TIMEOUT = 45
RETRIES = 3
BACKOFF = 5  # 秒，线性退避

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
RAW_DIR = os.path.join(DATA_DIR, "raw")
MANUAL_DIR = os.path.join(DATA_DIR, "manual")


def log(msg: str) -> None:
    print(f"[INFO] {msg}", flush=True)


def warn(msg: str) -> None:
    print(f"[WARN] {msg}", file=sys.stderr, flush=True)


def now_utc_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def today_str() -> str:
    return datetime.date.today().isoformat()


def http_get(url, *, timeout=TIMEOUT, retries=RETRIES, as_json=False,
             headers=None, max_bytes=None):
    """GET 请求，带 UA、超时、重试与线性退避。失败抛 RuntimeError（由调用方决定降级）。"""
    hdrs = {
        "User-Agent": USER_AGENT,
        "Accept": "*/*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    if headers:
        hdrs.update(headers)
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(url, headers=hdrs, timeout=timeout)
            resp.raise_for_status()
            if as_json:
                return resp.json()
            if max_bytes:
                return resp.content[:max_bytes].decode("utf-8", errors="replace")
            return resp.text
        except Exception as exc:  # noqa: BLE001 - 任何网络/解析错误都进入重试
            last_err = exc
            warn(f"GET {url} 第 {attempt}/{retries} 次失败: {exc}")
            if attempt < retries:
                time.sleep(BACKOFF * attempt)
    raise RuntimeError(f"GET 连续 {retries} 次失败: {url} -> {last_err}")


def http_get_bytes(url, *, timeout=TIMEOUT, retries=RETRIES, headers=None,
                   max_bytes=None):
    """GET 二进制内容（如 xlsx 等文档型数据源），带 UA/超时/重试与线性退避。
    失败抛 RuntimeError（由调用方决定降级）。"""
    hdrs = {
        "User-Agent": USER_AGENT,
        "Accept": "*/*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    if headers:
        hdrs.update(headers)
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(url, headers=hdrs, timeout=timeout)
            resp.raise_for_status()
            data = resp.content
            return data[:max_bytes] if max_bytes else data
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            warn(f"GET(bytes) {url} 第 {attempt}/{retries} 次失败: {exc}")
            if attempt < retries:
                time.sleep(BACKOFF * attempt)
    raise RuntimeError(f"GET(bytes) 连续 {retries} 次失败: {url} -> {last_err}")


def probe_url(url, *, timeout=15, headers=None) -> bool:
    """轻量存在性探测：单次 GET，只看是否 200。不重试、不抛异常、不读全量 body。

    专用于"候选路径逐个试"的场景（例如按月份探测榜单文件），
    避免 http_get 的重试+退避在大量 404 上放大请求数与耗时。
    """
    hdrs = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    if headers:
        hdrs.update(headers)
    try:
        resp = requests.get(url, headers=hdrs, timeout=timeout, stream=True)
        ok = resp.status_code == 200
        resp.close()
        return ok
    except Exception:  # noqa: BLE001
        return False


def read_json(path, default=None):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return default


def write_json(path, obj) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1)
        fh.write("\n")


# ---------------------------------------------------------------- 快照管理

def snapshot_path(source: str, date_str: str) -> str:
    return os.path.join(RAW_DIR, f"{source}_{date_str}.json")


def write_snapshot(source: str, payload: dict, date_str: str = None) -> str:
    date_str = date_str or today_str()
    path = snapshot_path(source, date_str)
    write_json(path, payload)
    return path


def list_snapshots(source: str):
    """返回 [(date_str, path), ...]，按日期升序。"""
    out = []
    for path in glob.glob(os.path.join(RAW_DIR, f"{source}_*.json")):
        base = os.path.basename(path)
        date_part = base[len(source) + 1: -len(".json")]
        out.append((date_part, path))
    out.sort(key=lambda x: x[0])
    return out


def latest_snapshot_before(source: str, date_str: str):
    """取 date_str 之前最近一次快照的 (date_str, payload)，无则 (None, None)。"""
    prev = None
    for d, path in list_snapshots(source):
        if d < date_str:
            prev = (d, path)
    if prev is None:
        return None, None
    return prev[0], read_json(prev[1])


def load_manual(source: str):
    """读取人工兜底数据 data/manual/<source>.json，无则 None。"""
    return read_json(os.path.join(MANUAL_DIR, f"{source}.json"))
