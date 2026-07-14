---
name: slide-infographic-reviewer
description: Review an existing one-page PPT slide, infographic, image-generation prompt, or text/Markdown layout draft and return prioritized evidence-based findings plus a minimum revision or prompt patch. Use for single-page presentation visuals when the user asks to review, critique, diagnose, or optimize the page or its generation prompt for thesis clarity, structure, relationships, evidence, hierarchy, and audience comprehension. Do not use for UI screenshots, general documents, whole-deck narrative review, creating a page from scratch, editing source artifacts, pixel-perfect reproduction, or factual verification.
---

# Slide Infographic Reviewer

Review one page as a communication system. Determine whether it makes one defensible point, organizes evidence around that point, and gives the audience a clear path through the content.

Keep this skill review-only. Deliver diagnosis, replacement copy, layout instructions, or prompt patches. Do not edit the source artifact, create the visual, or perform factual verification; hand those tasks to an appropriate downstream capability.

## Route by Review Target

First identify the single artifact the user wants reviewed. The review target determines the primary mode, output, and completion criteria; all other supplied materials are evidence.

Choose one primary mode from the target:

- `Prompt`: an image-generation prompt specifies the intended one-page visual.
- `Structural`: a text or Markdown draft specifies content and layout, but no final pixels are available.
- `Rendered`: a complete image, screenshot of the entire page, or rendered PPT/PDF page shows the final pixels.

Apply these deterministic rules:

1. Follow an explicit user target even when other artifact types are supplied.
2. If the target is final page pixels, use `Rendered`. Treat its prompt and content drafts as evidence; add prompt-conformance checking when the prompt is available.
3. If the target is an image-generation prompt, use `Prompt`. Treat generated images and content drafts as evidence of likely or prior behavior; do not switch the primary output to page redesign.
4. If the target is a content/layout draft, use `Structural`. Treat source material and visual examples as evidence.
5. If the user does not name a target, infer it in this priority order: final page pixels, image-generation prompt, then content/layout draft.
6. If the user explicitly requests multiple targets, run a separate review for each target with its own mode and primary output.
7. If a target PPT/PDF cannot be rendered, use `Structural` and mark visual execution `Not verified`.

State the target and selected mode near the start. Do not create another mode for combined inputs.

## Load Only the Needed References

- Always read [references/common-review.md](references/common-review.md).
- For `Prompt`, also read [references/prompt-review.md](references/prompt-review.md).
- For `Prompt` with rendered-image evidence, also read [references/rendered-review.md](references/rendered-review.md) for visible-result inspection and prompt-versus-render attribution; keep `Prompt` as the primary mode.
- For `Rendered`, also read [references/rendered-review.md](references/rendered-review.md).
- For `Rendered` with prompt evidence, also read [references/prompt-review.md](references/prompt-review.md) for conformance checking; keep `Rendered` as the primary mode.
- For `Structural`, do not load a mode-specific reference.

## Establish the Evidence Boundary

- Inspect the complete target artifact before judging it.
- For PPTX or PDF, prefer a rendered page plus extractable text or object structure when available.
- Treat supplied sources as the factual boundary. Flag unsupported claims, but do not browse or verify them.
- In `Prompt` and `Structural`, do not claim that the target's visual execution has been observed unless rendered evidence is supplied. When rendered evidence is available, describe only what is visible in that evidence and use it for attribution; do not turn it into the primary review target.
- If the target page in a multi-page file is ambiguous, infer it only when context is reliable; otherwise ask which page to review.

## Execute the Review

1. Reconstruct the page contract.
   Identify the question answered, core judgment, larger argument when known, and one audience takeaway. If the judgment is not recoverable, report that rather than inventing one.
2. Apply the common review.
   Test thesis, page pattern, information types, relationship semantics, evidence ownership, mapping, and content placement in the order defined by `common-review.md`.
3. Apply the mode-specific review.
   For prompts, test the generation specification and render risks. For rendered pages, test actual hierarchy, legibility, scan path, and prompt conformance when a prompt is supplied.
4. Prioritize root causes.
   Apply the severity, finding format, and root-cause rules in `common-review.md`.
5. Propose the minimum effective revision.
   Preserve what works. Recommend the smallest content, structure, placement, or instruction changes that restore the page contract.
6. Validate before delivery.
   Run the Definition of Done below. Fix the review before returning it if any required check fails.

## Match the Output to the Target

Follow the compact output contract in `common-review.md`.

- `Prompt` target: output prompt findings and a prompt patch. Provide a complete optimized prompt only when requested or when isolated patches would be harder to apply.
- `Structural` target: output structural findings and a minimum content/layout revision.
- `Rendered` target: output visible-page findings and a minimum page revision. When prompt conformance reveals a prompt-caused issue, append a short prompt patch without replacing the page revision.

Add a full diagnostic table only for a complex target or when requested. Add a three-sentence speaker path only when presentation delivery is relevant or requested.

## Definition of Done

Do not finalize until all applicable checks pass:

- The review target, mode, and evidence basis are explicit.
- The page contract is recovered or its absence is the primary finding.
- Every reported issue includes Evidence, Impact, and a concrete Fix.
- Observed evidence is separated from inferred intent.
- Unobservable visual claims are marked `Not verified`, not scored as failures.
- Recommendations address root causes and preserve effective existing elements.
- No unsupported facts, silent claim rewrites, or unrequested artifact edits are introduced.
- The output follows the compact default unless extra detail is justified.
- If a prompt patch is produced, rerun every Prompt Gate section affected by the patch. If a complete optimized prompt is produced, rerun all six sections. Do not finalize while any P0/P1 prompt defect remains; disclose remaining P2 defects and Render risks.

## Output Rules

- Respond in the user's language unless requested otherwise.
- Lead with the verdict and the top one to three issues.
- Refer to exact regions such as `title`, `left architecture`, or `bottom conclusion`.
- Prefer replacement copy and relocation instructions over vague advice.
- Label predicted generation problems as `Render risk`, not observed visual defects.
- Keep the review decision-oriented and concise.
