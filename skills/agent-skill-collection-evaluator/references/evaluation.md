# Evaluation Rules

Use this reference when judging whether an existing third-party Agent skill is worth collecting.

## Decision Gates

Stay evidence-driven. Do not default to recommending or rejecting before checking the gates.

Recommend "是" when these gates pass:

1. The user-provided source contains a concrete existing skill or explicitly points to the exact skill.
2. The skill has clear inputs and outputs.
3. The implementation is reusable by general-purpose AI agents such as Codex, Claude Code, or Cursor, not just a product feature or architecture idea.
4. The source includes enough operational detail to guide reuse.
5. The skill is portable enough to collect without private runtime assumptions.

If a hard gate fails, recommend "否" and state the failed gate. If the source is promising but one or two non-critical details are missing, use "否，暂不收录" or ask for the missing evidence instead of treating the skill as definitively bad. Do not use "interesting", "popular", "agent-related", or "inspiring" as substitutes for passing evidence. Do not reject a skill merely because it is simple, niche, unfamiliar, or lacks popularity signals.

## Recommend "是"

- The workflow can be repeated across multiple tasks or sources.
- The skill has clear inputs and outputs.
- The implementation logic is concrete enough to guide general-purpose AI agents such as Codex, Claude Code, or Cursor.
- The skill reduces recurring research, writing, coding, analysis, scraping, or tool-operation effort.
- The material includes usable prompts, APIs, scripts, repo structure, command patterns, or operational steps.
- The source identifies a concrete skill, such as a GitHub skill folder, prompt workflow, agent tool workflow, or named capability.
- The user-provided source itself contains the concrete skill or explicitly points to the exact skill being evaluated.

## Recommend "否"

- The source is only news, commentary, or opinion without a reusable workflow.
- The idea is useful but too vague to execute.
- The source describes a one-off product feature that cannot be generalized into agent behavior.
- The repo or article lacks enough implementation detail and no extra research was requested.
- The skill would require unavailable private data, credentials, or production access.
- The material does not identify an existing skill; it only suggests a broad topic that would require inventing one.
- The provided source is an agent product, app, framework, or platform, but does not contain a concrete reusable skill to collect.
- A related repository, adjacent spec, or inferred skill-like mechanism exists, but the user did not explicitly ask to evaluate that different target.

## Evidence Discipline

- Do not overstate maturity from a single article.
- If using external reputation or case evidence, cite the source in the normal response.
- If evidence conflicts, report the uncertainty in one sentence.
- Mark unsupported fields as "未知" rather than filling them with generic guesses.

## Example: Multiple Candidates in One Repository

When the user provides a GitHub repository URL and the repository contains more than one skill-like target, classify the candidates before recommending one.

Remotion example:

- `packages/skills/skills/remotion/SKILL.md`: end-user tool/product skill. It helps general-purpose AI agents use Remotion to create or edit videos. This is usually the default priority because it is broadly reusable outside the Remotion repository.
- `.agents/skills` or `.claude/skills`: repository-maintenance workflow package. These directories usually help agents contribute to the source repository, such as adding CLI options, writing docs, managing issues, and adding renderer tests. Do not evaluate them by default; consider them only when the user asks for repo-contribution or workflow-design examples, or when the content is clearly for external end users.

Preferred response pattern:

"I found two skill-like candidates: A is an end-user Remotion skill for general AI agents, and B is a repository-contribution workflow package under `.agents/skills` or `.claude/skills`. By default I will evaluate A and ignore B unless you want repo-maintenance workflow examples."
