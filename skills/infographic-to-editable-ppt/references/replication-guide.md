# Infographic-to-PPT Replication Guide

Use this reference for dense or visually fragile infographic recreation. Keep the main workflow in `SKILL.md` as the source of truth; this file adds decision tables and common fixes.

## Element Decision Table

| Element type | Preferred method | Avoid | Exception |
|---|---|---|---|
| Main title, subtitle, body, numbers, labels, conclusions | PPT text boxes | Rasterizing text, typos, broken phrases, under-8-pt text | Tiny decorative text may remain in a slice if disclosed |
| Cards, panels, borders, blocks, footer bars | PPT shapes | Whole-region screenshots | Complex texture backgrounds may be sliced |
| Simple arrows and connectors | PPT connectors / lines | Direction changes, over-simplifying paths | Special glow arrows may use SVG or slices |
| Loops, flows, flywheels | PPT curves / connectors / SVG / selective slices | Changing node order or arrow direction | Slice the path if native curves are unstable; keep node text editable |
| Axes, direction scales, braces, grouping lines | PPT lines / shapes | Reducing them to unrelated symbols | Special visual effects may use slices |
| Simple function icons | One consistent SVG family | Mixing icon sets or line weights | Use shape approximation only when no SVG fits |
| Core path icons | SVG / shape / original icon crop | Loose semantic substitution | Crop the original icon when exact matching matters |
| Illustrations, logos, product UI, photos, 3D objects | Image slices | Low-quality hand drawing or fake replacement | Overlay editable text when needed |
| Complex backgrounds, textures, glows, material effects | Image slices or restrained shape approximation | Default-template replacement | Use a few clean slices to keep quality |
| Tables, bars, stair-step lists, rankings | PPT shapes plus text boxes | Overflow, misalignment | Approximate visually if data cannot be inferred |

## Text Checks

- Use Microsoft YaHei for Chinese editable text unless the user asks otherwise.
- Keep readable editable text at least 8 pt; important body text should usually be at least 9 pt.
- Disable shrink-on-overflow. Use fixed sizing, wider text boxes, manual line breaks, line spacing, and padding adjustments.
- Preserve source terms, fixed phrases, labels, units, punctuation, quotation marks, numbering, and emphasis.
- Do not split fixed terms, short labels, or technical phrases across lines.
- For long body text or footers, compare line width rhythm with the source. If a line wraps too early, expand the object to the widest reasonable box whose visible text still stays inside the visual boundary.

## Relation Checks

- Verify every arrow's entry point, exit point, head position, curve, and direction.
- Verify every loop/flywheel node count, order, direction, and closed-path logic.
- Verify axes and trend arrows have the same direction and label placement as the source.
- Verify braces, dashed grouping lines, and summary connectors cover the same range as the source.
- Do not turn a one-sided brace into a pair of braces.
- If a relation path is visually central and hard to recreate, prefer SVG or a path-only slice over a low-quality native approximation.

## Icon and Slice Checks

- Keep icon matrix color, line weight, size, and style consistent.
- Do not recolor icons differently unless the source does so.
- Do not replace core icons with merely similar icons when the source icon carries specific meaning.
- Crop original icons when semantic or brand fidelity matters.
- Use transparent PNG slices when practical.
- Keep glow, shadow, and blur effects inside the crop with safe margins.
- Check slices for white edges, fuzzy compression, and mismatched resolution.
- Name assets clearly, such as `asset_center_visual.png`, `asset_core_icon_task.png`, or `asset_relation_path.svg`.

## Common Failures and Fixes

| Failure | Likely cause | Fix |
|---|---|---|
| Text layout drifts | Font mismatch, narrow text boxes, AutoFit shrinking | Use Microsoft YaHei, disable shrinking, widen boxes, tune line breaks |
| Text is too small | Forced source matching | Keep minimum size, rebalance layout instead |
| Future edits shrink text | Shrink-on-overflow enabled | Disable it and use fixed font sizes |
| Core icon meaning changes | Approximate icon replacement | Re-check source semantics; crop source icon if needed |
| Icon matrix looks inconsistent | Mixed icon sets or colors | Normalize color, stroke width, size, and style |
| Arrow direction is wrong | Entry/exit not checked | Trace each relation path before final preview |
| Curved arrow becomes a generic symbol | Used stock U-turn/cycle shape | Rebuild source curvature, endpoints, and head position |
| Relation paths are over-simplified | Native PPT shortcut | Use curves, SVG, or a relation-layer slice |
| Bracket relation changes | Added extra brace or paired brace | Match original count, side, opening, and range |
| Body wraps too early | Text box too narrow | Widen box first, then tune spacing if needed |
| Containers overflow | Bars/tables/tags not boundary-checked | Adjust width, padding, line breaks, and font size |
| Slice has white edges | Rough crop or tight glow boundary | Re-crop with transparent PNG and safe margin |
| Slide feels like a pasted collage | Too many slices | Convert main text and structure back to native PPT objects |

## Stop or Ask the User When

- The source image is too low-resolution or blurry to recover major text.
- OCR or manual inspection cannot recover the main title, section labels, body text, or key numbers.
- The requested output requires exact chart values but the values cannot be inferred from the image.
- Preview export cannot be completed with available local tools.
- A brand-critical logo, product UI, person, or copyrighted visual cannot be reproduced or sliced clearly.
- The source contains sensitive content and the next step would require uploading it to an external service.

## Final Report Details

When reporting the finished slide, explicitly mark:

- Editable text regions.
- Native PowerPoint shape/connector regions.
- SVG regions.
- Image-sliced regions.
- Text that remains image-based because it is tiny or embedded in complex visuals.
- Approximate chart data, approximate icon reconstruction, or sacrificed editability.
