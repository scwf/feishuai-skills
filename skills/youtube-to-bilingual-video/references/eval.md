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

A punctuation- or case-only optimization may pass the lexical audit but still create a semantic orphan boundary, such as `Next` -> `next` after a preceding cue. The exact reviewed English SRT must therefore rerun QC after all optimization/manual changes and before translation; exit `2` blocks translation.

## Structural Failure Case

If optimize silently changes a cue timestamp or removes a cue, the audit must return exit code `1` and status `error`.

## Bilingual Cases

Pass:

```text
我有一个 Genie Agent 来协助门店运营。
I have a Genie Agent to help with store operations.
```

Fail when English is first, Chinese is absent, cues overlap, or numbering is non-sequential.

## Semantic Readability Cases

Pass: a legal `Yes.` classified as `ok_short`.

Fail: a chunk-seam `customers.` fragment, a hanging `our`, or a bilingual cue whose Chinese line is complete while the English line is a short fragment. Structural SRT validation is not sufficient.

## Completion Checks

- Run `python -m py_compile` on every bundled script.
- Run the entity-mutation, fluency-rewrite, and clean-punctuation audit fixtures.
- Run bilingual validation on passing and failing fixtures.
- Run semantic orphan QC on initial English, post-optimization final English, and bilingual fixtures; high-risk alerts at any stage block completion.
- Verify `transcribe --semantic-split` / `split` exit `2` when nested QC is `review_required`.
- Verify source cue/timing mismatches and material video coverage gaps fail validation.
- Verify coverage-gap issues route to source-language interval repair, not bilingual-only edits.
- Verify SRT-only validation reports `coverage_checked=false` and is not treated as render-ready.
- Verify report paths cannot alias any input and silent sources fail unless explicitly allowed.
- Verify a missing-audio render error asks for user acceptance instead of instructing `--allow-silent` immediately.
- Run console-output fixtures under a legacy Windows code page without forcing UTF-8 mode.
- Run the skill-creator `quick_validate.py` with UTF-8 mode enabled.
- On a real local sample, render a short or full video and verify that the report records video/audio streams, duration tolerance, decode success, and QA frames.
