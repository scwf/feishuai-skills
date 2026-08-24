---
name: generate-and-process-subtitles
description: Generate and process subtitles from local audio/video files, video URLs, existing SRT files, or raw Whisper word-timestamp JSON. Use when an AI agent needs to create SRT/TXT subtitles, reuse available YouTube human subtitles, transcribe media with cross-platform Python faster-whisper, normalize or optimize subtitles, translate subtitles, optionally apply LLM semantic subtitle segmentation, or run semantic-orphan QC after a split. Do not use for dubbing, TTS, voice cloning.
---

# Generate And Process Subtitles

Use this skill for subtitle generation and subtitle text processing. Keep the workflow cross-platform and agent-agnostic: use normal Markdown instructions, Python scripts, JSON metadata, and environment variables only.

Typical requests:

- "Generate subtitles for this video/audio file."
- "Transcribe this YouTube video into SRT and TXT."
- "Normalize this SRT and export a TXT copy."
- "Translate this SRT to Chinese and keep bilingual subtitles."
- "Re-cut this Whisper JSON into natural subtitle segments."
- "Check this SRT for semantic orphan cues."

## Routing

1. YouTube URL -> apply the YouTube Confirmation Gate before running any command.
2. Local audio/video file or non-YouTube video URL -> run `transcribe`.
3. Existing `.srt` with no translation request -> run `normalize` for format normalization, or `optimize` when the user asks for recognition-error correction with an LLM.
4. Existing `.srt` with another language or bilingual output requested -> run `translate`.
5. Raw Whisper JSON with word timestamps plus a request for better segmentation -> run `split`.
6. Existing `.srt` plus a semantic-orphan / readability QC request -> run `qc`.

Do not perform dubbing, TTS, or voice cloning in this skill.

## YouTube Confirmation Gate

When the input is a YouTube URL and the user has not already explicitly chosen the transcription shape and post-transcription correction path, ask for confirmation before running any command. Do this even when the user says only "提取字幕", "把字幕提取出来", "extract subtitles", or "transcribe this video"; absence of an optimization or semantic-split request is not consent to skip either choice.

Ask two short questions in order:

1. "转录时要不要启用 semantic split，让字幕断句更自然？"
2. "转录完成后，要不要用视频简介作为参考做一次保守纠错 optimize？"

After asking, stop and wait for the user's answer. If the user answers only the first question, ask the second question before running commands.

Skip a question only when the user's message already makes that choice explicit, such as "不要语义切分 / no semantic split", "加 semantic split / natural subtitle breaking", "只提取字幕 / 不要优化 / transcribe only", or "提取后用简介作为参考纠错 / optimize with description as reference evidence".

The available paths are:

- Transcription only: run `transcribe` and stop after the final `.srt` and `.txt`.
- Transcription plus semantic split: run `transcribe --semantic-split`. Keep the `.srt` and `.txt`, then stop if nested QC reports `review_required` (exit code `2`). That is a quality gate, not a transcription failure. Do not continue to optimize, translate, or treat the run as complete.
- Transcription plus description-reference-assisted correction: run `transcribe`, then run `optimize` on the generated SRT using `<output-dir>/_subtitle_work/context.txt` as `--reference-file`.
- Transcription plus semantic split and correction: run `transcribe --semantic-split`, stop on `review_required`, and only then run `optimize` using `<output-dir>/_subtitle_work/context.txt` as `--reference-file`.

Keep `transcribe` itself ASR/subtitle-extraction focused. Do not add an LLM optimization step to `transcribe`; perform optimization only as a separate follow-up command after the user confirms.
Semantic splitting is allowed inside `transcribe` only when the user confirms it or already requested natural subtitle breaking.
For a YouTube URL, confirmed semantic splitting uses ASR even when human subtitles are available, because seam repair requires word-level timestamps. Human subtitles remain the default only when semantic splitting is off.
Only run description-reference-assisted correction when the current `transcribe` result includes a `context_file` and that file exists. If no context file was generated, tell the user the video has no available description context and stop after transcription unless they provide another reference file.

## Output Rules

Write only final user-facing `.srt` and `.txt` files directly in the target output directory. Strictly parse every SRT input, validate positive/non-overlapping timelines, and byte-check both temporary files against the same `ASRData` serialization. Publish the pair under one normalized-identity cross-process lock through short same-directory temporary files; promote TXT first and SRT last as the completion marker. Existing targets are never overwritten by default. `--replace-existing` is the only replacement authorization; it rejects directories, symlinks, reparse points, and other non-regular targets, archives every existing member before publishing, and reports any incomplete rollback with archive evidence.

Write all process artifacts under `<output-dir>/_subtitle_work/`, including downloaded audio, reusable YouTube subtitle downloads, raw ASR JSON, process JSON, metadata, and LLM intermediate outputs. Final-source metadata, process JSON, nested QC, seam files, and normalized source copies use content-addressed digest names. Create the publish-specific work JSON, metadata, nested QC, seam files, and normalized source copy only while holding the same output-pair lock used for final publication. If pair publication fails, remove artifacts newly created by that transaction and restore any pre-existing same-digest evidence byte-for-byte. A losing or failed publisher therefore cannot leave a metadata handoff for a pair that was never committed.

For YouTube inputs, `transcribe` also writes the video's description metadata and, when a description is available, `<output-dir>/_subtitle_work/context.txt`. This context file includes the title, channel, and raw video description for optional later correction with `optimize --reference-file`; it is not used automatically by `transcribe`. With `--require-language`, handoff metadata records the required language, evidence origin/confidence, exact emitted source path, and SHA-256 of its canonical UTF-8/LF bytes. Automatic language evidence below 0.5 confidence is rejected.

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
{PYTHON} {SKILL_ROOT}/scripts/generate_and_process_subtitles.py normalize input.srt -o ./subtitles
{PYTHON} {SKILL_ROOT}/scripts/generate_and_process_subtitles.py optimize input.srt -o ./subtitles
{PYTHON} {SKILL_ROOT}/scripts/generate_and_process_subtitles.py translate input.srt --target-language zh-Hans -o ./subtitles
{PYTHON} {SKILL_ROOT}/scripts/generate_and_process_subtitles.py split raw-whisper.json -o ./subtitles
{PYTHON} {SKILL_ROOT}/scripts/generate_and_process_subtitles.py qc input.srt --output ./subtitles/_subtitle_work/semantic-orphan-qc.json
```

Standalone `qc` always atomically writes the full report. If `--output` is omitted, it uses `<input-dir>/_subtitle_work/<safe-input-stem>-<stable-digest>.semantic-orphan-qc.json`, except that an input already inside `_subtitle_work` keeps the report beside that input; every default name is collision-resistant and component-length-safe. The normalized file identity, including Windows device-prefix/case/trailing-dot aliases, is checked against every input before writing. Stdout remains a bounded ASCII-safe status summary.

Semantic splitting is supported but not part of the default transcription path. Use `--semantic-split` on `transcribe`, or use `split` on an existing raw Whisper JSON, only when the user explicitly asks for semantic segmentation, natural subtitle breaking, or re-segmentation.

`split` repairs chunk seams after the first pass. It does not rely on the prompt seeing neighboring chunks, does not let one repaired singleton window cascade across later seams, and rejects repaired cues above configured length limits or with zero duration. All split and QC length, chunk, and retry controls must be positive integers. English length limits are both 21 words and 79 on-screen characters at 1080p FontSize 16; 80 characters already wrap. A failed or overlapping seam repair is itself a high-risk QC item and is persisted in a digest-suffixed `*.chunk-seams.json`; consume the exact `seam_times_path` returned by the command. After split, `transcribe --semantic-split` and `split` validate the raw segment and word timelines before punctuation-token normalization, including global order and containment within each segment, then validate the serialized SRT before writing final files. They write QC under `_subtitle_work/` and exit `2` when status is `review_required`; treat that as a stop gate. Zero-duration, overlapping, reverse-timeline, or blank-line cues are structured `invalid_srt` and must not be treated as a complete transcription. A later standalone `qc --seam-times-file` inherits persisted seam failures until each reviewed repair is explicitly recorded with `--resolved-seams-file`. Viewer-facing QC also blocks one-second-or-shorter dependent tails when the preceding local syntax mechanically requires them, marks genuinely ambiguous `To …` attachments as a separately reviewable finding, detects adjacent 2-6-word duplicate suffixes lasting up to 1.5 seconds, and detects an unfinished modifier immediately before a long subtitle gap even when punctuation or a bounded trailing filler was added; each finding includes timestamps plus neighboring cue text and gaps. Complete short discourse markers such as `To be clear, yes.` remain legal when the predecessor does not mechanically require a complement. Do not auto-merge high-risk orphan cues or delete a duplicate without checking word timestamps/audio. Do not merge a lowercase continuation that follows a cue already at the English word or display-character budget; that is a length wrap, not an orphan. Recut hanging function words, hanging auxiliary contractions such as `we're` / `we'll` / `we've`, and `overlong_display_line` cues instead. Legal short utterances such as `Yes.` or `Great.` are `ok_short` and may remain. For a reviewed complete short utterance or ambiguous attachment, record its exact cue number, text, and review reason in an approved-cues JSON file and rerun `qc --approved-cues-file`; continue only when QC returns exit `0`. Every approval entry must exactly match and be consumed by a currently approvable cue. Approvals cannot waive mechanically proven dependent tails, hanging words, duplicate suffixes, long-gap incompleteness, lowercase continuations, or overlong display lines.

## Missing Spoken Audio Without Subtitles

Treat audible speech with no corresponding subtitle cue as a source-transcription coverage failure. Downstream cue-count parity or successful translation does not detect speech that the source SRT never captured.

When this symptom is reported or confirmed:

1. Preserve the current SRT as an immutable baseline and identify the affected time range by listening to the media.
2. Inspect nearby subtitle gaps, starting with gaps of about 1.5 seconds or longer; do not add a full-video gap audit to the default workflow.
3. Re-transcribe only the affected interval with the same or a stronger faster-whisper model, fixed language, word timestamps, `--start-seconds`, `--end-seconds`, and `--no-vad`. These controls must be used together. The CLI writes both validated interval-named repair SRT/TXT outputs before best-effort temporary-file cleanup and refuses existing repair outputs; a locked temporary file cannot turn a complete pair into an SRT-only failure. Include a small amount of surrounding audio when useful, then keep timestamps inside the actual missing-speech interval. Use the exact command in `references/transcribe.md`.
4. Compare the result with the preceding and following cues. Reject boundary duplicates, filler-only fragments, hallucinations, and garbled text; do not auto-merge ASR output.
5. Add only verified missing speech to a copy of the baseline, renumber cues, and validate ordering, overlaps, empty cues, timestamps, and final audio-to-subtitle coverage.
6. If bilingual subtitles already exist, repair the source-language cue first, translate the verified addition, and re-check Chinese-above-English ordering before rendering again.

Do not globally disable VAD as a preventive default. Use local no-VAD re-transcription as a targeted recovery step because VAD can suppress short, quiet, overlapped, or music-backed speech while also reducing false positives during normal transcription.

## References

Load only the reference needed for the current task:

- `references/transcribe.md` for local media, URLs, YouTube subtitles, ASR device/model options, and output placement.
- `references/process.md` for normalize, optimize, translate, and semantic split workflows.
- `references/setup.md` for dependency installation, ffmpeg notes, and LLM environment variables.
- `references/eval.md` for trigger, boundary, seam-repair, orphan-QC, and output-placement checks before publishing changes.
