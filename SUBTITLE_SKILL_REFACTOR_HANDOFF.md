# 字幕 Skill 认知减负重构：问题清单与新会话交接

> 状态快照：2026-08-24  
> 仓库：`C:\Users\Alienware\feishuai-skills`  
> 涉及 Skill：`generate-and-process-subtitles`、`youtube-to-bilingual-video`  
> 当前结论：**NOT READY，不要合并；先停止追加特判，转入行为固化与信息架构重构。**

## 1. 为什么要重构

最近几轮为了修复字幕句尾闪屏、残句、重复尾词、跨 cue 断裂、产物发布安全等问题，代码、测试、说明文档和提示词都持续增长。新增能力中有不少是必要的，但当前形态已经出现两个不同层面的负担：

1. **实现负担**：入口脚本和 QC 模块承担过多职责，事务发布、路径安全、ASR、切分、QC、CLI 编排混在一起。
2. **认知负担**：同一条规则在 `SKILL.md`、references、提示词、脚本和复合 Skill 中重复出现；操作步骤、确定性约束、模型行为和历史事故说明没有清晰分层。

本次重构的目标不是简单“拆文件”，也不是删除已经验证有价值的安全能力，而是建立清晰的单一归属，使调用者只在需要时加载对应知识。

## 2. 当前分支与规模证据

当前工作树基于 `master`，相对 `origin/master` 为 `ahead 3, behind 1`，并包含大量未提交修改和新增文件。开始新会话时必须保留这些改动，不得重置、覆盖或假设它们已经可合并。

当前两个字幕 Skill 的工作树差异约为：

- 22 个已跟踪文件发生变化，另有 4 个新增文件；
- `+4773 / -236`；
- 原子 CLI `generate_and_process_subtitles.py` 从早期约 486 行增长到当前约 2012 行；
- `subtitle_tools/qc.py` 从引入时约 449 行增长到当前约 1046 行；
- 原子 `SKILL.md` 当前约 2029 词，复合 `SKILL.md` 当前约 1430 词；
- 原子 CLI 约 65 个函数，`run_transcribe` 约 282 行，`inspect_asr_data` 约 204 行，`run_qc` 约 164 行，`build_parser` 约 155 行；
- `qc.py` 含约 38 个常量、100 个条件分支和 90 个 `return`。

这些数字不是单独的质量判据，但与规则重复、职责交叉和实测漏检同时出现，说明继续增量堆叠的边际成本已经过高。

## 3. 两组真实实测证据

### 3.1 Agent Memory：局部问题已经暴露并人工修复

问题单：

`D:\PARA\projects\Databricks-youtube产品视频\Agent Memory EXPLAINED - Complete Architecture\ISSUE_双语字幕切分产生句尾闪屏与残句.md`

这组样本暴露了五类明显的观看问题，包括短依附尾句、重复尾词、长停顿后的残句等。现有工作树针对其中若干模式加入了 seam repair 和 QC；项目中的最终字幕也经过人工修复、重新渲染和验证。

但该案例只能证明特定簇可以被修复，不能证明规则已经具备泛化能力。

### 3.2 DeepSeek：当前版本仍然整体漏检

用户提供的路径没有对应文件；实际找到并检查的文件是：

`D:\PARA\projects\Databricks-youtube产品视频\DeepSeek Just Built the Next Generation of Coding Agents-test1\notes\字幕断句问题单.md`

问题单记录了 P01–P31，共 31 组问题，覆盖：

- 专有名词和标题短语被拆开；
- 介词、冠词、助动词等功能词悬空；
- 名词短语和动宾结构跨 cue 断裂；
- 中英文边界错位；
- 下一 cue 首字母大写造成“看似新句”的误判；
- 极短、无法独立阅读的碎片。

对 254 cues 的英文源字幕和双语字幕运行当前 QC，二者均返回 `exit 0`、`high_risk_count = 0`。报告保存在：

- `C:\Users\Alienware\.codex\visualizations\2026\08\21\01a02308-137e-7950-a7a0-4e3ed05dcad5\deepseek-test1-source-qc.current.json`
- `C:\Users\Alienware\.codex\visualizations\2026\08\21\01a02308-137e-7950-a7a0-4e3ed05dcad5\deepseek-test1-bilingual-qc.current.json`

因此，当前修复**不能解决 DeepSeek 样本的主要问题**。这不是再增加 31 条词表规则就能稳妥解决的问题，而是需要改写切分优先级、建立通用边界信号，并用真实夹具约束行为。

## 4. Skill 逻辑和提示词为什么变得臃肿

### 4.1 同一规则没有单一所有者

例如 `semantic split`、`review_required`、79 字符限制、source metadata 等概念，同时散落在多个 `SKILL.md`、references、提示词和脚本中。调用者难以判断哪一处是规范来源，修改者也容易漏改或产生冲突。

### 4.2 `SKILL.md` 同时承担路由、教程、事故复盘和实现细节

原子 `SKILL.md` 中存在接近 2900 字符的超长段落，把 seam repair、限制、验证、QC findings、人工审批和 stop gate 放在一起。它既不适合作为快速路由入口，也不利于精确维护。

### 4.3 提示词承担了本应由程序保证的确定性契约

当前提示词重复强调内容保持、长度限制、时序等要求。内容不变、时间轴合法、21/79 限制、输入输出路径和结构化结果，应由验证器和测试保证；模型提示词只应描述需要模型判断的语义边界。

### 4.4 切分提示词中的示例本身会诱导坏结果

`subtitle_tools/prompts.py` 的 split prompt 有一个示例，把：

`developers can build with the computer use beta`

和：

`on the anthropic api amazon bedrock...`

拆成两个 cue。这个示例明确示范了把介词短语孤立到下一行，与 DeepSeek 样本的失败形态一致，应删除并加入反例测试。

### 4.5 事故驱动的开放式词表无法自然收敛

不断补充“then we”“on the”“to be”等尾词或开头词，能提高局部召回，但会产生误报、重复条件和维护压力。应优先使用结构信号，而不是无限扩展短语枚举。

### 4.6 复合 Skill 重复描述原子 Skill 的内部流程

`youtube-to-bilingual-video` 应只负责端到端编排、状态传递和 hard stop，却重复解释了转写、切分、审核和验证细节，扩大了上下文成本，也造成规范漂移。

## 5. 最近独立审查尚未闭环的安全问题

按照黄金法则，修复通过测试不等于获得合并批准。最近一轮独立只读审查仍报告以下高风险点，开始结构重构前应先复核并以最小补丁解决：

1. 原子输出 pair lock 使用可预测路径和 `open("a+b")`，可能被 hardlink 指向其他文件；需要验证常规文件、单链接、reparse/inode 等安全属性。
2. renderer 的 `.render-*.lock` 存在同类 hardlink 风险。
3. `render_locked` 先归档旧产物，再提升 partial；若提升失败，可能使 canonical output 缺失，需要事务回滚。
4. unlock/close 清理路径只捕获 `OSError` 的位置需要复核，避免清理异常把已成功提交反转成失败。

这些是待复现、待修复、待重新审查的 finding，不能因为已有绿色测试而关闭。最终必须由新的独立 reviewer 给出按严重级别排序的结论和明确 merge verdict。

黄金法则依据：

`C:\Users\Alienware\.agents\agent_skill_黄金法则与最佳实践全景指南.md`

## 6. 目标信息架构

不要立即把当前能力拆成更多可发现的 Skill；这会增加触发、发现和编排成本。保留“一个原子 Skill + 一个复合编排 Skill”，但使用渐进式披露。

### 6.1 原子 Skill：薄路由入口

`skills/generate-and-process-subtitles/SKILL.md` 目标为 500–700 词，只保留：

- 能力边界和不支持事项；
- 输入类型到操作模式的路由表；
- 3–5 条真正的全局不变量；
- hard stop；
- 指向按需 reference 的链接。

建议 reference 划分：

- `references/transcribe.md`
- `references/split.md`
- `references/optimize.md`
- `references/translate.md`
- `references/qc.md`
- `references/output-contract.md`

### 6.2 复合 Skill：只负责编排

`skills/youtube-to-bilingual-video/SKILL.md` 目标为 400–700 词，只保留：

- 端到端阶段和状态机；
- 何时调用原子 Skill；
- 各阶段消费的结构化输出；
- `review_required` 等 hard stop；
- 最终产物验收和交付。

转写、切分、翻译、QC 的内部规则只由原子 Skill 拥有，复合 Skill 不再复述。

### 6.3 单一所有者矩阵

| 信息类型 | 唯一所有者 |
|---|---|
| 触发、路由、模式选择、hard stop | 对应 `SKILL.md` |
| 某一模式的操作步骤 | 对应 reference |
| 路径安全、事务发布、长度、时间轴、内容守恒 | 脚本与 eval |
| 需要 LLM 判断的语义偏好 | 最小提示词 |
| 项目专有名词、术语和例外 | job 级输入或 context artifact |
| 端到端阶段编排 | 复合 workflow |

任何规范性语句只能有一个所有者；其他位置只能链接或消费结构化结果，不能复制改写。

## 7. 提示词重构原则

当前主要提示词规模约为：optimize 506 词、standard translate 213 词、reflect translate 361 词、split 248 词。建议目标：

- split：120–160 词；
- optimize：150–200 词；
- standard translate：100–150 词；
- reflect translate：从默认路径隔离，仅显式启用时加载；
- 任一提示词原则上不超过 200 词，除非有 eval 证据证明更长文本带来稳定收益。

切分提示词只表达以下优先级：

1. 原文字符和顺序保持不变；
2. 优先形成可独立阅读的完整短语或语义单元；
3. 优先在标点和真实停顿处断开；
4. 长度是上限，不是切分目标；
5. 不孤立功能词、助动词、冠词、介词短语或专有名词片段。

模型只提出边界；程序负责验证字符守恒、时间轴、长度和输出契约。删除倒计时、强调性重复、历史事故说明和会诱导碎片的示例。

## 8. QC 的泛化方向

不要为 P01–P31 各写一条规则。优先验证以下紧凑信号：

- 前一 cue 没有终止标点且与下一 cue 时间相邻：视为 continuation candidate，不因下一 cue 首字母大写直接排除；
- cue 末尾或开头是悬空的功能词、助动词、冠词或限定词；
- 相邻 cue 存在重复尾部；
- 长停顿前的文本仍明显不完整；
- Title Case 或连续专有名词 span 被切断；
- 双语 cue 的语义边界明显不对齐。

专有词表应由每个 job 的上下文提供；核心 Skill 只保留通用检测机制。所有新规则都必须同时加入健康负例，控制误报。

## 9. 必须保留与应删除/迁移的内容

### 必须保留

- 严格 SRT 解析和时间轴验证；
- 成对产物的事务提交与回滚语义；
- immutable evidence、审计和人工复核 stop gate；
- source-language 验证与 metadata 绑定；
- 双语 cue 数量、时间和顺序一致性；
- viewer-facing QC 以及真实失败夹具；
- Windows/CP936、路径安全和跨平台输出契约。

### 删除或迁移

- 多处重复的流程说明和命令示例；
- `SKILL.md` 中的历史事故长段落；
- 可无限增长的具体尾词/动词列表；
- 复合 Skill 对原子实现的复述；
- 提示词中已经由验证器执行的确定性规则；
- 为了测试内部实现而固定精确正则或文案的脆弱断言。

## 10. 行为夹具与验收标准

重构前先固化可观察行为，而不是先移动代码。至少建立三组夹具：

1. **正常基线**：一个简单、无歧义的 transcribe/process/translate 流程；
2. **Agent Memory**：原始五组失败、修复结果和健康相邻样本；
3. **DeepSeek**：P01–P31 原始问题，以及数量相当的健康负例。

测试应回答“用户看见的产物是否正确”，不应绑定文档原句、函数名或某个具体正则。

完成条件：

- Agent Memory 已知簇不回归；
- DeepSeek P01–P31 有明确检测/修复覆盖，或被标记为需要人工复核，不能继续返回零风险；
- 健康负例的误报率在事先约定的阈值内；
- 内容、时间轴、cue 对齐和事务发布契约全部通过；
- 真实命令与 `--help`、Skill 文档一致；
- 新的独立 reviewer 完成黄金法则审查并给出 `READY`；
- 未获得 `READY` 前不得合并。

## 11. 分阶段执行计划

### Phase 0：冻结范围与安全止血

- 不再增加新的 QC 特判或提示词规则；
- 只复现并修复第 5 节的关键安全 finding；
- 运行相关最小测试，但不把“测试通过”当作合并批准。

### Phase 1：规则盘点

建立清单，逐条标记 `KEEP / MOVE / DELETE`，并记录唯一所有者。重点盘点两个 `SKILL.md`、所有 references、`prompts.py`、CLI 和 `qc.py`。

### Phase 2：特征化测试

把正常基线、Agent Memory 和 DeepSeek 转成可重复夹具。先记录当前行为，再定义目标行为和健康负例。

### Phase 3：只重写信息架构和提示词

先缩短 `SKILL.md`、references 和 prompts；除经过批准的行为缺陷外，保持运行行为不变。每删一条重复规范，都确保其唯一所有者仍然存在。

### Phase 4：实现层拆分

按职责拆分 CLI、artifact publishing、path safety、ASR orchestration 和 QC。优先组合和纯函数，避免为了“看起来架构化”引入抽象层。

### Phase 5：加入最小泛化修复

只针对 DeepSeek 夹具证明的通用信号增加紧凑规则；不得恢复开放式短语枚举。

### Phase 6：全量验证与独立审查

运行正向、负向、真实 CLI 和跨平台相关测试；随后启动新的独立只读 reviewer，使用黄金法则，输出按严重级别排序的 findings 和明确 merge verdict。

## 12. 复杂度预算

作为重构护栏，而不是机械 KPI：

- 原子 `SKILL.md`：500–700 词；
- 复合 `SKILL.md`：400–700 词；
- 默认加载段落尽量不超过 600–800 字符；
- 每个提示词原则上不超过 200 词；
- 一条规范只有一个所有者；
- 下一轮生产代码应实现净删除，目标减少 25%–35%；
- CLI 入口目标约 600–700 行以内；
- 单个实现模块目标 400 行以内；
- 普通函数目标 80 行以内，超出必须有明确单一职责理由。

## 13. 新会话的工作约束

- 不执行 `git reset --hard`、`git checkout --` 或覆盖当前 dirty worktree；
- 不提交、不推送，除非用户明确要求；
- 修改文件使用 `apply_patch`；
- 开始前读取本文件、黄金法则、相关 Skill 与当前 `git diff`；
- 先完成规则盘点和行为夹具，不直接继续追加 QC 特判；
- 修复完成后必须重新启动独立 reviewer；修复者不能自我批准合并。

## 14. 可直接复制的新会话启动词

```text
请在 C:\Users\Alienware\feishuai-skills 中继续字幕 Skill 的认知减负重构，范围仅限 generate-and-process-subtitles 与 youtube-to-bilingual-video。

先完整阅读：
1. C:\Users\Alienware\feishuai-skills\SUBTITLE_SKILL_REFACTOR_HANDOFF.md
2. C:\Users\Alienware\.agents\agent_skill_黄金法则与最佳实践全景指南.md
3. 两个 Skill 的 SKILL.md、相关 references、prompts.py，以及当前 git diff。

当前工作树有大量未提交改动，必须保留；不要 reset、checkout、提交或推送。不要直接继续添加 QC 特判。

第一阶段只做：
- 复核交接文档中的当前状态和未闭环安全 finding；
- 建立规则盘点表，为每条规则标记 KEEP / MOVE / DELETE 和唯一所有者；
- 把 Agent Memory 五组问题与 DeepSeek P01–P31 建成行为夹具，并加入健康负例；
- 给出最小重构批次，得到确认后再修改实现。

重构目标是降低 Skill 的逻辑、提示词、文档和代码认知负担，同时保留已经验证有价值的安全契约。修复后启动新的独立只读子智能体，按黄金法则输出 severity-ranked findings 和明确 READY / NOT READY；测试通过不等于允许合并。
```

