# Evaluation

Use these checks before publishing meaningful changes.

## Positive Triggers

- "Generate subtitles for this local mp4" -> use `transcribe`.
- "Clean this SRT without changing timing" -> use `clean`.
- "Translate this SRT to zh-Hans and keep bilingual subtitles" -> use `translate`.
- "Re-cut this Whisper JSON into natural subtitle segments" -> use `split`.

## Negative Triggers

- "Dub this video", "clone this voice", or "generate TTS" -> do not use this skill.
- "Summarize the visual content of this video" -> do not use this skill.

## Output Checks

- Only final `.srt` and `.txt` files are directly under the target output directory.
- Downloads, ASR JSON, metadata, cached subtitles, and LLM intermediate data are under `_subtitle_work/`.
- Faster-whisper model files are outside the target output directory because they use the system Hugging Face cache.
- Invalid local paths fail with structured JSON before creating `_subtitle_work/`.
