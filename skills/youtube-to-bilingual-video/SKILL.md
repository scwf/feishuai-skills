---
name: youtube-to-bilingual-video
description: Orchestrate an end-to-end workflow that turns one YouTube URL into a best-quality local source video, audited Chinese-English subtitles with Chinese above English, and a verified burned-in MP4 by composing youtube-scraper and generate-and-process-subtitles. Use when the user explicitly wants the YouTube video downloaded, bilingual subtitles created, and a final subtitled video delivered. Do not use for subtitle-only requests, metadata-only scraping, dubbing or TTS, live streams, batch processing, or publishing uploads.
---

# YouTube To Bilingual Video

Compose existing atomic skills through their public command contracts. Do not copy their logic or import their internal Python modules.

## Required Dependencies

Before acting, resolve and read the current `SKILL.md` files for:

- `youtube-scraper` for explicit best-quality video download and its sidecar metadata.
- `generate-and-process-subtitles` for YouTube subtitle reuse or ASR, optional semantic splitting, conservative optimization, and translation.

Read [atomic-skill-contracts.md](references/atomic-skill-contracts.md) for the handoff contract. If either skill is unavailable, stop and report the missing dependency instead of silently replacing it with an ad hoc pipeline.

Also require `ffmpeg`, `ffprobe`, and Python 3 for rendering and deterministic validation.

## Confirmation Gate

For a YouTube URL, preserve the confirmation gate owned by `generate-and-process-subtitles`:

1. Confirm whether to enable semantic splitting.
2. Confirm whether to run description-reference-assisted conservative optimization.

Skip only choices the user has already answered. Do not download or transcribe until both choices are explicit. The request itself authorizes media download only when the user asks for a saved or final video.

## Default Workflow

Use one stable job directory. Keep immutable source files separate from derived artifacts. See [workflow.md](references/workflow.md) for names and failure recovery.

1. **Download source video.** Invoke `youtube-scraper` with its explicit video-download command and a stable output directory. Validate the media file and `.download.json` sidecar.
2. **Generate English subtitles.** Invoke `generate-and-process-subtitles transcribe` on the YouTube URL. Add `--semantic-split` only when confirmed. Preserve the first final SRT as the immutable transcription baseline before any optimization.
3. **Optimize only when confirmed.** Require the generated `_subtitle_work/context.txt`; otherwise stop after transcription unless the user supplies reference evidence. Write optimized output to a distinct directory.
4. **Audit optimization changes.** Run `scripts/audit_subtitle_changes.py` against baseline and optimized SRT. Punctuation, whitespace, and case-only changes may pass automatically. Any lexical insertion, deletion, or replacement is `review_required`.
5. **Resolve lexical changes.** Inspect each flagged cue against reliable evidence. Prefer, in order: visible text in exact timestamp frames, official title/description evidence, then audio. Apply only high-confidence corrections. Keep ambiguous items in a confirmation list. Never let an LLM rewrite an entity solely because a description contains a plausible alternative.
6. **Translate.** Invoke `generate-and-process-subtitles translate` with `--target-language zh-Hans` and the `bilingual-trans-first` format so Chinese is above English. Use the audited English SRT as the source.
7. **Validate bilingual SRT.** Run `scripts/validate_bilingual_srt.py`. Stop on invalid timing, overlap, missing language lines, non-sequential numbering, or a material mismatch with video duration.
8. **Render and verify.** Run `scripts/render_bilingual_video.py` with bottom-safe defaults. It must render to a temporary file, probe and fully decode the result, extract QA frames, and only then promote it to the requested output. Inspect at least one ordinary QA frame and every frame used to resolve a terminology change.
9. **Deliver.** Report the source video, audited English SRT, bilingual SRT, final MP4, audit JSON, validation JSON, render report, and QA frames.

## Terminology Review Gate

Treat optimization as correction, not rewriting.

- Exit code `0` from `audit_subtitle_changes.py`: only non-lexical changes were found; continue.
- Exit code `2`: lexical changes require evidence review; stop the automatic pipeline.
- Exit code `1`: structural or parsing failure; repair the inputs before continuing.

When a slide, UI, diagram, or lower third contains the disputed term at the cue timestamp, visual text is primary evidence. Extract a narrow frame around that timestamp rather than analyzing the whole video. Record the accepted term and evidence in the job notes or audit report.

## Rendering Defaults

Unless the user specifies a style:

- Chinese first, English second.
- Bottom-center alignment with `MarginV=8`.
- Font size `16` for balanced bilingual readability.
- White text, black outline, no opaque box.
- Adaptive CJK font selection with user override available.
- H.264 video and AAC audio in MP4.
- Prefer available NVENC; fall back to `libx264`.
- Never overwrite a validated output in place. Use `--replace-existing` only after creating a recoverable archived copy.

If subtitles overlap important on-screen content, render a short sample and adjust only the requested style variables before the full encode.

## Definition Of Done

Do not call the workflow complete until all are true:

- The downloaded source and sidecar exist and are coherent.
- The immutable transcription baseline is retained.
- Optimization changes were audited; every lexical change is resolved or explicitly left for user confirmation.
- The bilingual SRT passes deterministic validation and keeps Chinese above English.
- The final video has video and audio streams, duration is within tolerance, and a full decode scan returns no errors.
- QA frames visibly show readable subtitles near the bottom without clipping.
- The final response lists absolute artifact paths and any remaining warnings.

## References

- [atomic-skill-contracts.md](references/atomic-skill-contracts.md): public dependency handoffs.
- [workflow.md](references/workflow.md): directory layout, commands, evidence gates, and recovery.
- [eval.md](references/eval.md): trigger, boundary, regression, and completion checks.
