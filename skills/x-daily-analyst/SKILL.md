---
name: x-daily-analyst
description: X 推文批量数据智能分析师。读取 x-scraper batch（默认 ~/data/x-daily/latest），按类别聚合推文，从 Data & AI 产品经理 / 技术负责人 / 超级个体视角提炼最多 Top 5 主题。支持单类别 interactive 输出，或全类别 batch report（含必选「今日总判断」）。不重新抓取 X。适用于「分析最新 X batch」「全类别简报」「分析 model_vendor」「从 PM/技术/超级个体视角解读」等。
---

# X 每日推文智能分析师

## 使用场景

对 x-scraper 已生成的 batch 做深度分析：默认 `~/data/x-daily/latest/meta.json` → `batch_dir`；无效时再要求用户提供 batch 路径。不重新抓取 X。

典型触发语：
- 「分析今天/最新的 X 日报」「全类别 / 整个 batch 分析」
- 「分析 `model_vendor` 这个类别」
- 「从产品经理 / 技术负责人 / 超级个体视角解读」

## 数据源

- **指针**：`~/data/x-daily/latest/meta.json` → `batch_dir`
- **索引**：`{batch_dir}/batch_category_index.json`（`categories` 以文件为准）
- **推文**：`{batch_dir}/raw/*.json`

## Batch 预检

开始 single 或 batch 分析前，先完成预检；预检失败时停止分析并要求用户提供有效 batch 路径。

1. 默认读取 `~/data/x-daily/latest/meta.json`，从 `batch_dir` 字段解析真实 batch 目录；如果用户显式提供 batch 路径，则使用用户路径。
2. 确认真实 batch 目录存在，且目录名匹配 `x-posts-batch-YYYYMMDD-HHMMSS`。
3. 读取 `{batch_dir}/batch_category_index.json`，确认 JSON 可解析，且 `categories` 为非空对象。
4. 后续类别枚举、single 类别校验、batch 覆盖范围均以 `batch_category_index.json` 的 `categories` 为准；不要扫描 `raw/` 自行推断类别。
5. 报告日期从 batch 目录名解析：`YYYYMMDD` → `YYYY-MM-DD`；不要使用当前系统日期。
6. 报告头部的推文总数优先使用 `{batch_dir}/summary.json.total_tweets`。只有字段存在且为可信数字时才写 `{N} 条`；否则写 `未知`。实际主题分析仍以 `extract_posts.py` 输出为准，不用总数字段推断主题。

## 模式判定

先判定模式、视角、输出，再进入对应流程。已说清则直接执行；无法映射时只补问缺失项。

| 用户意图 | 模式 | 默认输出 | 处理 |
|----------|------|----------|------|
| 指定一个类别，或只提到某个类别 key | `single` | `interactive` | 只分析该类别 |
| 明确说全类别 / 整个 batch / 每日总报 / 全类别简报 | `batch` | `report` | 覆盖全部类别，输出一份 report |

视角三选一：
- **Data & AI 产品经理**：竞品最近强调的产品方向、功能卖点、客户案例、定价变化、用户反馈、生态合作、市场叙事；业界正在讨论的新需求、新场景、新痛点；行业趋势、主流价值场景，以及产品竞争力构筑点。
- **技术负责人**：技术路线优劣、架构选择逻辑、优秀开源项目与 benchmark、工程实践方法、性能瓶颈与优化、成本优化、安全风险与应对技术、技术争议；技术大 V 对框架、模型、Agent、数据平台能力的真实评价。
- **超级个体**：新出现的工具、模型、工作流、Skill、提示词、自动化方法、内容选题、赚钱机会；值得模仿的博主表达方式、选题角度、增长方法、产品化路径；能快速沉淀为个人能力资产的趋势。

视角是解读维度，不是岗位指令。判断段说明该事实在当前视角下改变了什么、证明了什么、影响了什么；不要写成给读者分派动作的命令句。

用户没有指定视角，或无法映射到三者之一时，先询问用户。类别必须来自 `batch_category_index.json` 的 `categories`；single 模式类别不明时，列出可选类别请用户确认。

## Single 模式

用于一个类别的即时分析。

完成定义：
- 只分析一个类别。
- 聚合跨账号同事件，输出最多 Top 5 主题；有效主题不足 5 个时不要硬凑。
- 输出 interactive 格式，适合对话或微信竖屏阅读。

步骤：
1. 确认 `batch_dir`、批次日期、category、视角。
2. 运行 `extract_posts.py` 提取该类别推文。
3. 按「共用分析规则」必要时补全事实。
4. 聚合主题，按当前视角写事实与意义。
5. 按 Single 校验项检查后输出。

输出格式：

```text
📊 X 情报 · {category} · {perspective}视角 ({date})

1️⃣ {topic_title}

📌 事实：
...

💡 意义：
...

────────────
```

Single 校验：
- category 是否来自 `batch_category_index.json`。
- 主题是否基于真实推文与必要补全，未把低信息量内容硬凑为 Top 5。
- 事实是否写清发生了什么；意义是否对应当前视角。

## Batch 模式

用于全类别结构化 report。目标始终是 **一份** report，不是 N 份类别报告。

完成定义：
- 覆盖 `batch_category_index.json` 中全部类别。
- 每类输出最多 Top 5 主题；有效主题不足 5 个时不要硬凑。
- 同一事件跨类别重复时，只在最相关类别展开一次。
- 输出一份完整 report，格式见 `references/report-output.md`。
- 全文末尾必须有 `今日总判断`，至少 3 条、最多 5 条。

步骤：
1. 完成 Batch 预检，确认 `batch_dir`、批次日期、视角、类别数量、头部推文总数；告知用户当前将读取的 batch 与模式。
2. 对 `batch_category_index.json` 中全部类别分别运行 `extract_posts.py` 提取推文文本；各类别互不依赖，调用方可按自身能力顺序处理、并发处理或分派处理。
3. 基于各类别提取结果，逐类生成类别块草稿；各类别草稿彼此独立，但都只是最终 report 的中间材料。
4. 读取全部类别块草稿，一次性合并为一份 report；合并必须综合处理，不能拆成多个独立报告。
5. 做跨类别去重：重复事件保留在最相关类别，其它类别改为跳转主题。
6. 写 `今日总判断`：只能在所有类别块就绪并完成去重后写一次。
7. 按 Batch 校验项检查；若涉及 HTML/PDF格式转换、邮件外发，再读取 `references/delivery.md`。

Batch 要点：
- 本 skill 不强制要求使用子智能体；是否分派给子智能体、后台任务或多次工具调用，由外部调用方决定。
- 全类别分析时，可优先处理更可能出现主事件和跨类别重复事件的高信息密度类别，例如 `model_vendor`、`ai_infra`、`cloud_platform` 等；这只是效率建议，不改变最终必须覆盖全部类别的要求。
- 没有「只做逐类草稿、不合并」的 batch；逐类草稿只是中间材料。
- 跨类别去重不能在单个类别分析里完成，必须在合并 report 时对照全部类别块。
- 跳转主题的 `事实：` 须含 `详见 <category> 主题 <NN>。本主题不重复展开。`
- `推文链接：` 仅来自 `extract_posts.py` 输出中的 `[原文: ...]`；不要用官网 / 博客 URL 替代推文链接。

Batch 校验：
- 是否覆盖 `batch_category_index.json` 中全部类别。
- 每类主题是否最多 Top 5，且没有硬凑低信息量主题。
- 是否输出一份 report，而不是 N 份类别报告。
- 是否完成跨类别去重，跳转主题是否包含「不重复展开」。
- report 是否含固定头部、类别块、主题字段、推文链接与全文末尾 `今日总判断`。
- 报告日期是否来自 batch 目录名；推文总数是否只来自可信 `summary.json.total_tweets`，缺失时写 `未知`。
- `今日总判断` 是否 3-5 条，且来自跨类别归纳。

## 共用分析规则

### 信息补全

**触发**（满足任一即可考虑补全，仍遵守「必要才查」）：

1. 推文正文过短（如少于约 20 字）且几乎无实质信息，又无链接、无图说明。
2. 正文简略但带链接：`extract_posts.py` 输出中有 `[链接: ...]`，或正文中的 t.co / 官网 / 文档 / GitHub / 论文等 URL；推文本身说不清「发生了什么」时，优先打开链接落地页补全事实。
3. announcement / release 口吻（如 "We're excited to announce..."）但缺少对「X 是什么」的解释。
4. batch 内仅单条提及的新产品 / 公司 / 术语，且其它推文无法互证背景。

**来源优先级**：链接落地页（若为官方源）> 官方博客 / 文档 / GitHub release / 论文 / 官网 announcement > 可信媒体。

补全后须在「事实」中标注，例如：`补充自官方博客` / `补充自 GitHub release`（写明具体来源，而非只写「据链接」）。

**不触发**：
- 推文正文已自洽（有足够细节、数据、版本、结论），链接仅为佐证或重复信息。
- 同一主题在 batch 内有多条推文，已能拼出完整背景。
- 链接明显无关或无法验证；不强行补全，事实中可写「推文未展开，链接未提供有效补充」。

### 主题筛选

每类别最多 Top 5，按以下优先级筛选：

1. 官方发布、模型/产品/能力/定价/benchmark/开源/合作
2. 对当前视角有直接启发
3. 信息密度高
4. 多账号共识
5. 高互动但事实弱降权；纯观点/段子降权

每个主题固定两段：
1. **事实**：发生了什么（谁、何产品/版本/数据/链接）
2. **判断**：从当前视角的价值与影响；interactive 下标题为 `💡 意义`，report 下标题见 `references/report-output.md`

判断段写法：
- **产品判断**：写产品/市场含义，围绕竞品动向、功能卖点、客户案例、定价与反馈、生态合作、市场叙事、新需求/新场景/新痛点、行业趋势、价值场景与竞争力构筑点；避免 `PM 应...`、`产品经理应...`、`应立即...`。
- **技术判断**：写架构/工程含义，围绕技术路线优劣、架构选择逻辑、开源项目与 benchmark、工程实践、性能瓶颈与优化、成本优化、安全风险、技术争议与技术大 V 真实评价；避免 `技术负责人应...`。
- **实践启示**：写个人工作流/能力杠杆，围绕工具、模型、工作流、Skill、提示词、自动化方法、内容选题、赚钱机会、可模仿的表达/增长/产品化路径，以及能沉淀为个人能力资产的趋势；避免 `超级个体应...`。
- 可以写“适合关注/可作为观察项/不确定性在于”，但不要把判断段写成待办清单。

### 链接规则

- `interactive` 可在事实中简要提及来源。
- `report` 必须使用独立 `推文链接：` 字段。
- `report` 的推文链接只列 `[原文: ...]` 的 X 链接；无则写 `原始数据未提供推文链接`。

## 边界

- 不重新抓取 X；只读取已有 x-scraper batch。
- 不做情感/人身攻击。
- 主动补全事实；判断必须对应当前视角。
- 邮件、PDF、HTML 等交付脚本只是可用能力，不属于默认分析动作；是否串联、何时发送、发给谁，由外部调用方或用户明确指令决定。

## 辅助脚本

`{SKILL_ROOT}/scripts/` 下工具可复用。**分析必用**仅 `extract_posts.py`；其它交付脚本见 `references/delivery.md`，按外部调用方或用户需求使用。脚本不写死用户主目录；默认基于 `~/data/x-daily`，可用环境变量或 CLI 覆盖。

脚本能力地图：

| 脚本 | 何时使用 | 主文档是否展开 |
|------|----------|----------------|
| `extract_posts.py` | 分析前按类别提取推文文本 | 是，见下方 |
| `txt_to_html.py` | 用户或外部调用方要求把 report TXT 转 HTML | 否，读 `references/delivery.md` |
| `render_pdf.js` | 用户或外部调用方要求把 HTML 转 PDF | 否，读 `references/delivery.md` |
| `email_body.py` | 用户或外部调用方要求生成邮件正文 | 否，读 `references/delivery.md` |
| `send_email.py` | 用户或外部调用方明确授权邮件投递 | 否，读 `references/delivery.md` |

若任务涉及 HTML、PDF、邮件正文或邮件投递，先读取 `references/delivery.md` 再调用对应脚本。

### `extract_posts.py`

**用途**：从 x-scraper batch 按类别提取推文，供分析使用。

**调用**：

```bash
python3 "{SKILL_ROOT}/scripts/extract_posts.py" [--batch-dir <PATH>] --category <KEY> [--output <FILE>]
```

| 参数 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| `--batch-dir` | 路径 | 否 | `~/data/x-daily/latest` | 真实 batch 目录，或含 `meta.json` 的指针目录（从中解析 `batch_dir`） |
| `--category` | 字符串 | 是 | - | `batch_category_index.json` 中 `categories` 的键，如 `model_vendor` |
| `--output` | 路径 | 否 | stdout | 指定则将结果写入文件，否则打印到标准输出 |

**输出**：纯文本；每条推文含作者、时间、正文、`[链接: ...]`（推文内 URL）、`[原文: ...]`（X 推文页 URL）。

**示例**：

```bash
python3 "{SKILL_ROOT}/scripts/extract_posts.py" --category model_vendor
python3 "{SKILL_ROOT}/scripts/extract_posts.py" --batch-dir /path/to/x-posts-batch-20260602-020123 --category ai_infra --output /tmp/ai_infra.txt
```
