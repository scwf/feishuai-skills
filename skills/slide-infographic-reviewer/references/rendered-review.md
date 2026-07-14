# Rendered Review

Apply this reference when final page pixels are available as either the review target or supporting evidence.

## Actual Visual Execution

Check:

- The core judgment or main proof has the greatest visual weight.
- Alignment, spacing, repeated sizes, and grouping are consistent.
- Whitespace separates logical groups.
- Typography is readable in the likely presentation or viewing context.
- Accent color communicates meaning rather than decoration.
- Repeated cards, icons, lines, and shapes use consistent visual grammar.
- Borders, shadows, colors, and components do not compete with the message.
- No clipping, overlap, broken text, illegible labels, or incoherent connector endpoints are visible.

Do not impose a palette, font, or house style unless the user, artifact, or brand guide establishes it.

## Audience Scan Test

Within 5-10 seconds, identify:

1. The topic.
2. The main judgment.
3. The first proof or visual anchor.

Flag a page that requires reading all text before the point becomes clear. Identify low-priority content that can be weakened or removed.

## Speaker Path

Apply only when the page is intended for spoken presentation or the user asks for delivery guidance.

Reconstruct:

1. Opening: state the page's position.
2. Development: explain the main structure or proof.
3. Landing: return to the judgment or implication.

Flag layouts that force the speaker to jump between distant regions, explain the layout before its meaning, or delay the conclusion.

## Prompt Conformance

Apply only when the generation prompt is also supplied. Keep the primary mode `Rendered`.

Compare intended and actual:

- Core judgment and title wording.
- Zone hierarchy and reading order.
- Main visual type and relationship direction.
- Required labels, metrics, terminology, and qualifiers.
- Palette, style, icon language, footer, and negative constraints.

Classify a mismatch as:

- `Prompt-caused`: the prompt was ambiguous, conflicting, or overloaded.
- `Render-caused`: the prompt was clear but the generated visual did not follow it.

Do not turn prompt conformance into another review mode.

## Rendered Evidence for a Prompt Target

Apply when the prompt is the review target and a generated image is supplied as evidence. Keep the primary mode and output `Prompt`.

1. Identify the visible symptom in the rendered image using the actual-execution and audience-scan checks above.
2. Locate the prompt instruction that should have governed that symptom.
3. Classify the evidence:
   - `Prompt-caused`: the instruction is missing, ambiguous, conflicting, or overloaded. Fix the prompt.
   - `Render-caused`: the instruction is clear and feasible, but the image does not follow it. Report the render risk; do not rewrite a sound instruction solely to chase one failed rendering.
   - `Indeterminate`: the available evidence cannot distinguish the two. State the uncertainty and avoid a confident prompt rewrite.
4. Use the rendered image to support prompt findings, not to replace the prompt review with a page-redesign output.

## Rendered Anti-Patterns

- Claiming the page is clear because all requested elements are present.
- Treating decorative consistency as evidence of argumentative coherence.
- Reporting intended relationships instead of the connectors actually visible.
- Marking a prompt requirement as satisfied when its text is present but unreadable.
- Recommending wholesale redesign when a smaller hierarchy or mapping fix is enough.
