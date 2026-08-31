# Evaluation Contract

Evaluate the composite state machine and public artifacts. Atomic subtitle behavior belongs to the atomic Skill's own tests.

## Routing

Select this Skill only for one YouTube URL when the user wants download, Chinese-English subtitles, and a final burned-in MP4 together. Do not select it for subtitle-only work, channel metadata, dubbing/TTS, live streams, batches, or uploads.

An end-to-end request must resolve both semantic-split and description-assisted-optimize choices before download/transcription.

## State And Stop Gates

Verify that:

- the resolver creates or reuses one manifest-backed directory and rejects unsafe or concurrently locked paths;
- download advances only with coherent media and sidecar;
- source language is verified as English and metadata matches the exact reviewed SRT;
- lexical audit exit `2`, atomic QC exit `2`, stale approvals, validation failure, or missing evidence stop later stages;
- translation consumes only the final QC-cleared English SRT and produces Chinese above exact English;
- missing source speech routes to bounded English interval repair before translation;
- validation checks source/bilingual cue parity, exact English text/timing, language order, media coverage, and finite controls;
- validation requires a successful hash-bound final-English QC report and rejects contradictory or unauthorized relaxed-limit evidence;
- rendering requires a current hash-bound, coverage-complete validation report plus viewer QC, preserves audio unless silence was explicitly accepted, and promotes only after stream/duration/decode verification;
- final reporting lists absolute evidence and artifact paths.

## Regression Families

- Entity mutation and fluency rewrite require evidence review; record the actual AI/human reviewer and item-level evidence without treating review as scope expansion. Punctuation/case-only changes still rerun final English QC.
- Numeric punctuation and measurement marks remain semantic where they change meaning.
- Missing, non-English, low-confidence, stale, or hash-mismatched source metadata blocks bilingual validation.
- English-first, missing-Chinese, extra-English, misnumbered, overlapping, or source-mismatched bilingual cues fail.
- Output/report aliases, hardlinked lock files, unsafe resolver paths, and concurrent same-output renders fail safely.
- Injected verified-render promotion failure restores the previous canonical MP4; incomplete rollback reports the archive.
- Legacy Windows code-page runs keep structured bounded output.
- A short real render records streams, duration tolerance, decode result, QA frames, hash, and size.
- Render layout normalization preserves cue numbering, timing, language order, and non-newline text while keeping only one Chinese/English separator; the report records layout hash, wrap style, margins, and Unicode-wrap support.
- Load-aware QA preserves ordinary and user-requested times while adding the Top 5 bilingual cue midpoints with cue-level load evidence; estimated Chinese/English/total line overflow returns `review_required` / exit `2`, retains a review candidate, and leaves the final output untouched.

## Commands

```bash
python -m pytest skills/youtube-to-bilingual-video/tests -q -p no:cacheprovider
python -m py_compile skills/youtube-to-bilingual-video/scripts/*.py
python skills/youtube-to-bilingual-video/scripts/resolve_job_dir.py --help
python skills/youtube-to-bilingual-video/scripts/audit_subtitle_changes.py --help
python skills/youtube-to-bilingual-video/scripts/validate_bilingual_srt.py --help
python skills/youtube-to-bilingual-video/scripts/render_bilingual_video.py --help
```

Also run the Skill validator with UTF-8 mode and compare every documented option with live `--help`. Completion requires an independent severity-ranked review and explicit merge verdict; green tests alone are not approval.
