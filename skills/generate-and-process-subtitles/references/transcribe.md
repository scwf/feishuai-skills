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
- YouTube video descriptions are saved in metadata and mirrored to `<target-dir>/_subtitle_work/context.txt` when available.
- The context file contains the video title, channel, and raw description. It does not include the source URL.
- The context file is not used by `transcribe`; it exists for optional follow-up optimization.
- Pass `--force-asr` when the user explicitly wants ASR instead of reusable YouTube subtitles.
- First ASR use may download the selected `faster-whisper` model into the system Hugging Face cache.
- Repeated ASR runs reuse the cached model.
- Semantic splitting is off by default. Use `--semantic-split` only when requested.

For YouTube URL requests, confirm the desired workflow before running commands:

- Transcription only: run `transcribe` and stop.
- Transcription plus description-aware optimization: run `transcribe`, then run `optimize` on the generated SRT with `--description-file "<target-dir>/_subtitle_work/context.txt"`.

Before description-aware optimization, verify the `transcribe` JSON includes `context_file` and that the file exists. If no context file was generated, tell the user the video has no available description context and stop after transcription unless they provide another description file.

Example follow-up optimization:

```bash
python {SKILL_ROOT}/scripts/generate_and_process_subtitles.py optimize "<target-dir>/<base>.srt" --description-file "<target-dir>/_subtitle_work/context.txt" --output-dir "<target-dir>"
```

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

On Windows, if GPU transcription fails with a missing CUDA 12 DLL such as `cublas64_12.dll`, install the optional Windows GPU requirements from `references/setup.md`, then retry with `--device cuda --compute-type float16`.
