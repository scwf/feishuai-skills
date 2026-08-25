---
name: youtube-to-bilingual-video
description: Turn one YouTube URL into a best-quality local source video, audited Chinese-English subtitles with Chinese above English, and a verified burned-in MP4. Use only when the user wants download, bilingual subtitles, and final rendered video together. Do not use for subtitle-only work, metadata-only scraping, dubbing or TTS, live streams, batches, or publishing uploads.
---

# YouTube To Bilingual Video

Orchestrate one end-to-end job by composing `youtube-scraper` and `generate-and-process-subtitles` through their public commands and structured outputs. Do not import or duplicate either dependency's internal logic.

## Preconditions

Resolve and read the current dependency `SKILL.md` files plus [atomic-skill-contracts.md](references/atomic-skill-contracts.md). Stop if either dependency, Python, `ffmpeg`, or `ffprobe` is unavailable.

Before download or transcription, record explicit values for both `semantic_split` and `optimize_with_description`. Ask only for choices the user has not already answered. The end-to-end request authorizes the requested media download; it does not authorize unrelated uploads or publishing.

Use one stable job directory. Preserve the first verified English SRT as an immutable baseline and keep derived artifacts in separate stage directories. Read [workflow.md](references/workflow.md) for layout, commands, evidence review, rendering, and recovery.

## State Machine

| Stage | Required input | Output state | Stop condition |
|---|---|---|---|
| Resolve | URL, title, video ID | stable job manifest | unsafe/locked path |
| Download | explicit final-video request | source media + successful sidecar | incoherent source |
| Transcribe | confirmed split choice | verified English pair + language-bound metadata | language mismatch or nested review |
| Optimize | confirmed optimize choice + context | candidate English pair | missing context |
| Audit | immutable baseline + candidate | reviewed English SRT + lexical audit | unresolved lexical change |
| Final English QC | exact reviewed SRT + seam state | QC exit `0` | any review item or stale approval |
| Translate | QC-cleared English | Chinese-on-top bilingual pair | translation/structure failure |
| Validate | bilingual pair + exact source metadata + media | deterministic validation report | mismatch or coverage gap |
| Render | validated subtitles + source | verified MP4 + report + QA frames | stream, duration, decode, or visual QA failure |
| Deliver | all successful states | absolute artifact paths + warnings | missing evidence |

A command timeout is not itself failure. Inspect process state, reports, partials, and completed artifacts, then resume from the latest valid stage.

## Hard Stops

- Exit `2` or `review_required` from semantic split, optimization audit, final English QC, or bilingual QC stops the pipeline.
- Bind source-language metadata by SHA-256 to the exact reviewed English SRT. Rebind only after every change has an auditable lineage and review record.
- Never translate or repair only the Chinese line to hide an English boundary defect. Fix the reviewed English source, rerun QC, then regenerate the aligned bilingual pair.
- Route confirmed missing speech to bounded source-language interval transcription before translation.
- Never render on structural-only confidence. Require source/bilingual parity, viewer-facing QC, media coverage, and current metadata.
- A silent source requires explicit acceptance before `--allow-silent`. Existing outputs require explicit replacement authorization and recoverable archival.

## Definition Of Done

Completion requires coherent source media and sidecar; immutable baseline; reviewed English audit and QC; exact language-bound metadata; validated Chinese-above-English SRT; final MP4 with expected audio/video streams, duration tolerance, and full decode success; and inspected QA frames at ordinary and repaired timestamps.

Report absolute paths for source, baseline, reviewed English, bilingual SRT, audits, QC, validation, final MP4, render report, and QA frames. List unresolved terminology or visual warnings instead of claiming completion.

## References

- [atomic-skill-contracts.md](references/atomic-skill-contracts.md): dependency command and structured handoff contracts.
- [workflow.md](references/workflow.md): stage directories, evidence review, validation, rendering, and recovery.
- [eval.md](references/eval.md): trigger, regression, safety, and completion evaluation.
