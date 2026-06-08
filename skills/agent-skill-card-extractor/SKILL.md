---
name: agent-skill-card-extractor
description: Turn articles, links, GitHub repositories, product notes, or raw text into concise Chinese Agent skill cards. Use when the user wants to filter daily AI/agent information, evaluate whether a workflow or project is worth collecting as an Agent skill, or append recommended skill cards to a personal Markdown skill library. Do not use for building full executable skills unless the user explicitly asks for implementation.
---

# Agent Skill Card Extractor

Extract the smallest useful Agent skill from a source material, judge whether it is worth collecting, and output a structured Chinese skill card.

## Typical Requests

- "把这篇文章提炼成 Agent 技能卡片"
- "看看这个 GitHub 项目适不适合收录成一个技能"
- "从这些链接里筛选值得加入技能库的 Agent 技能"
- "提炼并追加到我的 my_skills_library.md"

## Workflow

1. Parse the source.
   - For pasted text, use only the provided text.
   - For URLs or repositories, fetch or inspect enough source material to identify the project goal, workflow, inputs, outputs, implementation method, maturity signals, and limitations.
   - If the source is too thin to support a judgment, say what is missing instead of inventing details.

2. Extract the skill.
   - Prefer an action-oriented skill name.
   - Keep the skill positioning to one sentence.
   - Separate "适用场景" from "实现逻辑": the former is user pain and workflow fit; the latter is prompt/tool/API/workflow mechanics.
   - Preserve source-specific technical details when they matter, such as API names, repo modules, model types, CLI commands, or integration points.

3. Evaluate collection value.
   - Recommend collection only when the skill is repeatable, actionable, and useful beyond one single article.
   - Use "否" when the material is mostly opinion, news without reusable workflow, a vague idea, or lacks enough implementation detail.
   - When the user asks for industry maturity, reputation, or cases and the current material is insufficient, search current sources and cite the evidence in the response.

4. Output the card in the required format.
   - Be concise and concrete.
   - Avoid motivational commentary, long explanations, and generic praise.
   - Use "未知" for fields that cannot be supported by the source.

5. Append only when recommended and requested.
   - Default library path: `D:\PARA\areas\01.GenAI\02.Agent\skills\my_skills_library.md`.
   - If the user provides another target path, use that path.
   - Never overwrite the library.
   - Write each skill as an independent incrementing Markdown section.
   - Use the bundled append script when modifying the library.

## Output Format

```markdown
🛠️ 技能名称：[在此填入技能名称]
技能定位：[一句话说明该技能的核心功能，解决什么问题]
适用场景：[什么场景或痛点下适合使用这个技能]
输入：[该技能运行时需要什么输入，如特定的指令、数据或格式]
输出：[该技能运行完毕后，产出什么结果或格式]
实现逻辑：[它是怎么实现的，如：核心 Prompt 结构 / 调用的工具 API / 工作流简述]
是否推荐收录：[是/否，并说明一句话理由]
```

## Appending to the Library

After generating a card with `是否推荐收录：是`, save the exact card body to a temporary Markdown file and run:

```bash
python <SKILL_DIR>/scripts/append_skill_card.py --card-file <CARD.md>
```

To override the target library:

```bash
python <SKILL_DIR>/scripts/append_skill_card.py --card-file <CARD.md> --library <PATH>
```

The script creates the parent directory if needed, creates the file if missing, detects the highest existing `## N.` section number, and appends the next section. It does not edit existing sections.
