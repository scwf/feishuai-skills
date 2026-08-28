# Atomic Skill Contracts

Resolve both dependency roots from the active skill catalog. Read their current `SKILL.md` and CLI `--help`; those interfaces override examples here. Never hard-code a home directory or import another skill's Python modules.

## youtube-scraper

Download exactly one explicitly requested video:

```bash
python "{YOUTUBE_SKILL_ROOT}/scripts/youtube_download.py" "<youtube-url>" --download-video --output-dir "<job-dir>/source"
```

Accept the handoff only when one final media path is identified and a successful `.download.json` sidecar declares video mode and the same source. Missing merge dependencies or an incoherent sidecar stops the job. This dependency does not transcribe or translate.

## generate-and-process-subtitles

Use the Python runtime prescribed by the atomic Skill.

Transcribe verified English:

```bash
"{SUBTITLE_PYTHON}" "{SUBTITLE_SKILL_ROOT}/scripts/generate_and_process_subtitles.py" transcribe "<youtube-url>" --require-language en --output-dir "<job-dir>/subtitles/transcribed"
```

Add `--semantic-split` only when confirmed. Preserve returned `outputs.srt`, `metadata`, and any `qc_path` / `seam_times_path`. Exit `2` is a blocking review state.

Optional optimize:

```bash
"{SUBTITLE_PYTHON}" "{SUBTITLE_SKILL_ROOT}/scripts/generate_and_process_subtitles.py" optimize "<baseline.srt>" --reference-file "<context.txt>" --output-dir "<job-dir>/subtitles/optimized"
```

Run only when confirmed and the transcribe result returned an existing context file. Treat the result as a candidate until the composite lexical audit resolves it.

Final English and bilingual QC:

```bash
"{SUBTITLE_PYTHON}" "{SUBTITLE_SKILL_ROOT}/scripts/generate_and_process_subtitles.py" qc "<reviewed.en.srt>" --output "<job-dir>/audit/final-english-qc.json" [--seam-times-file "<returned path>"]
"{SUBTITLE_PYTHON}" "{SUBTITLE_SKILL_ROOT}/scripts/generate_and_process_subtitles.py" qc "<bilingual.srt>" --bilingual --output "<job-dir>/audit/bilingual-qc.json"
```

Only exit `0` advances the state machine. Exact approvals or seam resolutions are inputs owned and validated by the atomic Skill. Final delivery uses the defaults. Passing wider QC limits requires the atomic Skill's separate `--allow-relaxed-limits` authorization flag; semantic split and optimize choices never imply it. Preserve the report path because validation binds its SHA-256 and effective limits to the exact reviewed source.

Translate:

```bash
"{SUBTITLE_PYTHON}" "{SUBTITLE_SKILL_ROOT}/scripts/generate_and_process_subtitles.py" translate "<reviewed.en.srt>" --target-language zh-Hans --subtitle-format bilingual-trans-first --output-dir "<job-dir>/subtitles/bilingual"
```

Required handoff invariants are public results, not internal implementation: final SRT/TXT pair paths, process evidence under `_subtitle_work`, source-language metadata bound to exact SRT bytes, unchanged cue timing outside an explicit segmentation operation, and structured status/exit code.

For confirmed source coverage gaps, use the atomic Skill's bounded interval repair command from its current transcribe reference, then rebuild downstream artifacts.

## Composite Ownership

This Skill owns job state, immutable baseline, dependency sequencing, lexical-change audit, evidence review, exact source-metadata rebinding, bilingual structural validation, render verification, QA frames, and final reporting. It consumes atomic results and must not restate or bypass atomic split, translation, QC, path, or publication rules.
