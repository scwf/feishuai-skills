---
name: generate-and-process-subtitles
description: Generate or process subtitle artifacts from local media, video URLs, SRT files, or Whisper word-timestamp JSON. Use for transcription, strict normalization, conservative ASR correction, translation, optional semantic re-segmentation, or viewer-facing subtitle QC. Do not use for dubbing, TTS, voice cloning, visual video analysis, or publishing.
---

# Generate And Process Subtitles

Create validated subtitle artifacts through one deterministic CLI. Keep model judgment limited to semantic boundaries, conservative text correction, and translation; scripts own parsing, timing, length, paths, publication, and structured results.

## Route The Request

| Input and intent | Mode | Read |
|---|---|---|
| Local media or non-YouTube media URL | `transcribe` | [transcribe.md](references/transcribe.md) |
| YouTube URL | confirmation gate, then `transcribe` | [transcribe.md](references/transcribe.md) |
| Existing SRT, formatting only | `normalize` | [output-contract.md](references/output-contract.md) |
| Existing SRT, clear ASR/name correction | `optimize` | [optimize.md](references/optimize.md) |
| Existing SRT, another language or bilingual output | `translate` | [translate.md](references/translate.md) |
| Whisper JSON with word timestamps, natural re-cut requested | `split` | [split.md](references/split.md) |
| Existing SRT, fragment/readability review | `qc` | [qc.md](references/qc.md) |

Resolve `{SKILL_ROOT}` to this directory and use the isolated Python described in [setup.md](references/setup.md). Run the CLI from any working directory:

```bash
{PYTHON} {SKILL_ROOT}/scripts/generate_and_process_subtitles.py <mode> ...
```

Check the current `--help` before relying on an option not shown in the relevant reference.

## YouTube Confirmation Gate

Before any command for a YouTube URL, resolve two independent choices unless the user already answered them explicitly:

1. Enable semantic split for natural re-segmentation?
2. After transcription, run conservative optimize using the video description as evidence?

Ask only for unanswered choices and wait. Neither silence nor a generic “extract subtitles” request selects either option. Semantic split uses ASR even when reusable human subtitles exist because seam repair requires word timestamps. Optimize remains a separate follow-up and runs only when confirmed and a current context artifact exists.

## Global Invariants

- Preserve source content and timing unless the selected mode explicitly changes text or segmentation. Never invent missing speech, terminology, or translations.
- Strictly validate SRT structure, positive non-overlapping timelines, configured length ceilings, and SRT/TXT consistency before publication.
- Publish final SRT/TXT as a transaction. Do not overwrite existing outputs unless the user authorizes `--replace-existing`; reject unsafe targets and locks.
- Keep final user-facing SRT/TXT in the requested output directory and process evidence under `_subtitle_work/`. Follow [output-contract.md](references/output-contract.md).
- Treat `review_required` and exit code `2` as a hard stop, not successful completion. Do not continue to optimize, translate, render, or deliver until the exact downstream subtitle passes the required review gate.
- A requested source language must be verified and bound to the exact emitted SRT metadata. Script validation, not Latin-script appearance, is authoritative.

## Finish

Return the structured command result and absolute final artifact paths. Report unresolved review items and evidence paths. Do not claim completion from green structural checks alone when viewer-facing QC or a required manual review remains open.

For Skill changes, read [eval.md](references/eval.md), run the real CLI contracts, and validate this package with the Skill validator. Tests must assert observable artifacts and failures rather than documentation wording or internal function names.
