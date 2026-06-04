# Process Subtitles

Resolve `{SKILL_ROOT}` to this skill folder before running commands.

## Clean

Normalize an existing SRT and export clean SRT/TXT without LLM calls:

```bash
python {SKILL_ROOT}/scripts/generate_and_process_subtitles.py clean input.srt --output-dir ./subtitles
```

## Optimize

Use an LLM to correct subtitle recognition errors while preserving timing:

```bash
python {SKILL_ROOT}/scripts/generate_and_process_subtitles.py optimize input.srt --output-dir ./subtitles
```

Configure the LLM with `SUBTITLE_LLM_*` environment variables or the untracked `{SKILL_ROOT}/llm.env` file described in `references/setup.md`.

Add context with `--description` or `--description-file` for names, terminology, or source notes.

## Translate

Translate an existing SRT:

```bash
python {SKILL_ROOT}/scripts/generate_and_process_subtitles.py translate input.srt --target-language zh-Hans --output-dir ./subtitles
```

Output format choices:

- `bilingual-trans-first`
- `bilingual-source-first`
- `translation-only`

## Semantic Split

Use only when the user explicitly requests semantic segmentation or natural subtitle line breaking.

For raw Whisper JSON:

```bash
python {SKILL_ROOT}/scripts/generate_and_process_subtitles.py split raw-whisper.json --output-dir ./subtitles
```

For transcription plus split:

```bash
python {SKILL_ROOT}/scripts/generate_and_process_subtitles.py transcribe input.mp4 --semantic-split --output-dir ./subtitles
```

All process JSON stays under `_subtitle_work/`; only final `.srt` and `.txt` stay in the target directory.
