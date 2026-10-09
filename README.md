# AI 大模型第三方权威排行榜

> 在线地址：https://motao123.github.io/ai-model-rankings/

聚合第三方权威 AI 模型榜单的纯静态站点。**零成本、无后端**：GitHub Actions 每天 UTC 0 点抓取各榜单数据 → 写回仓库 `data/` → GitHub Pages 纯静态渲染。

## 收录榜单

| 榜单 | 类型 | 数据通道 |
|---|---|---|
| LMArena / Arena.ai 文本总榜 | 真人盲测（Bradley-Terry） | HF 官方数据集 `lmarena-ai/leaderboard-dataset`（datasets-server API，parquet 兜底） |
| LMArena Code Arena / WebDev | 真人盲测 | 同上 |
| LMArena Agent Arena | 真人盲测 | 同上 |
| Artificial Analysis 智能指数 + 价格 | 客观基准（独立机构） | 解析官网页面内嵌 JSON |
| SuperCLUE 中文榜 | 客观基准（中文） | 尝试官方接口/HTML，失败降级人工快照 |
| LiveCodeBench 编程榜 | 客观基准（防污染） | 官方静态 JSON，逐题聚合 Avg. pass@1 |
| HF Open LLM Leaderboard v2 | 客观基准（开源·已退役归档） | HF 归档数据集 datasets-server API |

**方法论交叉**：同一模型在「真人偏好」与「客观基准」两类榜单同屏并列，看谁全能、谁偏科。

## 合规原则

- 所有分数与排名**原样搬运**，不修改、不加权、**不计算跨榜综合总分**；
- 每榜标注原始链接、更新时间、数据版权；页面显著位置有免责说明；
- 明确提示各榜口径不同、不可直接横向比较；
- 抓取每天仅 1 次，带明确 User-Agent（含仓库地址），优先官方 API/数据集。

## 目录结构

```
├── .github/workflows/cron.yml   # 每天 UTC 0 点抓取 + workflow_dispatch 手动触发
├── src/
│   ├── main.py                  # 入口：串行抓取 → 清洗 → 合并 → 趋势聚合
│   ├── common.py                # HTTP(UA/超时/重试)、快照管理、降级读取
│   ├── models.py                # 模型注册表：厂商/国别/开源标签、跨榜别名归一化
│   ├── fetch_lmarena.py         # LMArena（HF 数据集双通道）
│   ├── fetch_aa.py              # Artificial Analysis（页面内嵌 JSON 解析）
│   ├── fetch_superclue.py       # SuperCLUE（API 探测 + HTML 兜底 + 人工降级）
│   ├── fetch_livecodebench.py   # LiveCodeBench（官方 JSON）
│   ├── fetch_openllm.py         # HF Open LLM v2（归档数据集）
│   ├── fallback.py              # 多层兜底引擎：数据契约熔断 / LKG / 第三方镜像 / 失败报告
│   ├── report_issue.py          # 把降级报告同步为 GitHub Issue（自愈闭环）
│   └── build_trend.py           # 从历史快照聚合趋势数据 → data/trend.json
├── data/
│   ├── raw/<source>_<日期>.json # 每日原始快照（历史趋势的真相源，git 保留）
│   ├── manual/<source>.json     # 人工兜底数据（自动抓取失败时降级展示，页面明确标注）
│   ├── state/lkg.json           # 最后已知良好（仅记录通过契约的批次）
│   ├── state/failures.json      # 本轮降级/失败报告（供工作流开 Issue、前端横幅）
│   ├── merged.json              # 前端直接消费（含 trend 升降、新上榜、共识置信度）
│   ├── trend.json               # 历史排名趋势（折线图数据）
│   └── meta.json                # 更新时间、失败/降级记录
├── index.html                   # 单文件前端（内联 CSS/JS，零外部依赖，SVG 手绘图表）
├── sw.js                        # Service Worker：离线可访问 + 数据 stale-while-revalidate
├── assets/                      # 品牌 / 分享素材
│   ├── og-card.html             # OG 卡片源文件（1200×630，浅色，与站点同款设计变量）
│   ├── og-card-dark.html        # 同上，暗色变体（墨黑 + 暖金）
│   ├── og-cover.png             # 浅色成品 —— index.html 的 og:image / twitter:image 指向它
│   └── og-cover-dark.png        # 暗色成品 —— 建议用于 GitHub 仓库 Settings 的 Social preview
├── sitemap.xml / robots.txt / 404.html / .nojekyll
└── requirements.txt
```

## 容错与降级设计（多层独立冗余）

单源失败**不影响整体**。每轮抓取先过**数据契约熔断**，不合格视为失败、不落盘、不晋级；
随后按可信度依次尝试四层兜底，**每一层都独立于"活源成功"这一前提**：

| 层 | 机制 | 信任域 | 页面标注 |
|---|---|---|---|
| A 熔断 | 行数下限 / 较上期跌幅 / 分数完整度校验 | 本站 | — |
| B 镜像 | 活源失败时改取 **Internet Archive** 最近快照重解析 | 完全外部第三方 | 「兜底数据 · 第三方镜像快照」 |
| C LKG | 回填**上一次通过契约**的批次（比"最近快照"更可信） | 本站（已校验） | 「兜底数据 · 已知良好回退」 |
| D 传统 | 最近历史快照 → `data/manual/` 人工数据 | 本站 | 「兜底数据 · 历史快照 / 人工数据」 |

交付侧再加一层客户端容灾：`data/*.json` 支持**同源 → jsDelivr CDN → GitHub raw 多端点 failover**，
叠加 **Service Worker 离线缓存**与 **localStorage 末次成功快照**——上游与仓库同时不可用时页面依旧不白屏。
页面顶部有「数据新鲜度横幅」，任一榜降级都会写明**实际来源与滞后天数**，绝不静默展示旧数据。

连续降级会由 `report_issue.py` 自动开/更新 GitHub Issue（带 `data-degraded` 标签），恢复后自动关闭。

字段缺失一律降级为 `None` 展示「—」，不报错中断；HTTP 层带 UA、45s 超时、3 次重试、线性退避；全部失败时**保留旧 `merged.json` 不覆盖**。

## 本地运行

```bash
python -m venv .venv && .venv\Scripts\pip install -r requirements.txt   # Windows
.venv/Scripts/python src/main.py        # 抓取 + 合并 + 趋势
.venv/Scripts/python -m http.server 8848  # 本地预览 http://127.0.0.1:8848
```

首次初始化：仓库已附带第一次生成的 `data/`（真实抓取的 AA / LiveCodeBench + 人工快照兜底），克隆后直接起本地服务器即可看到完整页面；推送到 GitHub 后 Actions 会接管每日更新。

## 部署步骤（GitHub Pages）

1. 本仓库推送到 GitHub（已完成：`motao123/ai-model-rankings`）；
2. Settings → Pages → Source 选 **Deploy from a branch**，分支 `main`、目录 `/ (root)`；
3. `.nojekyll` 已放置，JSON 文件不会被 Jekyll 忽略；
4. Actions 页确认 `Update Rankings` 工作流已启用（新仓库可能需手动点一次 Enable）；
5. 每天 UTC 0 点自动抓取，也可在 Actions → Update Rankings → Run workflow 手动触发；
6. commit message 带 `[skip ci]`，数据提交不会再次触发工作流。

## 已知限制

- SuperCLUE 前端为混淆 SPA，自动通道目前打不通，默认展示人工快照（依据官方月度报告），页面有明确标注；
- HF Open LLM Leaderboard 已于 2025-03 退役，本站抓的是**归档数据集**，页面标注「已退役归档」；
- Artificial Analysis 无官方公开数据文件，解析其页面内嵌 JSON，前端改版可能导致失败（自动降级，见上）。

## License

代码 MIT。榜单数据版权归原作者（LMArena/Arena.ai CC-BY-4.0、Artificial Analysis、SuperCLUE、LiveCodeBench、Hugging Face）所有，本站仅聚合展示。
