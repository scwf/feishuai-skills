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

Use one stable job directory. When the user does not specify one, run `scripts/resolve_job_dir.py --root <cwd> --title <title> --video-id <video-id>` and use its `<cwd>/<safe-title>-<video-id>-<id-digest>/` result. Here `safe-title` is NFKC-normalized, Windows-safe, UTF-8-byte bounded, and ends in an eight-hex SHA-256 title digest; `id-digest` preserves the distinction between case-only video IDs on case-insensitive filesystems. The resolver uses a bounded-wait per-video lock whose existing file must be a single-link regular file, rejects symlink/junction/reparse escapes, validates a versioned manifest schema, rejects duplicate valid video-ID claims, safely recovers an empty candidate left before manifest commit, and reuses that directory even if later metadata changes the title. Keep immutable source files separate from derived artifacts. See [workflow.md](references/workflow.md) for names, manual revision, and failure recovery. A command timeout is not a failure: inspect existing artifacts and resume from the latest complete stage.

1. **Download source video.** Invoke `youtube-scraper` with its explicit video-download command and a stable output directory. Validate the media file and `.download.json` sidecar.
2. **Generate verified English subtitles.** Invoke `generate-and-process-subtitles transcribe` on the YouTube URL with `--require-language en`. This selects only an English manual track or requires ASR language detection to return English; stop on mismatch instead of treating arbitrary Latin-script text as English. Preserve the returned metadata containing `source_language`. Add `--semantic-split` only when confirmed. Preserve the first final SRT as the immutable transcription baseline before any optimization. If semantic split was used, run `qc` on the English SRT and stop on unresolved high-risk orphans.
3. **Optimize only when confirmed.** Require the generated `_subtitle_work/context.txt`; otherwise stop after transcription unless the user supplies reference evidence. Write optimized output to a distinct directory.
4. **Audit optimization changes.** Run `scripts/audit_subtitle_changes.py` against baseline and optimized SRT. Ordinary punctuation, whitespace, and case-only changes may pass automatically; numeric punctuation and measurement symbols remain lexical evidence. Any lexical insertion, deletion, or replacement is `review_required`.
5. **Resolve lexical changes.** Inspect each flagged cue against reliable evidence. Prefer, in order: visible text in exact timestamp frames, official title/description evidence, then audio. Apply only high-confidence corrections. Keep ambiguous items in a confirmation list. Never let an LLM rewrite an entity solely because a description contains a plausible alternative.
6. **Re-run final English QC.** After optimization and every manual lexical resolution, run `qc` on the exact audited English SRT that will be translated. Reuse the original `seam_times_path` plus any still-valid approved-cues and resolved-seams files. Stop on exit `2`; stale approval entries are input errors and must be removed or updated, never ignored.
7. **Translate.** Invoke `generate-and-process-subtitles translate` with `--target-language zh-Hans` and the `bilingual-trans-first` format so Chinese is above English. Use only the final English SRT that passed step 6.
8. **Validate bilingual SRT.** Source metadata must be bound by SHA-256 to the exact audited English SRT. Use transcription metadata directly only when those exact bytes are unchanged. After reviewed edits, run `scripts/bind_reviewed_source_metadata.py` with the upstream metadata and final audit report; pass `--accept-reviewed-changes` only after every `review_required` item has actually been checked, and record reviewer/note evidence. Then run `scripts/validate_bilingual_srt.py` with the audited English SRT as `--source-srt`, the exact-hash metadata as `--source-metadata`, and `--video`. Stop on stale/mismatched metadata, weak ASR confidence, a non-English/unverified source language, source cue/timing or English-text mismatch, invalid timing, overlap, missing or extra language lines, non-sequential numbering, non-finite numeric controls, or material head/tail coverage gaps. Also run `qc --bilingual` so English fragments are not hidden by Chinese. That viewer-facing gate must also be clear of unresolved sub-second dependent tails, adjacent duplicate suffixes, and unfinished modifiers before long subtitle gaps. Check word timestamps/audio before deleting apparent repetition. Fix the audited source and bilingual SRT together, rebind metadata, then rerun both gates. Route missing-speech coverage gaps to source-language interval repair, then translate the added cues.
9. **Render and verify.** Run `scripts/render_bilingual_video.py` with bottom-safe defaults. Require source and output audio unless the user explicitly authorizes `--allow-silent`. A missing-audio error is not authorization; ask first. Render to a temporary file, probe and fully decode the result, extract QA frames, and only then promote it to the requested output. Inspect at least one ordinary QA frame, every frame used to resolve a terminology change, and a frame at any repaired orphan timestamp.
10. **Deliver.** Report the source video, audited English SRT, bilingual SRT, final MP4, audit JSON, validation JSON, QC reports, render report, and QA frames.

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
- Keep libass automatic wrapping enabled so long Chinese remains visible. Overlong English must be recut by QC before render rather than disabling wrapping globally.
- White text, black outline, no opaque box.
- Adaptive CJK font selection with user override available.
- H.264 video and AAC audio in MP4.
- Prefer available NVENC; fall back to `libx264`.
- Serialize renders targeting the same output, including Windows aliases that differ by case, extended-device prefix, or ignored trailing component dots/spaces. Apply the same file-identity normalization to input/output/report collision checks. Use collision-resistant partial/archive names, and never overwrite a validated output in place. Use `--replace-existing` only after creating a recoverable archived copy.

If subtitles overlap important on-screen content, render a short sample and adjust only the requested style variables before the full encode.

## Definition Of Done

Do not call the workflow complete until all are true:

- The downloaded source and sidecar exist and are coherent.
- The immutable transcription baseline is retained.
- Exact-hash source metadata proves `source_language` is English, records the required-language gate and evidence origin/confidence, and matches the final reviewed source SRT byte-for-byte.
- Optimization changes were audited; every lexical change is resolved or explicitly left for user confirmation.
- The exact final English SRT used for translation passed QC after all optimization and manual review changes, with semantic seam failures and approvals inherited and revalidated. Chunk-seam cues were inspected. Every very short cue is classified as a complete utterance (`ok_short`) or has been repaired.
- The bilingual SRT matches the audited English cue count and timing, passes deterministic validation, keeps Chinese above English, and passes the same English-line orphan QC.
- The final video has video and audio streams, duration is within tolerance, and a full decode scan returns no errors. An intentionally silent source requires explicit user authorization and a reported warning.
- QA frames visibly show readable subtitles near the bottom without clipping, including frames at repaired orphan timestamps.
- The final response lists absolute artifact paths and any remaining warnings.

## References

- [atomic-skill-contracts.md](references/atomic-skill-contracts.md): public dependency handoffs.
- [workflow.md](references/workflow.md): directory layout, commands, evidence gates, and recovery.
- [eval.md](references/eval.md): trigger, boundary, regression, and completion checks.
