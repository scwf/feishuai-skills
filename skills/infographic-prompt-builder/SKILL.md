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

2. Confirm color system before starting.
   If the user has not already specified a color system, ask one concise preflight question before research extraction or design work:
   “请先确认信息图配色体系：默认用经典商务红黑灰（主色 #C7000B，严格限制红/黑/白/灰），可以吗？”
   Do not proceed to research extraction, design work, or final prompt generation until the color system is confirmed.

3. Run research extraction.
   Extract facts, claims, data points, mechanisms, actors, product modules, timelines, comparisons, and source constraints. Use [references/research-lens.md](references/research-lens.md) for the Data & AI product/technical lens.

4. Find the one-page core judgment.
   Answer: “If the reader only scans for 5 seconds, what conclusion should remain?” Compress the answer into one clear sentence.

5. Separate common capability from unique insight.
   Identify what is generic industry capability and what is truly distinctive: architecture, workflow, runtime mechanism, business model, ecosystem strategy, cost structure, benchmark implication, or operational promise.

6. Ask or choose canvas orientation.
   Offer the user a required orientation choice before writing the final prompt unless they already specified it:
   - Vertical infographic: 9:16, recommended 1080x1920px. Use for poster-like tree, stack, timeline, deep-dive, or mobile/social sharing formats.
   - Horizontal PPT infographic: 16:9, recommended 1920x1080px. Use for one-page slide, board deck, presentation, side-by-side comparison, system landscape, or wide architecture map formats.
   If the user wants a direct result and has not specified orientation, ask one concise question: “这张信息图要做竖版 9:16，还是横版 16:9 PPT 比例？” Do not write the final image prompt until the orientation is known.

7. Ask or choose visual style.
   Offer the style selector from [references/style-options.md](references/style-options.md) only when style is a meaningful user-facing choice. Keep the color system separate from layout style: the default palette remains Classic Business Red-Black-Gray even when the layout style is consulting, research-card, or technical.

8. Prepare content confirmation table.
   Before designing the final infographic prompt, present a concise content-only confirmation table and ask the user whether any content needs adjustment. Do not repeat already confirmed execution parameters such as color system, canvas ratio, or visual style.
   The table must contain exactly these rows:
   - 核心主题
   - 一句话观点
   - 信息图主线
   - 关键事实和依据
   - 洞察观点
   - 关键术语
   Do not write the final image prompt until the content table is confirmed.

9. Design the infographic.
   Use “主图 + 辅图 + 证据图/小图 + 结论框”. Every infographic must have at least one real main graphic: architecture diagram, flywheel, timeline, benchmark chart, system flow, stack diagram, old-vs-new comparison, or ecosystem map.
   Match the layout to the chosen canvas:
   - Vertical 9:16: prioritize top-to-bottom reading, layered stacks, tree structures, vertical timelines, or stacked proof blocks.
   - Horizontal 16:9 PPT: prioritize left-to-right reading, wide architecture maps, landscape system flows, comparison matrices, timeline bands, or central main diagram with side evidence panels.

10. Write the final image prompt.
   Use zone-based structure: canvas, style, topic, one-sentence judgment, layout zones, graphic type per zone, exact text, footer, and negative constraints. See [references/prompt-recipes.md](references/prompt-recipes.md). The first line must explicitly state the chosen orientation and aspect ratio.

11. Run the quality gate.
   Check: one main judgment, one strong visual hook, clear hierarchy, no text-only card wall, faithful facts, readable Chinese, and a memorable bottom insight.

## Output Format

Use this output order by default:

1. Research Extraction Summary
2. Core Judgment
3. Canvas Orientation
4. Visual Strategy
5. Color System & Style Choice
6. Content Confirmation Table
7. Final Image Prompt
8. Quality Checklist

If the user asks for only the final prompt, still complete the mandatory color-system confirmation and content confirmation first. After confirmation, output only the final prompt.

## House Rules

- Canvas must be explicitly chosen before the final prompt: vertical 9:16 or horizontal 16:9 PPT ratio.
- Default canvas only after the user asks to skip choices: vertical 9:16, recommended 1080x1920px.
- Horizontal PPT canvas: 16:9, recommended 1920x1080px.
- Vertical default footer: `Data & AI 洞察小分队`.
- Horizontal PPT pages must not include `Data & AI 洞察小分队`; use no footer signature unless the user explicitly asks for one.
- Default color system: Classic Business Red-Black-Gray.
  - Theme: “经典商务红黑灰”, with strict color boundaries. Avoid colors outside red, black, white, and gray unless the user explicitly approves.
  - Primary accent: `#C7000B` (PANTONE 185C, RGB 199/0/11) for titles, key emphasis, core buttons, process lines, arrows, and critical indicators.
  - Background/base: pure white `#FFFFFF`; light gray `#F5F5F5` for card or panel backgrounds; medium gray `#E0E0E0` for dividers and subtle borders.
  - Text/contrast: deep black `#1A1A1A` or `#333333` for body text. Emphasized body points, numbers, and metrics should use bold black or bold red.
- Default style: light, clean consulting/research brief using the Classic Business Red-Black-Gray palette.
- Avoid deep/dark style unless the user chooses it.
- Confirm the color system before research extraction, design work, or final prompt generation unless the user already chose one.
- Confirm content before final prompt generation with a concise table containing only: 核心主题、一句话观点、信息图主线、关键事实和依据、洞察观点、关键术语.
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
- [references/prompt-horizontal-ppt-example.txt](references/prompt-horizontal-ppt-example.txt): horizontal 16:9 PPT-ratio prompt skeleton; use when the user chooses horizontal layout.
- [references/prompt-kimi-2.6.txt](references/prompt-kimi-2.6.txt): full historical prompt example; style and structure reference only, not a fact source.
- [references/prompt-gtc-2026.txt](references/prompt-gtc-2026.txt): full historical prompt example; style and structure reference only, not a fact source.
