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

## YouTube Confirmation Gate

For YouTube URL requests, confirm the desired workflow before running any command unless the user already explicitly chose both the transcription shape and post-transcription correction path. Treat generic wording like "提取字幕", "把字幕提取出来", "extract subtitles", "生成字幕", or "transcribe this video" as ambiguous because the skill supports plain transcription, semantic splitting during transcription, and description-reference-assisted correction.

Ask two short questions in order:

1. "转录时要不要启用 semantic split，让字幕断句更自然？"
2. "转录完成后，要不要用视频简介作为参考做一次保守纠错 optimize？"

After asking, stop and wait for the user's answer. If the user answers only the first question, ask the second question before running commands.

Skip a question only when the user has already answered that part, such as "不要语义切分 / no semantic split", "加 semantic split / natural subtitle breaking", "transcription only / 不要优化", or "use the description as reference evidence to correct subtitles".

Available workflows:

- Transcription only: run `transcribe` and stop.
- Transcription plus semantic split: run `transcribe --semantic-split` and stop.
- Transcription plus description-reference-assisted correction: run `transcribe`, then run `optimize` on the generated SRT with `--reference-file "<target-dir>/_subtitle_work/context.txt"`.
- Transcription plus semantic split and correction: run `transcribe --semantic-split`, then run `optimize` on that generated SRT with `--reference-file "<target-dir>/_subtitle_work/context.txt"`.

Before description-reference-assisted correction, verify the `transcribe` JSON includes `context_file` and that the file exists. If no context file was generated, tell the user the video has no available description context and stop after transcription unless they provide another reference file.

Example follow-up optimization:

```bash
python {SKILL_ROOT}/scripts/generate_and_process_subtitles.py optimize "<target-dir>/<base>.srt" --reference-file "<target-dir>/_subtitle_work/context.txt" --output-dir "<target-dir>"
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
