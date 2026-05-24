# Prompt Recipes

## Universal Final Prompt Structure

```text
Create a [vertical 9:16 / horizontal 16:9 PPT-ratio] Chinese insight infographic, [vertical: 1080x1920px / horizontal PPT: 1920x1080px].

Overall style:
[chosen style name]
[background, color palette, typography, grid, mood]
All Chinese and English text must be sharp, fully readable, and not garbled.

Topic:
[topic]

One-sentence judgment:
[single conclusion]

Target reader:
[Data & AI product managers / technical leads / technical architects / executives]

Canvas orientation:
[Vertical 9:16: poster-like top-to-bottom layout / Horizontal 16:9 PPT: slide-like left-to-right landscape layout]

Layout zones:
1. Header zone: [height %, role]
2. Thesis/spec zone: [height %, role]
3. Main visual zone: [height %, graphic type]
4. Supporting evidence/comparison zone: [height %, graphic type]
5. Insight conclusion zone: [height %, role]
6. Footer zone: [height %, role]

Zone details:
[For each zone, specify exact text, hierarchy, icons, arrows, chart values, labels, and colors.]

Footer:
[Vertical 9:16 only] Left: Data & AI 洞察小分队
[Vertical 9:16 only] Right: [topic/date if applicable]
[Horizontal 16:9 PPT] No footer signature. Do not include Data & AI 洞察小分队. Put date/source metadata in the top header only if needed.

Negative constraints:
No logo, no watermark, no cartoon, no heavy 3D, no neon cyberpunk unless selected,
no dense paragraphs, no overlapping text, no garbled Chinese, no unsupported facts,
no generic text-card wall without a main diagram.
```

## Canvas Orientation Patterns

Use one of these before writing the final image prompt.

### Vertical 9:16

Best for poster-style insight graphics, mobile/social sharing, tree structures, stacked architecture, vertical timelines, or product deep dives.

Opening line:

```text
Create a vertical 9:16 Chinese insight infographic poster, 1080x1920px.
```

Layout pattern:

- Header and thesis at the top.
- Main visual in the middle, occupying the largest vertical zone.
- Supporting evidence below or around the main visual.
- Bottom insight conclusion and footer.

### Horizontal 16:9 PPT

Best for one-page presentation slides, executive decks, board updates, landscape architecture maps, side-by-side comparisons, wide timelines, or system flows.

Opening line:

```text
Create a horizontal 16:9 PPT-ratio Chinese insight infographic slide, 1920x1080px.
```

Layout pattern:

- Header strip across the top.
- Main visual as a wide central landscape diagram.
- Supporting evidence in left/right side panels or a bottom proof band.
- Bottom-right or bottom-band insight conclusion. No footer signature; if metadata is needed, place it as small header text.

## Model / Benchmark Brief

Use when the material includes model specs, benchmark scores, pricing, performance, or launch claims.

Zones:

- Header: model/event name, date, one-line capability thesis.
- Spec strip: 3 badges with core facts.
- Capability columns: 3 capability clusters.
- Main evidence: horizontal benchmark bars or metric comparison.
- Levers: cost/business lever + technical mechanism.
- Insight block: why this matters beyond scores.

Judgment pattern:

```text
[Model] 的优势不是单点刷榜，而是把 [A]、[B]、[C] 做成一个整体。
真正竞争力不只来自模型本体，也来自 [runtime/system/engineering mechanism]。
```

## Product Strategy

Use when explaining a company product line, platform ecosystem, or strategic shift.

Zones:

- Header: strategy title and subtitle.
- Thesis strip: one large strategic statement.
- Pillars: 3 product/capability pillars.
- Main visual: layered stack, funnel, product system, or ecosystem map.
- Flywheel: first-party practice -> platform abstraction -> ecosystem expansion -> feedback.
- Bottom conclusion: strategic implication.

Judgment pattern:

```text
[Company] 不是做互不相干的单品，而是在打造 [first-party practice] -> [platform abstraction] -> [ecosystem expansion] -> [feedback] 的闭环。
```

## Single Product Deep Dive

Use when explaining a runtime, architecture, security design, tool system, or production product.

Zones:

- Header: product name and production-facing claim.
- Main architecture: layers and flows.
- Old vs new: why this differs from common practice.
- Evidence: safety, latency, cost, reliability, or workflow proof.
- Bottom conclusion: unique mechanism and buying rationale.

Judgment pattern:

```text
[Product] 的真正独特性，不在于也有 [generic capabilities]，而在于把 [unique mechanism] 抽象成 [named structure]。
企业买的不是 [capability itself]，而是 [operational promise]。
```

## Mechanism / Agent System

Use when explaining loops, memory, skills, tools, long-running agents, or multi-agent systems.

Zones:

- Header: system name and one-sentence positioning.
- Main loop: user task -> execution -> record -> skill/memory generation -> reuse -> improvement.
- Mechanism cards: 3-4 enabling mechanisms.
- Comparison: ordinary agent vs target system.
- Bottom conclusion: why repeated use compounds capability.

Judgment pattern:

```text
[System] 的价值主张，不是“更会调用工具”，而是“能把做过的事逐渐变成自己的一部分”。
竞争力不在单次输出质量，而在长期使用中的复利效应。
```
