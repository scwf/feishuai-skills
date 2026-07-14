# Prompt Review

Apply this reference when an image-generation prompt is the review target or is evidence for conformance checking. Treat the prompt as a specification, not as evidence that the visual has rendered successfully.

## Prompt Gate

### 1. Contract Completeness

Require only choices that materially affect the result:

- Canvas orientation, aspect ratio, and viewing context.
- Topic and one complete core judgment.
- One dominant main visual.
- Layout zones, hierarchy, and reading order.
- Exact or bounded copy for titles, labels, metrics, and conclusions.
- Relevant color, typography, icon, and diagram-language constraints.
- Required attribution, footer, logo, or exclusions.
- Negative constraints that prevent unsupported facts, clutter, or illegible text.

Do not require a field merely because another template contains it.

### 2. Content-to-Visual Translation

Match the visual form to the logic: architecture for structure, flow for process, timeline for evolution, matrix for comparison, chart for quantitative evidence, flywheel for reinforcing cycles, and ecosystem map for multi-actor relationships.

Check that every zone has one argumentative role, major claims are assigned to visible regions, and the main visual carries the insight rather than decorating dense text.

### 3. Relationships and Mapping

Check that the prompt names connector direction and meaning, node or layer order, comparison dimensions, and one-to-one mappings. Color, shape, line, and position encodings must remain stable. Flag incompatible layouts or reading paths.

### 4. Text Inventory and Density

Estimate visible text by zone. Check that:

- The judgment-style title is short enough to dominate.
- Labels are shorter than explanatory copy.
- Repeated cards use comparable copy length and abstraction level.
- Exact text is limited to content that must survive rendering.
- The number of zones, cards, metrics, and footnotes fits the canvas.

Flag likely tiny text, crowded cards, long Chinese paragraphs, dense tables, and too many equally weighted modules as `Render risk`.

### 5. Evidence Fidelity

Check that every claim is traceable to supplied material or marked as a placeholder, reference-locked prompts add no outside facts, metrics belong to the claims they support, and names, units, terminology, and qualifiers are preserved.

Do not independently fact-check the prompt.

### 6. Instruction Quality

Separate content, layout, style, exact text, and negative constraints. Make priorities explicit when instructions compete. Replace vague adjectives with concrete visual behavior. Flag contradictions in palette, background, style, orientation, or footer rules.

Classify each prompt-specific finding as:

- `Prompt defect`: missing, conflicting, or structurally weak instructions that must change before generation.
- `Render risk`: coherent instructions that an image model may still execute unreliably.

## Prompt Patch Output

When the primary review target is the prompt, replace the common minimum-revision section with:

```md
## Prompt patch
- Retain:
- Replace:
- Add:
- Delete:
- Render risks that remain:
```

Provide a complete optimized prompt only when requested or when isolated patches would be harder to apply.

When the primary target is a rendered page and this reference is loaded only for prompt conformance, keep the common minimum page revision. Append a short prompt patch only for prompt-caused findings.

## Revalidation

After writing a prompt patch, rerun every Prompt Gate section affected by the changed instructions. After writing a complete optimized prompt, rerun all six sections. Do not finalize either output while any P0/P1 `Prompt defect` remains. Disclose remaining P2 defects and unavoidable `Render risk` separately.

## Prompt Anti-Patterns

- Treating desired style as proof of rendered quality.
- Rewriting reference-locked content with unsupported facts or altered terminology.
- Requiring every possible prompt field despite an unambiguous specification.
- Mixing prompt defects and renderer limitations into one warning.
- Depending on flawless rendering of dense tables, tiny labels, or long Chinese text.
