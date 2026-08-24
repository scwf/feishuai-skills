# Atomic Skill Contracts

Resolve each skill root from the host's available-skill catalog. Do not hard-code a user's home directory and do not import Python modules from another skill.

## youtube-scraper

Purpose in this workflow: download one explicitly requested YouTube video at the downloader's best supported quality and write a metadata sidecar.

Public command shape:

```bash
python "{YOUTUBE_SKILL_ROOT}/scripts/youtube_download.py" "<youtube-url>" --download-video --output-dir "<job-dir>/source"
```

Required handoff checks:

- Exactly one final local media file is identified.
- A sidecar ending in `.download.json` exists.
- The sidecar status is successful and identifies video mode.
- If format merging was requested, missing `ffmpeg` is a hard failure.

Do not use this dependency for transcription or translation.

## generate-and-process-subtitles

Purpose in this workflow: create the source-language subtitle, optionally semantic-split it, optionally optimize it with description evidence, and translate it.

Use the Python environment prescribed by that skill. Resolve it as `{SUBTITLE_PYTHON}`.

Transcription command shape:

```bash
"{SUBTITLE_PYTHON}" "{SUBTITLE_SKILL_ROOT}/scripts/generate_and_process_subtitles.py" transcribe "<youtube-url>" --require-language en --output-dir "<job-dir>/subtitles/transcribed"
```

Add `--semantic-split` only after confirmation. That confirmed option uses ASR because semantic seam repair requires word-level timestamps; otherwise, do not force ASR and allow a reusable English YouTube human subtitle. `--require-language en` rejects a non-English manual track, a mismatched ASR detection, or low-confidence automatic language evidence. Preserve the returned metadata path; it contains the required language, evidence origin/confidence, and SHA-256 of the exact emitted source SRT. Rebind reviewed source bytes with `bind_reviewed_source_metadata.py` after evidence-approved edits.

Targeted missing-speech repair command shape:

```bash
"{SUBTITLE_PYTHON}" "{SUBTITLE_SKILL_ROOT}/scripts/generate_and_process_subtitles.py" transcribe "<local-source-video>" --output-dir "<job-dir>/subtitles/repairs" --language en --start-seconds <start> --end-seconds <end> --no-vad
```

Pass interval bounds, fixed language, and `--no-vad` together. Prefer the already downloaded local source. Merge only verified missing speech into a copy of the audited English SRT; never overwrite the baseline in place. Then translate the added cues.

Optimization command shape:

```bash
"{SUBTITLE_PYTHON}" "{SUBTITLE_SKILL_ROOT}/scripts/generate_and_process_subtitles.py" optimize "<baseline.srt>" --reference-file "<job-dir>/subtitles/transcribed/_subtitle_work/context.txt" --output-dir "<job-dir>/subtitles/optimized"
```

Only run this when optimization was confirmed and the context file exists. Optimization output is untrusted until the composite skill's lexical-change audit passes.

Translation command shape:

```bash
"{SUBTITLE_PYTHON}" "{SUBTITLE_SKILL_ROOT}/scripts/generate_and_process_subtitles.py" translate "<audited-english.srt>" --target-language zh-Hans --subtitle-format bilingual-trans-first --output-dir "<job-dir>/subtitles/bilingual"
```

Before execution, use the current atomic skill's `--help` if an option name may have changed. The current atomic `SKILL.md` and CLI help take precedence over examples in this reference.

Required handoff checks:

- Final user-facing SRT/TXT files are in the requested output directory.
- SRT/TXT publish as a validated pair, refuse existing targets by default, and archive before an explicitly authorized `--replace-existing` replacement.
- Process files remain under `_subtitle_work/`.
- Cue timing survives optimize and translate unless the atomic skill explicitly reports a segmentation operation.
- Translation output is bilingual with Chinese first.
- Source metadata identifies English, records the required-language evidence, and its SHA-256 matches the exact source SRT handed to the bilingual validator; Latin-script presence alone is insufficient.
- The bilingual result is validated against the audited source SRT for cue count, numbering, timing, and exact normalized English text, not only against video duration.
- Semantic orphan/viewer QC on the initial semantic-split English SRT, again on the exact final English SRT after optimization/manual review and before translation, and again on the bilingual English line has no unresolved high-risk alerts, including dependent sub-second tails, adjacent duplicate suffixes, and unfinished modifiers before long subtitle gaps.
- `transcribe --semantic-split` / `split` exit code `2` is `review_required`; do not continue to optimize, translate, or render.

QC command shape:

```bash
"{SUBTITLE_PYTHON}" "{SUBTITLE_SKILL_ROOT}/scripts/generate_and_process_subtitles.py" qc "<final-reviewed-english.srt>" --output "<job-dir>/audit/final-english-orphan-qc.json" --seam-times-file "<seam_times_path returned by transcribe/split>"
```

For a source-verified complete short utterance that is not in the deterministic `ok_short` set, add `--approved-cues-file "<approvals.json>"`. Every entry must match and be consumed by an exact currently approvable cue and include a review reason; stale entries are input errors. It cannot waive hanging-word, lowercase-continuation, or overlong-display-line findings, and the handoff remains blocked until final English QC exits `0`.

```bash
"{SUBTITLE_PYTHON}" "{SUBTITLE_SKILL_ROOT}/scripts/generate_and_process_subtitles.py" qc "<bilingual.srt>" --bilingual --output "<job-dir>/audit/bilingual-orphan-qc.json"
```

## Composite Ownership

The composite skill owns only:

- job directory and immutable-baseline policy;
- dependency sequencing and stop gates;
- optimization lexical-change audit;
- exact-timestamp evidence review;
- bilingual SRT structural validation;
- semantic orphan QC on initial English, final post-review English, and bilingual English lines;
- subtitle burn-in, media verification, QA frames, and final artifact reporting.

This boundary allows each atomic skill to evolve independently while keeping the end-to-end workflow reproducible.
