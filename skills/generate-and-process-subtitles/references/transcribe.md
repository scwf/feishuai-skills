# Transcribe

Use `transcribe` for local audio/video files and video URLs.
Resolve `{SKILL_ROOT}` to this skill folder before running commands.

```bash
python {SKILL_ROOT}/scripts/generate_and_process_subtitles.py transcribe "<input>" --output-dir "<target-dir>"
```

Behavior:

- Final outputs are `<target-dir>/<base>.srt` and `<target-dir>/<base>.txt`.
- Process files go to `<target-dir>/_subtitle_work/`.
- YouTube human subtitles are reused by default when available.
- Pass `--force-asr` when the user explicitly wants ASR instead of reusable YouTube subtitles.
- First ASR use may download the selected `faster-whisper` model into the system Hugging Face cache.
- Repeated ASR runs reuse the cached model.
- Semantic splitting is off by default. Use `--semantic-split` only when requested.

Useful options:

```bash
--model large-v2
--device auto
--compute-type auto
--language en
--force-asr
--semantic-split
```

For GPU use, keep `--device auto` unless the user asks for a specific device. The script falls back to `cpu/int8` if automatic or GPU loading fails.
