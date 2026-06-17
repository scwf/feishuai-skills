---
name: generate-and-process-subtitles
description: Generate and process subtitles from local audio/video files, video URLs, existing SRT files, or raw Whisper word-timestamp JSON. Use when an AI agent needs to create SRT/TXT subtitles, reuse available YouTube human subtitles, transcribe media with cross-platform Python faster-whisper, clean or optimize subtitles, translate subtitles, or optionally apply LLM semantic subtitle segmentation. Do not use for dubbing, TTS, voice cloning.
---

# Generate And Process Subtitles

Use this skill for subtitle generation and subtitle text processing. Keep the workflow cross-platform and agent-agnostic: use normal Markdown instructions, Python scripts, JSON metadata, and environment variables only.

Typical requests:

- "Generate subtitles for this video/audio file."
- "Transcribe this YouTube video into SRT and TXT."
- "Clean or optimize this SRT without changing timing."
- "Translate this SRT to Chinese and keep bilingual subtitles."
- "Re-cut this Whisper JSON into natural subtitle segments."

## Routing

1. Local audio/video file or video URL -> run `transcribe`.
2. Existing `.srt` with no translation request -> run `clean` for format normalization, or `optimize` when the user asks for correction/cleanup with an LLM.
3. Existing `.srt` with another language or bilingual output requested -> run `translate`.
4. Raw Whisper JSON with word timestamps plus a request for better segmentation -> run `split`.

Do not perform dubbing, TTS, or voice cloning in this skill.

For YouTube URL transcription requests, ask the user whether they want:

- Transcription only: run `transcribe` and stop after the final `.srt` and `.txt`.
- Transcription plus description-aware optimization: run `transcribe`, then run `optimize` on the generated SRT using `<output-dir>/_subtitle_work/context.txt` as `--description-file`.

Keep `transcribe` itself ASR/subtitle-extraction focused. Do not add an LLM optimization step to `transcribe`; perform optimization only as a separate follow-up command after the user confirms.
Only run description-aware optimization when the current `transcribe` result includes a `context_file` and that file exists. If no context file was generated, tell the user the video has no available description context and stop after transcription unless they provide another description file.

## Output Rules

Write only final user-facing `.srt` and `.txt` files directly in the target output directory.

Write all process artifacts under `<output-dir>/_subtitle_work/`, including downloaded audio, reusable YouTube subtitle downloads, raw ASR JSON, normalized JSON, metadata, and LLM intermediate outputs.

For YouTube inputs, `transcribe` also writes the video's description metadata and, when a description is available, `<output-dir>/_subtitle_work/context.txt`. This context file includes the title, channel, and raw video description for optional later optimization with `optimize --description-file`; it is not used automatically by `transcribe`.

Default output directory is `subtitles/` relative to the current working directory unless the user specifies another target.

## Runtime

Prefer `uv` to create a per-skill Python virtual environment at `{SKILL_ROOT}/.venv` so this skill's dependencies do not pollute the user's global Python environment. If the host agent already provides an isolated Python runtime, use that instead.

```bash
uv venv {SKILL_ROOT}/.venv
uv pip install --python {SKILL_ROOT}/.venv/bin/python -r {SKILL_ROOT}/requirements.txt
```

On Windows:

```bash
uv venv {SKILL_ROOT}\.venv
uv pip install --python {SKILL_ROOT}\.venv\Scripts\python.exe -r {SKILL_ROOT}\requirements.txt
```

If `uv` is unavailable, fall back to `python -m venv` and install with that venv's `python -m pip`. Use the same venv Python for later CLI runs. In command examples, resolve `{PYTHON}` to `{SKILL_ROOT}/.venv/bin/python` on macOS/Linux or `{SKILL_ROOT}\.venv\Scripts\python.exe` on Windows.

The ASR backend is Python `faster-whisper` only. Default model is `large-v2`. Default device and compute type are `auto`; the script falls back to `cpu/int8` if model loading fails on the requested device.

On first ASR use, `faster-whisper` may download the selected model. Model files are stored in the system Hugging Face cache, not in the subtitle output directory or `_subtitle_work/`. Repeated runs reuse the cached model.

LLM features use OpenAI-compatible chat completions. Set `SUBTITLE_LLM_API_KEY`; optionally set `SUBTITLE_LLM_BASE_URL` and `SUBTITLE_LLM_MODEL`. These can come from the host environment or an untracked local `{SKILL_ROOT}/llm.env` file. The default endpoint is `https://api.deepseek.com/v1`, and the default model is `deepseek-v4-flash`.

## Commands

Run from any working directory:

Resolve `{SKILL_ROOT}` to this skill folder before running commands.

```bash
{PYTHON} {SKILL_ROOT}/scripts/generate_and_process_subtitles.py transcribe input.mp4 --output-dir ./subtitles
```

Useful commands:

```bash
{PYTHON} {SKILL_ROOT}/scripts/generate_and_process_subtitles.py transcribe input.mp4 -o ./subtitles
{PYTHON} {SKILL_ROOT}/scripts/generate_and_process_subtitles.py transcribe "https://www.youtube.com/watch?v=..." -o ./subtitles
{PYTHON} {SKILL_ROOT}/scripts/generate_and_process_subtitles.py clean input.srt -o ./subtitles
{PYTHON} {SKILL_ROOT}/scripts/generate_and_process_subtitles.py optimize input.srt -o ./subtitles
{PYTHON} {SKILL_ROOT}/scripts/generate_and_process_subtitles.py translate input.srt --target-language zh-Hans -o ./subtitles
{PYTHON} {SKILL_ROOT}/scripts/generate_and_process_subtitles.py split raw-whisper.json -o ./subtitles
```

Semantic splitting is supported but not part of the default transcription path. Use `--semantic-split` on `transcribe`, or use `split` on an existing raw Whisper JSON, only when the user explicitly asks for semantic segmentation, natural subtitle breaking, or re-segmentation.

## References

Load only the reference needed for the current task:

- `references/transcribe.md` for local media, URLs, YouTube subtitles, ASR device/model options, and output placement.
- `references/process.md` for clean, optimize, translate, and semantic split workflows.
- `references/setup.md` for dependency installation, ffmpeg notes, and LLM environment variables.
- `references/eval.md` for minimal trigger, boundary, and output-placement checks before publishing changes.
