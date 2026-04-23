---
name: infographic-prompt-builder
description: A tool-neutral skill for generating high-quality Chinese insight infographic image prompts. Use it to turn either a minimal topic or user-provided reference materials into a researched, structured, executive-readable infographic prompt for product strategy, Data & AI analysis, technical architecture, AI model briefs, benchmark explainers, industry insights, and product deep dives.
---

# Infographic Prompt Builder

## Purpose

Generate the final image-generation prompt for a Chinese insight infographic.

Do not jump directly from topic to prompt. First perform research extraction, identify the core insight, design the infographic logic, then write the final prompt.

## Supported Input Modes

### Mode 1: Minimal Topic Input

Use when the user only provides a topic, product name, event, or one sentence.

Examples:

- “帮我做一张 Kimi K2.6 的洞察信息图提示词”
- “生成一张关于 Agent Runtime 的信息图提示词”
- “做一个 NVIDIA GTC 主题的信息图”

Rules:

- First infer a likely angle and information gaps. Do not ask a clarifying question unless the missing choice would materially change the infographic thesis or factual basis.
- If external research is available and allowed by the user/environment, gather reliable facts before writing the prompt.
- If external research is not available or not allowed, do not invent facts. Output a prompt framework with clear placeholders or ask the user to provide reference material.
- Before the final prompt, summarize assumptions and missing facts.

### Mode 2: Reference-Locked Input

Use when the user provides reference materials, notes, article excerpts, transcripts, benchmark data, screenshots, or internal analysis.

Rules:

- Strictly use only the user-provided materials and files.
- Do not search the web, add third-party facts, or import outside claims.
- If a needed fact is missing, mark it as a gap instead of filling it.
- Keep the final infographic faithful to the provided source while still sharpening the insight.

## Required Execution Flow

1. Detect input mode.
   Decide whether this is Minimal Topic Input or Reference-Locked Input. State the mode briefly when useful.

2. Run research extraction.
   Extract facts, claims, data points, mechanisms, actors, product modules, timelines, comparisons, and source constraints. Use [references/research-lens.md](references/research-lens.md) for the Data & AI product/technical lens.

3. Find the one-page core judgment.
   Answer: “If the reader only scans for 5 seconds, what conclusion should remain?” Compress the answer into one clear sentence.

4. Separate common capability from unique insight.
   Identify what is generic industry capability and what is truly distinctive: architecture, workflow, runtime mechanism, business model, ecosystem strategy, cost structure, benchmark implication, or operational promise.

5. Ask or choose visual style.
   Offer the style selector from [references/style-options.md](references/style-options.md) only when style is a meaningful user-facing choice. If the user wants a direct result, default to “Light Cool Consulting”.

6. Design the infographic.
   Use “主图 + 辅图 + 证据图/小图 + 结论框”. Every infographic must have at least one real main graphic: architecture diagram, flywheel, timeline, benchmark chart, system flow, stack diagram, old-vs-new comparison, or ecosystem map.

7. Write the final image prompt.
   Use zone-based structure: canvas, style, topic, one-sentence judgment, layout zones, graphic type per zone, exact text, footer, and negative constraints. See [references/prompt-recipes.md](references/prompt-recipes.md).

8. Run the quality gate.
   Check: one main judgment, one strong visual hook, clear hierarchy, no text-only card wall, faithful facts, readable Chinese, and a memorable bottom insight.

## Output Format

Use this output order by default:

1. Research Extraction Summary
2. Core Judgment
3. Visual Strategy
4. Style Choice
5. Final Image Prompt
6. Quality Checklist

If the user asks for only the final prompt, still do the internal extraction first, then output only the final prompt.

## House Rules

- Default canvas: vertical 9:16, 1080x1920px or 2K.
- Default footer: `Data & AI 洞察小分队`.
- Default style: light color system, clean consulting/research brief.
- Avoid deep/dark style unless the user chooses it.
- Prefer precise diagrams over decorative cards.
- Keep Chinese copy short enough for image rendering.
- Use English technical terms only when they improve precision.
- Do not include logo, watermark, cartoon style, heavy 3D, dense paragraphs, garbled Chinese, or unsupported facts.

## References

- [references/research-lens.md](references/research-lens.md): what to extract from a Data & AI product/technical perspective.
- [references/style-options.md](references/style-options.md): selectable visual styles and palettes.
- [references/prompt-recipes.md](references/prompt-recipes.md): prompt structures for different infographic types.
- [references/examples-index.md](references/examples-index.md): how to use bundled examples; read only when the user asks for visual reference matching or when a style/structure example is needed.
- [references/source-guide.md](references/source-guide.md): original Chinese production manual; read only when the core workflow is insufficient.
- [references/prompt-kimi-2.6.txt](references/prompt-kimi-2.6.txt): full historical prompt example; style and structure reference only, not a fact source.
- [references/prompt-gtc-2026.txt](references/prompt-gtc-2026.txt): full historical prompt example; style and structure reference only, not a fact source.
