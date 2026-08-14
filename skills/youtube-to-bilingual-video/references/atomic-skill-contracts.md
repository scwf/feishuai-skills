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
"{SUBTITLE_PYTHON}" "{SUBTITLE_SKILL_ROOT}/scripts/generate_and_process_subtitles.py" transcribe "<youtube-url>" --output-dir "<job-dir>/subtitles/transcribed"
```

Add `--semantic-split` only after confirmation. Do not force ASR unless the user explicitly requests it.

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
- Process files remain under `_subtitle_work/`.
- Cue timing survives optimize and translate unless the atomic skill explicitly reports a segmentation operation.
- Translation output is bilingual with Chinese first.

## Composite Ownership

The composite skill owns only:

- job directory and immutable-baseline policy;
- dependency sequencing and stop gates;
- optimization lexical-change audit;
- exact-timestamp evidence review;
- bilingual SRT structural validation;
- subtitle burn-in, media verification, QA frames, and final artifact reporting.

This boundary allows each atomic skill to evolve independently while keeping the end-to-end workflow reproducible.
