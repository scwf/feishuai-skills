---
name: agent-skill-collection-evaluator
description: Evaluate existing Agent skills found in third-party sources such as GitHub repositories, skill directories, industry reports, articles, links, or raw notes, then decide whether they are worth collecting into a personal skill library. Use when the user asks whether a skill mentioned in a GitHub repo or industry material should be collected, wants a concise Chinese evaluation card, or wants confirmed recommended skills appended to a Markdown skill library. Do not use to invent new skills from generic content or to build full executable skills unless explicitly requested.
---

# Agent Skill Collection Evaluator

Evaluate an existing Agent skill found in third-party material, judge whether it is worth collecting, and output a structured Chinese skill card.

## Typical Requests

- "评估这个 GitHub 仓库里面的 skill 是否值得收录"
- "评估这个行业咨询里面提到的 skill 是否值得收录"
- "看看这个链接里的 Agent skill 值不值得加入我的技能库"
- "把这个第三方 skill 评估后生成收录卡片"

## Workflow

1. Parse the source.
   - For pasted text, use only the provided text.
   - Identify the existing skill being discussed. It may be a GitHub skill folder, a prompt/workflow skill mentioned in an industry article, or a named third-party agent capability.
   - If the source is a collection of concrete reusable skills, workflows, rules, or templates organized as a package, evaluate it as a `Skill Package` instead of forcing it into a single-skill card.
   - Lock the evaluation target to the user-provided source. Do not switch to a related repository, adjacent spec, product architecture, or inferred mechanism unless the user explicitly asks to evaluate that different target.
   - For URLs or repositories, fetch or inspect enough source material to identify the skill goal, workflow, inputs, outputs, implementation method, maturity signals, and limitations.
   - Capture the most precise source URL available. For a GitHub skill inside a repository, use the exact skill directory or file URL, not the repository root.
   - If the material does not contain an identifiable existing skill, say that it cannot be evaluated as a skill, set `是否推荐收录` to `否`, and explain the missing evidence.
   - If the source is an agent product, framework, app, or platform rather than a reusable skill, do not recommend collection as a skill. You may mention related skill-like projects as background, but do not evaluate or recommend them as substitutes for the provided source.
   - If the source is too thin to support a collection judgment, say what is missing instead of inventing details.

2. Apply the collection gates before writing a positive recommendation.
   - Stay evidence-driven rather than optimistic or conservative by default. Do not force either `是` or `否` before checking the gates.
   - Recommend `是` when the gates pass: the source contains a concrete existing skill; the skill has clear inputs and outputs; the implementation is reusable by general-purpose AI agents such as Codex, Claude Code, or Cursor; the source includes enough operational detail; the skill is portable enough to collect.
   - Do not recommend collection merely because the project is interesting, popular, well engineered, adjacent to agents, or could inspire a future skill.
   - If a hard gate fails, still output the card, but keep unsupported fields as `未知` and set `是否推荐收录` to `否` with the failed gate as the reason.
   - If the source is promising but one or two non-critical details are missing, set `是否推荐收录` to `否，暂不收录` or ask for the missing evidence instead of treating the skill as definitively bad.
   - Do not reject a skill merely because it is simple, niche, unfamiliar, or lacks popularity signals; evaluate whether it is concrete, reusable, and operational.

3. Describe the skill under evaluation.
   - Prefer an action-oriented skill name.
   - Do not translate the skill name. Preserve the original source name, project name, product name, method name, or English phrase when one is provided.
   - Keep the skill positioning to one sentence.
   - Separate "适用场景" from "实现逻辑": the former is user pain and workflow fit; the latter is prompt/tool/API/workflow mechanics.
   - Write "实现逻辑" as reusable operating guidance when evidence allows: core steps, key constraints, tool/API calls, prompt structure, or acceptance checks. Avoid a vague one-sentence summary.
   - Preserve source-specific technical details when they matter, such as API names, repo modules, model types, CLI commands, or integration points.

4. Evaluate collection value.
   - For complex or borderline collection decisions, read `references/evaluation.md` before deciding.
   - Recommend `是` only when the user-provided source itself contains a concrete existing skill or explicitly points to one.
   - Recommend collection only when the existing skill is repeatable, actionable, and useful beyond one single source.
   - Use "否" when the material is mostly opinion, news without a concrete skill, a vague idea, or lacks enough implementation detail.
   - When the user asks for industry maturity, reputation, or cases and the current material is insufficient, search current sources and cite the evidence in the response.

5. Output the card in the required format.
   - Be concise and concrete.
   - Avoid motivational commentary, long explanations, and generic praise.
   - Use "未知" for fields that cannot be supported by the source.
   - When the user provides a link, still print the completed skill card in the chat first.
   - Include `来源地址` when a source URL or repository path is available.
   - In `是否推荐收录`, name the decisive pass/fail evidence rather than giving a general impression.
   - Use the single-skill format for one concrete workflow. Use the skill-package format only when the source itself is a package of multiple concrete reusable skills or workflows.

6. Ask before appending.
   - If the card says `是否推荐收录：是`, ask the user to confirm whether to write it to the skill library.
   - Do not append during the same response that first presents the card, even if the user originally asked to collect suitable skills.
   - Append only after the user explicitly confirms in a later message, such as "确认写入", "写入", "收录", or equivalent.

7. Append only after confirmation.
   - Default library path: `~/.agents/my_skills_library.md`.
   - If the user provides another target path, use that path.
   - Never overwrite the library.
   - Write each skill as an independent incrementing Markdown section.
   - Let the append script format the stored card as readable Markdown with headings, not as a flat list of field lines.
   - Do not include `是否推荐收录` in the stored Markdown section because every stored card is already recommended.
   - Convert the reason in `是否推荐收录` into a stored `收录价值` section so the library keeps the decision rationale.
   - Include `来源地址` in the stored Markdown section when available.
   - Use the bundled append script when modifying the library.

## Output Formats

### Single Skill

```markdown
🛠️ 技能名称：[在此填入技能名称]
来源地址：[原文、仓库、具体 skill 目录或文件的精确地址；无则写未知]
技能定位：[一句话说明该技能的核心功能，解决什么问题]
适用场景：[什么场景或痛点下适合使用这个技能]
输入：[该技能运行时需要什么输入，如特定的指令、数据或格式]
输出：[该技能运行完毕后，产出什么结果或格式]
实现逻辑：[它是怎么实现的；优先写成可复用的核心步骤 / 关键约束 / 调用的工具 API / Prompt 结构 / 验收检查]
是否推荐收录：[是/否，并说明一句话理由]
```

### Skill Package

```markdown
🧩 技能包名称：[在此填入技能包名称]
来源地址：[技能包仓库、目录或文档的精确地址；无则写未知]
技能包定位：[一句话说明这个技能包覆盖什么领域或生命周期]
收录价值：[为什么值得作为技能包收藏；如果不值得，说明决定性原因]
适用场景：[适合在哪些工作流或痛点下按需挑选其中的技能]
核心能力：[这个技能包提供的主要能力类型，不逐个展开所有子技能]
是否推荐收录：[是/否，并说明一句话理由；可写“是，作为 Skill Package 收录；不作为单个 Skill 收录”]
```

## Appending to the Library

After generating a card with `是否推荐收录：是`, first show the card to the user and ask whether to write it to the library. After explicit confirmation, save the exact card body to a temporary Markdown file and run:

```bash
python <SKILL_DIR>/scripts/append_skill_card.py --card-file <CARD.md>
```

To override the target library:

```bash
python <SKILL_DIR>/scripts/append_skill_card.py --card-file <CARD.md> --library <PATH>
```

The script creates the parent directory if needed, creates the file if missing, detects the highest existing `## N.` section number, and appends the next section. It formats the stored card as a readable Markdown section with subheadings, keeps `来源地址`, converts the recommendation reason into `收录价值`, omits `是否推荐收录`, and does not edit existing sections.
