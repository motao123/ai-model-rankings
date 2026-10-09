# 同类站点调研：AI 模型排行榜 / 聚合对比站

> 调研时间：2026-10-09 · 方法：联网检索 + 重点站点抓取正文
> 目的：为本项目（ai-model-rankings，多榜聚合 + 跨榜对比）寻找可借鉴对象
> 说明：以下站点现状均来自本次检索的实时内容，站点迭代快，字段与设计可能随时变化

---

## 0. 先给结论：本项目应该对标谁

本项目是**「多源聚合 + 跨榜对齐」**型站点，不是单一评测机构。所以：

| 层次 | 对标对象 | 理由 |
|---|---|---|
| **最该学（同构）** | Epoch AI、LLM Stats、Vellum、Artificial Analysis | 它们都在做「多榜合并成一个可读视图」，遇到的问题和我们完全一样 |
| **最该抄（方法论）** | AI Stupid Level、OpenRouter Rankings | 二者的「方法论声明」与「数据契约可视化」是同类站里的天花板 |
| **最该抄（代码）** | llm-benchmarks（GitHub 开源） | Astro + ECharts + 双主题 + 静态部署，技术栈与我们最接近且可直接读源码 |
| **中文侧补位** | SuperCLUE、DataLearner、OpenCompass | 国产模型覆盖与中文测评口径，是我们 region=cn 维度的权威参照 |
| **数据来源方** | LMArena、HF Open LLM、LiveBench、SWE-bench | 我们已经在用它们的数据，需理解它们的口径边界 |

一句话：**我们的差异化不在「再做一个榜」，而在「跨榜对齐的透明度」**——这正是下面几个站做得最狠的地方。

---

## A. 多榜聚合型（与本项目同构，重点研究）

### A1. Artificial Analysis — artificialanalysis.ai

**定位**：2026 年被多家评测文章称为「最广泛引用的独立评测聚合站」，面向要同时权衡能力/成本/速度的采购者与工程团队。

**核心功能**
- **Intelligence Index**：把约 10 项独立评测（AA-Briefcase、GDPval-AA、AutomationBench-AA、Terminal-Bench 4.0、SciCode、HLE、GDP.pdf、CritPt、AA-Omniscience、AA-LCR）加权成单一指数，版本号公开（v4.3.2）。
- **Openness Index**：把「开放程度」拆成 4 个可计分组件（预训练数据透明度、后训练数据透明度、方法论透明度、模型可获得性），满分 18。
- **Capability Indexes**：按行业细分（金融会计、战略运营、法律、医疗、工程、经济）。
- **多个 Arena**：图像/视频/语音 Arena，Elo 分并标注 **95% 置信区间**。
- **Model Recommender / Optima**：按用户优先级（智能/速度/成本）推荐模型，Optima 允许自建自定义 benchmark。
- 新闻/更新日志流：以「New language model evaluation」形式把新模型评测当信息流发。

**界面与交互特点**
- **散点图是主角**：Intelligence vs Cost per Task / vs Time per Task / vs Output Tokens per Task 三种切换，带 **Pareto 前沿线**与「Most attractive quadrant」标注。
- 筛选器直接做在概念层：`Open Weights / Proprietary`、`Reasoning / Non-Reasoning`、`Text Only / Multimodal`、**`By Country`**。
- 每个榜单都标「X of Y models」（如 `26 of 696 models`），不假装全量。
- 成本口径写得极细：每个评测的成本由 input / cache hit / cache write / reasoning / answer token 价格分别计算，再按 Index 权重加权。

**可借鉴点（对本项目最直接）**
1. **「By Country」筛选** —— 我们的 `region` 维度已建好（cn / us / other），但页面上还没有国家级筛选器，这是最省力的对齐点。
2. **Pareto 前沿** —— 我们的趋势图现在只是折线，改成「能力 vs 成本」散点 + Pareto 线，叙事立刻从「谁第一」升级为「谁划算」。
3. **指数版本号公开** —— 我们的 `cross_meta` 已有 `sort_rule` 字段，可以再加一个方法论版本号（如 `cross-v2`），每次改算法就升版，页面显示出来。这是「可信度基建」。
4. **成本口径写清楚** —— 我们现在不做跨榜总分（这是对的），但成本/速度这类**可加总维度**可以单独成表，并注明口径。

---

### A2. LLM Stats — llm-stats.com

**定位**：覆盖最广的聚合站之一，357~373 个 canonical 模型、725 benchmarks、56 capabilities，定位「先看复合指数，再下钻单项评测」。

**核心功能**
- **复合分用 TrueSkill 保守评分（μ − 3σ）**，明确说这是保守估计（而非平均值），并给出「所有输入都来自公开 benchmark 或实时 API 指标」。
- 表格列：`Open Rank / Model / LLM Stats / Reasoning / Coding / Agent / Context / Speed / Pricing $/M / License`。
- 每个模型有 **Benchmark 雷达图**（完整能力画像）。
- **每个能力维度都有一个独立指数**（Overall / Reasoning / Coding / Math / Vision / Tool use / Agents / Long context / Factuality / Writing / Research / Finance / Healthcare / Legal）。
- 数据新鲜度显式标注：`Data checked Oct 7, 2:00 PM UTC · refreshes every 30 min`。
- 价格做了「混合口径」：8 input : 1 output blend 与 20:1 blend 都在，说明不是拍脑袋。

**界面与交互特点**
- 表格顶部有一行**「当前各维度冠军」摘要**（leads on reasoning / wins at coding / cheapest in the top 10 / fastest output / longest context window / best open-weights），直接回答"我该看哪一行"。
- 条形长度明确声明 **「Bar lengths show the spread within this top-ten field, not a zero-based scale」**——避免视觉误导，这点极专业。
- 每个 benchmark 卡片带：模型数、类别、一句话解释（这个 benchmark 测什么）、`Community benchmark` 标记。

**可借鉴点**
1. **「各维度当前第一」摘要条** —— 我们的表格顶部目前只有统计数字，可以升级成「推理第一 / 代码第一 / 性价比第一 / 开源第一」这一行。**成本极低、观感提升极大。**
2. **条形图非零基线的显式声明** —— 我们已经去掉彩虹 palette，但条形图还没做这个声明。一句话注释即可避免"视觉撒谎"的指责。
3. **Benchmark 卡片带方法论说明** —— 我们的分榜明细每榜都有 `metric` / `source_url`，但页面上没把"这个榜测什么"用人话讲出来。加一段 1-2 句的介绍，能显著提升可信度。
4. **canonical 模型数公开** —— 我们的 master data 层已经算出了 canonical 数，应该在页面显示（现在只在 `cross_meta` 里）。

---

### A3. Epoch AI — epoch.ai/data/ai-benchmarking-dashboard

**定位**：研究机构视角，做「AI 能力趋势」而非「今日谁第一」，面向研究者与政策分析。

**核心功能**
- **ECI（Epoch Capabilities Index）**：把 39 个不同 benchmark 合成单一「通用能力」标尺（当前榜首 167 分），并公开合成方法。
- **89 个 benchmark 被追踪**，明确区分三类数据来源：**Epoch 自己跑的 / benchmark 创建者跑的 / 模型厂商跑的**。
- 每个数据点都挂 **provenance（来源溯源）**。
- 更新日志按日期列出结论（如「Claude Opus 5.5 以 167 分登顶，GPT-6 Astra 紧随」），而不是只丢一张图。

**界面与交互特点**
- **Graph / Table 双视图切换**：同一数据，图看趋势，表看精确值。
- **Graph Settings 面板**：按 release date 筛选时间窗、按 organization 高亮（OpenAI / Google / Anthropic / Meta / xAI / Other）、**圈大小（Circles sized by）可绑定到任意维度**。
- 每张图都带 **Share / Download graph / Cite** 三个动作，并标 **CC-BY** 许可与引用说明。
- 明确声明 ECI 基于 39 个 benchmark 合成，并链到方法页。

**可借鉴点（这是我们当前最大的缺口）**
1. **provenance 溯源** —— 我们的 `appearances` 里其实已经存了每个榜的名次、分数、metric、is_new，但页面上只显示"出现在几个榜"。**把它做成可展开的溯源面板**（点开看到每个榜的原始名次与链接），这是从"聚合站"升级为"可信聚合站"的关键一步，而且数据已经现成。
2. **图/表双视图** —— 我们的趋势图和跨榜表是两个独立 section，可以做成同一数据的两视图切换。
3. **数据来源三分法** —— 我们天然有这个信息（实时抓取 / Wayback 镜像 / LKG / 人工数据），应在每行标注"这条数据是实时抓的还是兜底来的"（我们已有降级横幅，但没做到行级）。
4. **CC-BY + 引用格式** —— 我们聚合的是别人数据，加上许可与引用说明是合规必需。

---

### A4. Vellum LLM Leaderboard — vellum.ai/llm-leaderboard

**定位**：任务导向（job-to-be-done）排行榜，只收 2024-04 之后发布的 SOTA 模型版本，**明确排除已饱和的 benchmark（如 MMLU）**。

**核心功能**
- 榜单按**任务**切分，而不是按 benchmark 名：`Best Overall (HLE)` / `Best in Reasoning (GPQA Diamond)` / `Best in Agentic Coding (SWE-Bench)` / `Best for Work Automations (AutoBench)` / `Best in Computer Use (OSWorld)` / `Best in Browsing (BrowseComp)` / `Best in Terminal Use (Terminal-Bench 2.1)`。
- 三个运维榜单：`Fastest Models (Tokens/sec)` / `Lowest Latency (TTFT)` / `Cheapest Models (per 1M tokens)`。
- **Compare models**：并排对比，且**共享同一批已选模型**（切换榜单时选择不丢）。
- **Model Comparison 表**：`Context size / Cutoff date / I/O cost / Max output / Latency / Speed`。
- **Benchmark glossary**：内置术语表。

**界面与交互特点**
- 每个榜单是一段 **横向条形排名**（前 5-20 名），数字直接标在条端。
- 每个榜单标题括号里写明**用的哪个 benchmark**（如「Best in Reasoning (GPQA Diamond)」），任务名与评测名同时出现——这是「人话 + 严谨」的平衡。
- 表格允许同一模型出现两次（如 Claude Opus 4.1 在 Dashboard generation 与 Data insights 得分差异大），**不强行合并**。

**可借鉴点**
1. **「任务名（benchmark 名）」双层命名** —— 我们的 tab 现在是 `LMArena Text` / `AA Intelligence` / `SuperCLUE`，对陌生访客不友好。改成「对话偏好（LMArena Text）」这种双层结构，可用性立刻提升。
2. **显式排除饱和 benchmark** —— 我们应声明「MMLU 等已饱和指标不纳入跨榜结论」，这是专业信号。
3. **对比选择持久化** —— 我们已有列选择器，切换榜单时应该保持。
4. **运维三榜（最快/最低延迟/最便宜）** —— 我们有 speed/price 数据吗？若无，可作为数据源扩展方向。

---

### A5. AI Stupid Level — aistupidlevel.info

**定位**：方法论最激进的独立榜，把「统计不确定性」和「数据口径」全部摆到台面上。

**核心功能**
- 四个榜：`Combined`（coding 50% + reasoning 25% + tool use 25%）/ `Coding` / `Reasoning` / `Tool use`，**各自独立重测频率**（coding 每 4 小时、其余每天）。
- **Drift monitor**：比较「模型与自己的过去」而不是「模型与模型」，用于发现能力漂移/回归。
- **社区资助模型**：停止付费的模型，用户可以自己掏 API key 资助下一次测试，结果照常公开。
- Watchlist + 邮件告警（如"编码分比一周前低 5 分以上"触发）。

**界面与交互特点（这是同类站里最强的）**
- **四种布局可切换**：`Connected`（四个榜并排，同模型连线，一眼看出强项与滑坡）/ `Side by side` / `Table`（一行一模型，四榜分数+价格，点表头排序）/ `Top 5`。
- **`=4` 表示统计并列**：规则是「除非上一组领头者领先超过 1.96 × 合并标准误（双样本 95% 检验），否则并入该组」，所以出现 `1, 1, 1, 4` 这种名次是正常的——**把统计不显著性直接写进排名本身**。
- **琥珀色注记 `5/7 tasks`**：厂商拒绝作答的题不算 0 分，但注记跟随分数保留，且**拒绝过任务的模型永远不会被标为与全测模型并列**。
- **新鲜度阈值明确**：coding 分数 8 小时、reasoning/tool 48 小时未更新即视为失效，该榜不排名（而不是显示旧分）。
- 灰色底部分组：无当前有效测评的模型单独成组，社区资助模型单独成组。
- 每一项都与 **test fingerprint**（每个 prompt / 测试 / 检查的版本指纹）绑定，"我们改了测试" 与 "模型退步了" 可区分。

**可借鉴点（强烈建议逐条抄）**
1. **统计并列** —— 我们有 Elo/Arena Score，天然有噪声。把「分差小于阈值即并列」写进排序并显示 `=`，是对付「跨榜分数不可直接比较」这一困局的**最诚实的解法**，而且成本只是改排序函数。
2. **琥珀色口径注记** —— 我们的 `variant` 折叠（如 `["32k / high"]`）本质就是「同模型不同配置」，应该用同样的注记样式说明"这条记录带档位"。
3. **失效阈值** —— 我们已有 `stale_days` 工具与降级横幅，但可以像它一样**按榜设阈值**（如 LMArena 7 天、SuperCLUE 30 天），超过即从跨榜结论中剔除而非仅标色。
4. **与自己比（Drift）** —— 我们的 `trend.json` 已在存时间序列，做一个"进步/退步"视图是现成的数据。
5. **方法论页面** —— 它有一个完整 methodology 页，逐条列出「每个权重、阈值、统计规则」。我们应该有一页 `/methodology`，把我们 `cross_meta` 里那些规则（min_boards=2、排序四键、变体折叠规则、厂商归一规则）全部写出来。

---

### A6~A10. 其他多榜聚合站（速览）

| 站点 | 定位 | 核心功能 | 可借鉴点 |
|---|---|---|---|
| **LLMBoard** (llmboard.ai) | 声称 1254 模型 / 23 leaderboards / 741 benchmarks | 把「能力信号」与「部署信号（价格、运行时）」**明确分栏**；模型目录可按厂商/类型/模态/价格过滤；有专门的「Scoring & Data」说明页 | **能力与部署分栏**这一条我们没做；我们应避免把速度/价格和 Elo 分数混在一个表里 |
| **llmleaderboard.in** | 印度视角，50+ 模型 | 表格含 **Country-of-origin 与 License 列**、历史 benchmark 进步图、场景化指南（best for coding / cheapest / 最大上下文） | 「历史进步图」+「场景指南」两个模块我们都能做（trend 数据已在） |
| **RankLLMs** (rankllms.com) | 极简「速度+价格+能力」三分 | #1 vs #2 对照区、Top 3 领奖台、每模型 Scorecard | **#1 vs #2 逐项对照**这个组件很轻，适合放在页面首屏 |
| **OpenTheRank** | Arena Elo 70% + Artificial Analysis 30% 混合 | 覆盖 chatbot/编码/图像/视频/搜索/音乐，**在价格旁标注免费额度** | 混合权重公式公开；「免费额度」是实用信息 |
| **DataLearner** (datalearner.com/leaderboards) | 国内平台 | **最多选 4 个模型横向对比**、国产模型维度最全、含 C-Eval / AGI Eval 等中文评测 | 「选 N 个模型对比」的交互是我们的列选择器的强化版；中文评测覆盖可与 SuperCLUE 互校 |

---

## B. 单一权威榜型（本项目的数据来源方）

理解它们的口径边界，才能在自己的聚合里不误用。

| 站点 | 定位 | 呈现特点 | 我们需要知道的口径边界 |
|---|---|---|---|
| **LMArena** (lmarena.ai) | 人类盲评二选一，Elo 排名；前身 LMSYS Chatbot Arena | 分 Text / Vision / Document / Search / WebDev / Agent 多子榜，**选模型要看与你任务最接近的分榜而非 Overall** | 「更喜欢」≠「更正确」；投票有偏；Elo 应看 95% bootstrap 区间而非点估计 |
| **Hugging Face Open LLM Leaderboard** | 开源权重模型的公开标准 | 多标准化基准（MMLU、ARC、TruthfulQA、GSM8K 等），可按模型大小/架构/量化精度过滤 | 主要覆盖开放权重；公开题集仍可能被专项优化 |
| **LiveBench** (livebench.ai) | 动态换题、客观答案评分，月度更新 | 核心卖点是**抗污染**：每月换新题 | 不擅长衡量主观写作体验 |
| **Stanford HELM** | 研究级多场景多指标 | 覆盖准确率、鲁棒性、校准、效率 | 阅读门槛高；按项目/版本发布 |
| **SWE-bench / Terminal-Bench / SWE-rebench / DeepSWE** | 软件工程 Agent 专项 | SWE-rebench 提供**去污染滚动窗口**（选日期范围得解决率+置信区间）；DeepSWE 公开成本与步数 | **成绩强烈依赖 Agent harness**（同一底座模型用弱 harness 40%、强 harness 70%），排名必须标注 harness |
| **Scale Labs SEAL** | 企业级专家构建评测 | 覆盖编码、经济价值工作、安全、科学 | harness 标签必须区分（native Codex vs mini-swe-agent） |

> **对本项目的直接含义**：我们的 `appearances` 里记录名次时，应同时保留「该榜的 harness / 口径说明」链接。否则用户拿我们的跨榜视图去下采购结论，会出现口径误用。

---

## C. 使用量 / 市场信号型

### C1. OpenRouter Rankings — openrouter.ai/rankings

**定位**：**不是质量榜**，是「真实使用量榜」——按通过其 API 处理的 token 数排名。它自己反复强调这一点。

**核心功能**
- 多时间窗：`Today` / `This Week` / `This Month` / `New & Trending`（周环比变化，且只收当周 ≥100 万 token 的模型，防止小基数产生大百分比）。
- **Market Share**：按模型作者统计请求份额。
- 多维份额：语言、编程语言、领域、上下文长度分布、工具调用、图像处理量。
- **Top Apps**：按应用维度的 token 消耗。
- Benchmarks 分栏：引用 Artificial Analysis 与 Design Arena，另有自跑的 GPQA Diamond。

**界面与交互特点（方法论呈现的教科书）**
- 页面底部有一整段 **"How these rankings are measured"**，逐条说明：
  - **What is measured**：数 prompt + completion token，按模型变体分别统计（free 变体单独排），私有请求排除。
  - **Selection period**：三个窗口分别是 1/7/30 天滚动。
  - **Freshness**：「页面上方的日期是**最新数据桶**的日期，不是页面渲染/部署时间」——这句话精准解决了一个常见困惑。
  - **How to read these rankings**：明确列出「这些排名**不代表**准确率、推理能力或 benchmark 表现」「不衡量用户数或花费」「不同模型 verbosity 与 tokenization 不同，token 总量高只说明用得多」。
- 数据以 **CC BY 4.0** 授权，提供 **Data API** 与引用格式。

**可借鉴点**
1. **把「我们测什么 / 不测什么 / 新鲜度如何定义」写成页面固定段落** —— 我们的 `disclaimer` 已有一段，但可以升级成 OpenRouter 这种结构化条目。
2. **「新鲜度的定义」** —— 我们的 `generated_at` 是生成时间，但用户未必理解。加一句"这是数据抓取时间，不是页面渲染时间"。
3. **数据许可 + API** —— 我们在聚合别人数据，同时也在产出数据；开放 `merged.json` 的引用格式与许可，能吸引二次使用与引用。

---

## D. 中文 / 国产评测

### D1. SuperCLUE — superclueai.com

**定位**：中文通用大模型综合测评基准，CLUE（2019 起）在大模型时代的延续。

**核心功能**
- **六维权重公开**：智能体编程 25%、数学推理 18%、科学推理 16%、精确指令遵循 16%、幻觉控制 16%、智能体任务规划 9%（合计 100%）。
- 表格列：`排名 / 模型名称 / 机构 / 开闭源 / 总分 / 各维度分 / 属地 / 使用方式 / 是否推理 / 测评发布日期`。
- 另有「生成耗时」（每题平均秒数，衡量响应效率）与「价格」（官方标准价，按输入:输出 = 3:1 加权估算，元/百万 tokens，并拆出 Input / Output 两列）。

**界面与交互特点**
- **并列规则显式**：「榜单将分差 1 分内的模型视为并列排名」。
- **「国外模型与部分国内模型不参与排名，只做参考」**——在表格中用 `-` 前缀（如 `-Gemini-3.1-Pro-Preview`）表示非排名项，但仍列出数据。
- 有多个子榜（通用、SWE、Agent 产品榜 xclaw），并有 **成绩口径切换**（平均成绩 / 单次测评成绩）与 **数据批次切换**（按月份）。

**可借鉴点**
1. **并列规则** —— 与 AI Stupid Level 同一思路，中文榜也这么做。我们应跟进。
2. **「不参与排名只做参考」的处理** —— 我们的 `region=other` / 未注册模型（如 `inkling`、`trinitylargethinking`）现在是被排除出跨榜表。SuperCLUE 的做法更友好：**列出但标灰、不参与排序**。
3. **「是否推理」独立列** —— 我们的 `variant` 折叠已经处理了 `(thinking)`/`-high`，可以直接暴露成「推理档位」列。
4. **`开/闭源` 与 `属地` 两列** —— 正是我们刚建好的 `open` 与 `region` 字段，SuperCLUE 证明这两列是中文用户的刚需。

### D2. OpenCompass / CompassRank（上海人工智能实验室）

**定位**：开源可复现的大模型评测平台，2.0 版本构建「铁三角」：**CompassRank（榜单）+ CompassHub（开源社区）+ CompassKit（工具链）**。

**核心功能**
- 五大核心维度（学科、语言、知识、理解与推理），整合 70+ 数据集、40 万评测问题；2.0 新增数学、代码、智能体维度。
- **数据污染检测**、长文本评估、视觉语言模型与代码评测；覆盖法律、金融等垂直领域。
- 支持分布式高效评测、中英双语基准。

**可借鉴点**
- **「榜单 + 工具链 + 社区」的三层结构**：我们目前只有「榜单」。中期可考虑把 `src/` 的抓取与归一化脚本整理成可被他人复用的工具（CompassKit 模式），这能显著提升项目影响力。
- **数据污染检测**：我们聚合的榜单本身可能被污染，在页面上提示"公开题集可能被专项优化"是可加的一句免责。

### D3. 其他中文平台（提及）

- **FlagEval**（智源）、**AGI-Eval**（上海交大/清华系）、**ReLE**（中文大模型能力评测开源项目）—— 均为可关注的中文评测来源，可作为 SuperCLUE 之外的第二、第三中文信号源，降低单一中文榜的刷榜风险。

---

## E. 开源可直接抄的参考实现（代码级）

### E1. llm-benchmarks — GitHub: brabos-ai/llm-benchmarks

**为什么单独列出来**：它与本项目的**技术栈几乎重合**，而且完全开源。

- **栈**：Astro (SSG) + TypeScript + Apache ECharts (CDN) + Cloudflare Pages + `cloudflare/wrangler-action`。
- **数据**：构建时从 OpenRouter API 拉取（build-time fetch），落到 `src/data/models.json`。
- **组件**：`ModelCard.astro` / `ModelProfile.astro` / `ModelSelector.astro` / `RadarChart.astro` / `BarChart.astro` / `ComparisonDashboard.astro`。
- **特性**：多模型横向对比（交互式柱状图）、**单模型页带雷达图**、**完整暗/亮双主题平滑过渡**、响应式、静态零 JS 优先 + 需要交互处才上 JS。

**对本项目的意义**
1. **与我们的架构选型直接互证**：之前调研推荐的「短期零构建自建 token 系统，中期 Astro + 岛屿」在这个项目上得到了实证——它就是用 Astro 做的，且做到了零 JS 默认。
2. **图表用 ECharts**：我们目前是手写 SVG。ECharts 能白送交互（hover 取值、图例开关、缩放），代价是引入 CDN 依赖（与我们的"纯单文件零依赖"原则冲突，但可作为中期选项）。
3. **`RadarChart.astro` + `ModelProfile.astro` 正是我们缺的模块**：我们的模型详情目前只散落在表格里，没有独立画像页。

---

## F. 方法论参考（非站点，但价值最高）

### F1. 《Designing an LLM Leaderboard That Can Survive Change》（dev.to）

一篇界面级的 LLM 排行榜设计备忘录，提出的概念与本项目刚做完的 master data 层高度呼应。

**核心观点**
1. **先定信号分类学（signal taxonomy），再谈配色**。它建议分成四类：
   - **capability signals**：模型在某个定义好的任务族上的表现（分数）
   - **deployment signals**：成本、延迟、可用性、运行约束
   - **evidence signals**：benchmark 名、日期、覆盖范围、测量口径
   - **catalog metadata**：模型身份、厂商、模态、状态
   > **四类若过早坍缩成一个分数，界面会变得有说服力但无法审计。**
2. **「一行是一条记录，不是一个数字」**。一条有用的记录应包含：稳定模型 ID、厂商与模型家族、评测类别与 benchmark 名、分数与单位、评测日期与新鲜度状态、价格基准与币种、运行时测量范围、来源/方法论引用、置信度或可比性说明。
   > 「当厂商改了模型名、benchmark 升版、或一个地方按百万 token 计价另一个地方按请求计价时，UI 不应让两条测量契约不同的记录看起来一模一样。」
3. **让比较状态显式**：表格附近要有一行紧凑状态摘要（当前模态、任务类别、benchmark、日期范围、价格基准、排序字段），并且**筛选状态应进 URL 或可恢复**，以便分享。
4. **为「视图之间的分歧」而设计**：最有信息量的时刻不是某模型横扫所有表，而是**不同任务/价格/速度下冠军易主**。不要藏起这种分歧，要让它可读。给出的模式：
   - 切换 benchmark 时**保持已选模型的对比抽屉**
   - **"why this row?" 面板**：显示该行的指标、日期、来源
   - **新鲜度徽章**：区分 current / aging / unavailable
   - **独立的部署视图**，避免价格与延迟冒充能力
   - 当模型无法在同等条件下比较时，给**明确的空状态**
5. **先测失败态**：「Not available」不等于 0，「Not comparable」不等于排名低，「Last updated」不等于「verified today」。
6. **发布前的四问自检**：读者能否不查文档就识别任务与指标？审阅者能否找到测量日期与来源？删除或改名一个模型是否改变历史含义？团队能否解释这个分数**不**测什么？
7. **原始测量与编辑呈现分离**：卡片可以显示四舍五入的分用于扫读，详情视图保留原始单位、来源与时间戳——这样改版不会重写旧结果的含义。

**为什么这条对我们最重要**：我们刚刚做的 master data 层解决了「数据混乱」，但**页面上还没有把"测量契约"暴露出来**。这篇文章给的就是「暴露契约」的具体 UI 模式清单。

---

## G. 横向对比速查表

| 站点 | 类型 | 模型数 | 复合指数 | 置信度/并列处理 | 溯源 | 图/表切换 | 暗色主题 | 数据许可 |
|---|---|---|---|---|---|---|---|---|
| Artificial Analysis | 聚合 | ~600 配置 | Intelligence Index (10 项) | 95% CI | 有方法页 | 散点为主 | 是 | 未明示 |
| LLM Stats | 聚合 | 357~373 canonical | TrueSkill (μ−3σ) | 保守评分 | 每 benchmark 卡片 | 雷达图 | 是 | 未明示 |
| Epoch AI | 聚合/研究 | 257 结果 | ECI (39 benchmarks) | — | **逐点 provenance** | **Graph/Table** | — | **CC-BY** |
| Vellum | 聚合/任务导向 | SOTA（2024-04 后） | 无（分任务） | — | 注明来源方 | 条形 | 是 | — |
| AI Stupid Level | 聚合/统计严谨 | — | Combined (50/25/25) | **`=` 并列 + 1.96×SE** | test fingerprint | **4 种布局** | — | — |
| OpenRouter | 使用量 | 300+ | 无（token 排名） | — | **完整方法论段** | 多图 | 是 | **CC-BY 4.0 + API** |
| SuperCLUE | 中文聚合 | 24~30/期 | 六维加权（权重公开） | **1 分内并列** | 发布日期列 | 表格为主 | — | — |
| OpenCompass | 中文评测平台 | 70+ 数据集 | 五维 | 污染检测 | — | 榜单+工具链 | — | 开源 |

---

## H. 可操作性强的设计思路（按投入产出比排序）

### H1. 立刻能做（数据已就绪，只是没暴露）

1. **行级溯源面板**：`appearances` 已存每榜名次/分数/metric/is_new → 点击某行展开"这一行是怎么来的"。**这是本项目最大的差异化点，零新增抓取。**
2. **各维度当前第一摘要条**：从现有 cross 数据里取推理/代码/性价比/开源的第一名，放在表格上方。
3. **国家级筛选器**：`region` 字段已备，加一个 `全部 / 中国大陆 / 美国 / 其他` 切换即可。
4. **统计并列显示**：在排序里引入"分差小于阈值即并列"，显示 `=` 前缀。
5. **方法论页面 `/methodology`**：把 `cross_meta` 里的规则（min_boards=2、排序四键、变体折叠四类尾巴、厂商归一、region 推导）写成页面。
6. **新鲜度语义化**：把 `generated_at` 旁的文案改成"数据抓取时间，非页面渲染时间"，并按榜标注滞后天数（`stale_days` 已实现）。
7. **任务名（benchmark 名）双层命名**：tab 从 `LMArena Text` 改成 `对话偏好（LMArena Text）`。
8. **"不参与排名只做参考"分组**：把 `region=other` / 未注册模型从"排除"改为"列出但标灰、不排序"（SuperCLUE 做法）。

### H2. 需要一点开发（1-2 天量级）

9. **能力 vs 成本散点图 + Pareto 前沿**：替换/补充现有折线趋势图。
10. **模型画像页/抽屉**：一模型一卡，含雷达图或条形画像（对标 llm-benchmarks 的 `ModelProfile`）。
11. **图/表双视图切换**：同一数据两视图（对标 Epoch AI）。
12. **DRIFT（与自己比）视图**：`trend.json` 已在存时间序列，做"本周进步/退步榜"。
13. **对比抽屉持久化**：切换榜单时保持已选模型（对标 Vellum）。
14. **URL 可分享状态**：把筛选/排序/翻页写进 query string（对标 dev.to 第 3 点）。
15. **能力/部署分栏**：把速度、价格、上下文长度拆到独立区域，不与 Elo 混排（对标 LLMBoard）。

### H3. 中期（需扩展数据源或重构）

16. **接入使用量信号**：OpenRouter 有 CC-BY 4.0 的 Data API，可加一个"真实使用量"维度——与"评测分数"形成对照叙事。
17. **中文多源交叉**：SuperCLUE 之外补 FlagEval / AGI-Eval，降低单一中文榜的刷榜风险。
18. **数据许可与引用格式**：给 `merged.json` 明确许可（建议 CC-BY 4.0）并提供引用格式。
19. **工具链化**：把 `src/` 的抓取+归一化脚本整理为可复用工具（对标 CompassKit），提升项目外部价值。
20. **图表库评估**：若交互需求上升，评估 ECharts（对标 llm-benchmarks）；但需权衡与"零依赖单文件"原则的冲突。

---

## I. 需要警惕的坑（来自本次调研的负面信号）

1. **不要过早合成单一总分**。Artificial Analysis 自己的评测文章都承认「复合分可能掩盖任务特定优势」。本项目目前"不做跨榜总分"的决定是正确的，应坚持。
2. **harness 效应**：SWE-bench 类成绩强依赖 Agent 框架，同一底座模型可差 30 分。聚合时若不标注 harness，会误导用户。
3. **公开题集污染**：多个来源指出公开 benchmark 可能被专项优化，且 OpenAI 2026-07 审计发现 SWE-Bench Pro 约 30% 公开任务已损坏。聚合站有必要提示这一点。
4. **榜单会停更**：多篇 2026 年评测文章提到「一些被广泛引用的榜单已经停更」。这反过来说明**我们自动抓取 + 新鲜度监控 + 降级可见**的设计方向是对的，应继续强化"滞后天数"的可见性。
5. **不要用 token 量冒充质量**：OpenRouter 反复强调其排名"不衡量准确率"。若我们将来接入使用量数据，必须同样明确区分。

---

## 附：本次调研的原始来源

- Artificial Analysis — https://artificialanalysis.ai/
- LLM Stats — https://llm-stats.com/ 与 https://llm-stats.com/benchmarks
- Epoch AI — https://epoch.ai/data/ai-benchmarking-dashboard
- Vellum LLM Leaderboard — https://www.vellum.ai/llm-leaderboard
- AI Stupid Level — https://aistupidlevel.info/faq 与 /methodology
- OpenRouter Rankings — https://openrouter.ai/rankings
- SuperCLUE — https://superclueai.com/
- OpenCompass（百度百科条目）— https://baike.baidu.com/item/OpenCompass/63834152
- llm-benchmarks（开源）— https://github.com/brabos-ai/llm-benchmarks
- 设计方法论 — https://dev.to/zhebuildsthings/designing-an-llm-leaderboard-that-can-survive-change-4p7o
- 2026 榜单纯净度讨论 — https://mehmetbaykar.com/posts/best-websites-to-compare-ai-llms-in-2026/
- LLM 排名局限性 — https://aiwiki.ai/wiki/large_language_models_ranking
