---
name: infographic-to-editable-ppt
description: Recreate a static PNG/JPG infographic as a one-page editable PowerPoint slide. Use when the user asks to turn an infographic, screenshot, poster-like analysis graphic, chart-heavy visual, or image-based one-pager into an editable .pptx with native text boxes, shapes/connectors/SVG where possible, selective image slices for complex visuals, an exported preview image, and a short editability/approximation report. Do not use for creating a new infographic concept from scratch, making a non-editable image-only slide, building a multi-slide deck, editing an existing editable PPT, rebuilding charts from raw data, translating or rewriting copy, or creating a brand template.
---

# Infographic to Editable PPT

Recreate a source infographic as one editable PowerPoint page while preserving its visual hierarchy, reading logic, and major information.

Default strategy: editable information layer, native structural layer, SVG/shape simple icons, selective image slices for complex visuals.

## Definition of Done

Deliver all of these unless the user narrows the request:

1. A `.pptx` file with one slide whose page ratio matches the source image as closely as practical.
2. An exported preview image of the slide.
3. Optional `assets/` files for cropped image slices, SVGs, or source-derived visual assets.
4. A concise table explaining which regions are PPT text, shapes/connectors, SVG, or image slices, and where visual approximation was used.

Default outputs: save next to the source image unless the user specifies an output directory. Use `{source_stem}_editable.pptx`, `{source_stem}_preview.png`, and `{source_stem}_assets/`. Never overwrite existing files; append a version suffix such as `_v2` when needed.

## Required Workflow

1. Inspect the source image.
   Identify canvas ratio, major regions, title/subtitle/body/numbers/labels, relation diagrams, arrows, axes, brackets, icon groups, complex illustrations, logos, product UI, textures, and background effects.

2. Choose the slide canvas.
   Match the source aspect ratio. Use 16:9 widescreen only when the source is close to 16:9; otherwise set a custom size close to the image ratio.

3. Build the large structure first.
   Recreate background, title zone, panels/cards, footer or summary zone, major color blocks, borders, dividers, and shadows before adding details.

4. Rebuild major text as editable PPT text.
   Use native text boxes for titles, subtitles, section names, card titles, body paragraphs, quotes, conclusions, numbers, units, labels, annotations, and footers.

5. Rebuild structure and relationships.
   Use PowerPoint shapes, connectors, lines, curves, or SVG paths for cards, tables, bars, stair-step lists, rankings, axes, arrows, flow paths, loops, flywheels, braces, and grouping lines.

6. Handle icons and complex visuals.
   Use a single SVG icon family for simple icons when possible. For core icons that must match the source, prefer accurate SVG/shape recreation or crop the original icon. Use image slices for complex illustrations, photos, logos, product UI, 3D objects, textures, glassmorphism, glow, and hard-to-recreate relation paths.

7. Group and name objects.
   Organize objects by region such as `Header`, `Left Panel`, `Main Visual`, `Right Panel`, `Footer`, `Icons`, and `Decorations` so the slide remains editable.

8. Export and compare a preview.
   Render the slide to an image, compare it against the source, fix visible misses, and re-export. Do not finalize before preview verification.

Read [references/replication-guide.md](references/replication-guide.md) when the source contains dense diagrams, many arrows/brackets, icon matrices, complex visual effects, or when the first preview reveals text wrapping, relation-path, icon, or slicing problems.
Also read it for dense text, tables, rankings, small labels, many repeated cards, repeated icon grids, relation-heavy diagrams, or any preview mismatch.

## Hard Constraints

- Do not deliver the original full infographic as a single slide background.
- Do not rasterize major readable text.
- Use Microsoft YaHei (`微软雅黑`) for editable Chinese text unless the user specifies another font.
- Keep readable editable text at least 8 pt; keep important body text preferably at least 9 pt.
- Disable "shrink text on overflow" / AutoFit shrinking for editable text boxes. Fix overflow by adjusting text box width, line breaks, spacing, or layout.
- Preserve arrow direction, loop order, flywheel sequence, axes direction, bracket opening direction, grouping scope, and connector endpoints.
- Do not replace core icons, logos, official product UI, people, products, or branded visuals with loose semantic approximations.
- Use slices only for complex visual material, not for the main information layer.
- If a slice contains important editable text, cover or avoid the source text and overlay native PPT text.
- If chart data cannot be reverse-engineered, approximate visually and label it as visual approximation in the final report.

## Safety Boundaries

- Use local source-image slices and user-provided assets by default.
- Do not upload the source image to external OCR, vision, design, or asset services without explicit user approval.
- Do not download, invent, or replace brand logos, product UI, people, official icons, or copyrighted visuals without user approval.
- Mark retained logos, people, product UI, copyrighted visuals, and any sacrificed editability in the final report.

## Text Layout Rules

- Preserve source wording, emphasis, punctuation, units, numbering, and keyword highlighting.
- Use Microsoft YaHei for Chinese; use Aptos, Arial, or a close system font for English. For other languages or obvious brand fonts, use the closest available font and disclose the approximation.
- Avoid broken words, orphan single-character labels, compressed text, visible overflow, and overlapping text.
- Match the source line-breaking rhythm for long body text and footers. If a line wraps too early, first widen the text box within the visible boundary before reducing font size.
- A text box may be wider than its visual container when the visible glyphs still remain inside the intended boundary.

## Relationship Rules

- Curved progression arrows must keep the source curvature, start/end points, arrowhead location, and direction. Do not simplify them into generic U-turn, loop, or cycle symbols.
- Loop, cycle, flywheel, and flow diagrams must preserve node count, node order, arrow direction, and closed-path logic.
- If native PPT curves cannot reliably recreate a complex relation path, use an SVG path or crop only the relation layer, then overlay editable text.
- Single-sided braces and grouping lines must stay single-sided; do not invent paired braces or extra grouping marks.

## Quality Gate

Before final delivery, perform these verification steps:

- Export the final `.pptx` to the preview image path.
- Confirm the preview was generated from the final `.pptx`, not from the source image or an intermediate file.
- Inspect the `.pptx` object structure enough to confirm it contains editable text boxes and native shapes/connectors, not only one full-page image.
- Check the exported preview against the source for text overflow, major missing text, relation direction, icon mismatch, slice edges, and incoherent overlap.
- If preview export is unavailable, state that verification failed and do not present the slide as fully complete.

Then verify:

- The slide is not an image-only background.
- Major text is editable and uses the chosen font.
- Editable text is not smaller than the allowed threshold and does not rely on shrinking AutoFit.
- No obvious typos, missing text, duplicated ghost text, overflow, or incoherent overlap appears in the preview.
- Arrows, axes, braces, loops, flow paths, and direction labels match the source.
- Core icons keep the source semantics, style, color, line weight, and visual weight.
- Tables, bars, tags, callouts, and dense labels stay inside their visual parent regions.
- Slices are sharp, have no white edges, and do not unnecessarily replace editable content.
- Object grouping is understandable for later editing.

## Final Report Format

Start with a short artifact list:

- PPTX: `<path>`
- Preview: `<path>`
- Assets: `<path or none>`
- Known limitations: `<none or concise list>`

Use a concise table:

| Region / element | Method | Editable | Notes |
|---|---|---|---|
| Title area | PPT text / shape | Yes | Font, color, and placement notes |
| Main visual | Shape / SVG / slice | Mixed | Name sliced elements |
| Relationship diagram | Connector / SVG / slice | Mixed | Note path and text handling |
| Icons | SVG / shape / slice | Mixed | Note core-icon handling |
| Footer / notes | PPT text / shape | Yes | Note approximation if any |

Always mention:

- Any text preserved as image because it is embedded in complex visuals.
- Any visual quality preserved by sacrificing editability.
- Any chart or data element that is visually approximated.
