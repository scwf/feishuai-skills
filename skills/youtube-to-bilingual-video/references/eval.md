# Minimal Evaluation Contract

## Trigger Cases

Expected to select this skill:

- Explicit: "Download this YouTube video, make Chinese-English subtitles, and burn them into the final MP4."
- Implicit: "把这个 YouTube 链接做成一份中文在上、英文在下的成片。"
- Noisy: A long request that includes video download, bilingual subtitle creation, bottom placement, and final-video delivery.

Expected not to select this skill:

- "Only translate this SRT into Chinese." Use `generate-and-process-subtitles`.
- "List this channel's latest uploads." Use `youtube-scraper`.
- "Dub this video in Chinese." This workflow excludes dubbing and TTS.
- "Process these 30 videos." Batch orchestration is outside this skill.

## Confirmation Case

Given only a YouTube URL and an end-to-end request, the skill must ask or infer from explicit wording both semantic-split and optimization choices before starting transcription. One answered choice does not imply the other.

## Regression Case: Entity Mutation

Baseline cue:

```text
I have a Genie Agent to help with store operations.
```

Optimized cue:

```text
I have an Omnigent agent to help with store operations.
```

`audit_subtitle_changes.py` must return exit code `2`, status `review_required`, and a lexical-change item. The pipeline must not translate or render until evidence resolves the change.

A fluency-only rewrite such as `works good` -> `works well` is also `review_required`.

Numeric punctuation and measurement symbols are semantic tokens: `.5` -> `5` and removal of an unpaired digit-adjacent ASCII, curly, or Unicode prime/quote such as `5'`, `5”`, or `5′` must return `review_required`, not pass as punctuation-only edits. Two semantic suffixes such as `5' 6'` and abbreviated years such as `'25 '26` must not be paired as ordinary quotation. Balanced ordinary quotation around one number, such as `He answered "5".` -> `He answered 5.`, remains non-lexical punctuation only when the opening and closing quote exteriors are not digit-adjacent.

A punctuation- or case-only optimization may pass the lexical audit but still create a semantic orphan boundary, such as `Next` -> `next` after a preceding cue. The exact reviewed English SRT must therefore rerun QC after all optimization/manual changes and before translation; exit `2` blocks translation.

## Structural Failure Case

If optimize silently changes a cue timestamp or removes a cue, the audit must return exit code `1` and status `error`.

## Bilingual Cases

Pass:

```text
我有一个 Genie Agent 来协助门店运营。
I have a Genie Agent to help with store operations.
```

Fail when transcription metadata is missing or reports a non-English source, English is first, Chinese is absent, cues overlap, numbering is non-sequential, the trailing English differs from the audited source cue, or an extra English line appears before the exact source suffix. Reject `NaN`, infinity, negative tolerances, and negative gap limits with strict JSON output. A `你好 / Hola` pair cannot pass merely because `Hola` uses Latin letters.

## Semantic Readability Cases

Pass: a legal `Yes.` classified as `ok_short`.

Fail: a chunk-seam `customers.` fragment, a hanging `our`, a sub-second dependent tail such as `To be stored.`, a short adjacent duplicate suffix such as `Returned from here.`, an unfinished modifier before a long subtitle gap, an English line over 79 display characters, or a bilingual cue whose Chinese line is complete while the English line is a short fragment. Diagnostics include cue/time/neighbor/gap context. Structural SRT validation is not sufficient. Do not merge a 21-word unpunctuated cue into the following lowercase continuation to pass QC. Pass the negative control `And there you go.`.

## Completion Checks

- Run `python -m py_compile` on every bundled script.
- Run the entity-mutation, fluency-rewrite, and clean-punctuation audit fixtures.
- Run bilingual validation on passing and failing fixtures.
- Verify a non-English manual track/ASR language is rejected, the source-language metadata is handed to the validator, Windows `\\?\` report aliases cannot overwrite inputs, large reports stay on disk with bounded stdout, and report-write failures return structured `report_write_failure` JSON without tracebacks.
- Run semantic orphan QC on initial English, post-optimization final English, and bilingual fixtures; high-risk alerts at any stage block completion.
- Verify `transcribe --semantic-split` / `split` exit `2` when nested QC is `review_required`.
- Verify source cue/timing mismatches and material video coverage gaps fail validation.
- Verify coverage-gap issues route to source-language interval repair, not bilingual-only edits.
- Verify SRT-only validation reports `coverage_checked=false` and is not treated as render-ready.
- Verify report paths cannot alias any input and silent sources fail unless explicitly allowed.
- Verify the default-job resolver recovers a validated empty crash lock, rejects a complete manifest stored under a non-deterministic directory name, rejects duplicate deterministic claims, distinguishes case-only IDs, and returns `reason=output_locked` with `retryable=true` after its bounded lock wait.
- Verify automatic subtitle wrapping remains enabled, same-output renders are mutually exclusive across Windows case/device-prefix/trailing-dot/trailing-space aliases, path collisions use the same identity, and partial/archive names are collision-resistant.
- Verify a missing-audio render error asks for user acceptance instead of instructing `--allow-silent` immediately.
- Run console-output fixtures under a legacy Windows code page without forcing UTF-8 mode.
- Run the skill-creator `quick_validate.py` with UTF-8 mode enabled.
- On a real local sample, render a short or full video and verify that the report records video/audio streams, duration tolerance, decode success, and QA frames.
