# Trigger Samples

Use these samples when checking whether `video-frame-understanding` should trigger.

## Positive Samples

- "把这个阿里云发布会视频每 30 秒抽帧并理解画面内容。"
- "Analyze this local product demo video frame by frame with Ollama."
- "从这个本地峰会视频里抽取画面，并忠实总结每一帧的可见内容。"

## Negative Samples

- "给这个视频生成字幕。" Route to a subtitle or transcription workflow.
- "把这个视频翻译成中英双语字幕。" Route to subtitle translation.
- "基于这个发布会做 SWOT / 商业洞察。" Do not trigger this skill. If frame materials are needed, the user should explicitly ask to understand the video by frames.
- "把这个视频做成 PPT。" Do not trigger this skill; deck generation is outside scope.

## Error Sample

- `video.mp4` with no user-provided topic must ask for `video_topic` before running.
