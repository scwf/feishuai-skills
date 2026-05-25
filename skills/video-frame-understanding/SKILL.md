---
name: video-frame-understanding
description: >
  Understand a local video by extracting frames at a fixed interval and using a local Ollama vision-language model to produce faithful screen-content understanding for each frame. Use when an agent needs faithful frame-level understanding of a local video file, especially technology conference videos, product launch videos, cloud summit recordings, demos, lectures, screen recordings, or presentation-heavy videos. Typical triggers include "analyze this conference video by frames", "把这个发布会视频按帧理解", "从这个产品发布视频里抽帧并解读画面", and "summarize visible slide content from this local video". The skill writes extracted frames, one compact script-generated JSON file per frame, a JSONL aggregate, and a faithful Chinese Markdown summary. Do not use for audio transcription, subtitle generation, dubbing, creative commentary, opinionated analysis, SWOT, strategy reports, or PPT generation.
---

# Video Frame Understanding

Use this skill to convert a local video into a faithful screen-content-first material library.

For technology conference and product launch videos, prioritize the published material shown on screen: slides, large-screen content, demo interfaces, charts, architecture diagrams, timelines, product pages, and data pages. Do not treat venue, lighting, audience, speaker clothing, microphones, or generic stage activity as important unless those details are part of the visible published material.

The skill is platform-neutral. Any agent may use it by reading this file and running the bundled script.

`{SKILL_ROOT}` means the absolute path to the directory containing this `SKILL.md`.

## Preflight

Before running the workflow, resolve these inputs:

1. Local video file path.
2. `video_topic`.
3. Frame interval.
4. Ollama model name.

### Required User Confirmation

Do not run extraction or Ollama calls until the user explicitly confirms the resolved execution plan.

Always show the confirmation block even when every value is a default or an inferred value:

```text
请确认本次视频帧理解任务配置：
- 视频文件：<absolute video path>
- 视频主题：<confirmed or filename-inferred video_topic>
- 抽帧间隔：30 秒（或用户指定值）
- Ollama 模型：qwen3-vl:8b（或用户指定值）
- 输出目录：<explicit output dir or current working directory timestamped dir>
- 预计抽帧数量：<estimated_frames if duration is available>

确认后我再开始执行。
```

If the user changes any value, update the plan and ask for confirmation again. Treat this confirmation as a hard gate, not an optional courtesy.

Check the local environment before starting a long run:

```bash
ffmpeg -version
ollama list
pip show ollama
```

If `ollama` is missing, run:

```bash
pip install -r "{SKILL_ROOT}/requirements.txt"
```

If the default model is missing, run:

```bash
ollama pull qwen3-vl:8b
```

### Video Topic Rule

Confirm `video_topic` before starting extraction or model calls.

Resolve it in this order:

1. If the user provides the topic, use it.
2. Otherwise, infer only from the video file name.
3. If the file name is generic or unclear, ask the user to confirm the topic before running.

Do not inspect early frames to infer the topic. Do not start the workflow until `video_topic` is known.

The script accepts `--video-topic`. If omitted, it makes one conservative filename-based inference attempt and fails fast when the name is unclear.

### Frame Interval Rule

Default to `30` seconds per frame. Before execution, tell the user the default interval and let them override it when interaction is possible.

The script supports interval override with `--interval-seconds`.

Use these simple heuristics:

- Short dense demos or fast UI walkthroughs: consider `5` to `10` seconds.
- Long meetings or slow presentation recordings: consider `60` seconds, or run a short test segment first when available.

### Serial Processing Rule

Process images serially. Use one Ollama request per image. Do not parallelize model calls.

This is intentional for consumer GPUs and local Ollama environments.

## Long-Running Runs

Long videos can take a long time because every extracted frame is sent to the local vision model.

Before running, estimate approximate frame count:

```bash
ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "video.mp4"
```

```text
estimated_frames = video_duration_seconds / interval_seconds
```

Tell the user the estimate when possible. For large jobs, prefer running in a way that preserves terminal output or logs so progress remains visible.

The script prints progress lines:

```text
[START] video=... topic=... interval=30 model=qwen3-vl:8b
[EXTRACT] extracting frames to ...
[FRAMES] extracted 240 frames
[UNDERSTAND] processing 240 frames serially with qwen3-vl:8b
[RUN ] 12/240 frame_000012_00-05-30.png
[SKIP] 13/240 frame_000013_00-06-00.png
[ERR ] 14/240 frame_000014_00-06-30.png: ...
```

After completion, report `manifest.output_dir` so the user can find the timestamped result directory.

## Command

Run commands only after the required user confirmation above.

Default command:

```bash
python "{SKILL_ROOT}/scripts/video_frame_understanding.py" "path/to/video.mp4" --video-topic "confirmed topic"
```

With a custom interval:

```bash
python "{SKILL_ROOT}/scripts/video_frame_understanding.py" "path/to/video.mp4" --video-topic "confirmed topic" --interval-seconds 10
```

With a custom model:

```bash
python "{SKILL_ROOT}/scripts/video_frame_understanding.py" "path/to/video.mp4" --video-topic "confirmed topic" --model "qwen3-vl:8b"
```

Resume after interruption:

```bash
python "{SKILL_ROOT}/scripts/video_frame_understanding.py" "path/to/video.mp4" --video-topic "confirmed topic" --output-dir "existing-result-dir"
```

The script skips existing frame JSON by default.

Force a full rerun:

```bash
python "{SKILL_ROOT}/scripts/video_frame_understanding.py" "path/to/video.mp4" --video-topic "confirmed topic" --output-dir "existing-result-dir" --overwrite
```

Use `--no-skip-existing` only when you want to regenerate frame JSON while keeping already extracted frames.

Use `--output-dir` only when the user explicitly wants a specific destination. If omitted, the script creates a timestamped result directory in the current working directory:

```text
./<video_stem>-frame-understanding-YYYYMMDD-HHMMSS/
  frames/
  frame_json/
  all_frames_understanding.jsonl
  summary.md
  manifest.json
```

## Per-Frame JSON

The vision model outputs only the frame content text. The script wraps that text into JSON.

Each frame JSON must use only these fields:

```json
{
  "timestamp": "00:00:30",
  "video_topic": "confirmed or inferred video topic",
  "frame_content": "clearly visible published material on the screen plus a faithful content-grounded explanation, preserving text hierarchy when possible: main titles, subtitles, card titles, small explanatory text, chart node labels, footnotes/notes, product names, technical terms, charts, architecture, timelines, interface content, and key visual structure"
}
```

Field rules:

- `timestamp`: the frame time in the source video.
- `video_topic`: the confirmed topic for the whole video.
- `frame_content`: observable published material plus faithful explanation in one text field. Prioritize screen/PPT/demo/interface text, diagrams, product names, technologies, metrics, and visual structure. Preserve text hierarchy when possible, including main titles, subtitles, card titles, small explanatory text under technical concepts, chart node labels, footnotes, and notes. If no clear published material is visible, say `未看到清晰可读的发布材料内容`.

Do not ask the vision model to output JSON. JSON must be generated by the script so malformed model JSON cannot break the run.

Low-value frame rule:

- Do not describe speaker clothing, posture, microphones, stage lighting, audience, seats, or atmosphere unless they directly affect understanding the published material.
- If the frame mainly shows a speaker or venue with no readable slide/demo content, keep both fields short and mark it as lacking substantive published material.
- Speaker names, titles, company logos, conference titles, and agenda pages are valid content when they appear as text on the screen.

Small-text rule:

- Do not stop at large titles. Small explanatory text under technical concepts, product capability cards, architecture nodes, metrics, or diagrams is often critical and should be extracted when readable.
- If small text is partially readable, preserve the readable parts and mark the rest as `部分看不清` or `看不清`.

## Output Principles

Default output language is Chinese. Per-frame JSON values and `summary.md` should be written in Chinese unless the user explicitly asks for another language.

The Markdown summary is a human-readable material summary, not an insight report.

Follow these rules:

- stay faithful to frame JSON records
- prioritize published screen material over stage or venue details
- merge only obvious duplicate or near-duplicate consecutive frames
- do not write opinions
- do not make business judgments
- do not infer facts outside the visible frame content
- preserve uncertainty instead of turning it into fact

## Context Window Protection

Do not paste full `all_frames_understanding.jsonl` or all frame JSON contents into the chat.

Default reading order after a run:

1. Read `manifest.json`.
2. Read `summary.md` only when it is short enough for the current context.
3. Read individual files under `frame_json/` only when the user asks about a specific timestamp or when validation needs a sample.

If `summary.md` is long, do not read it all into chat. Use `manifest.json` for run statistics and read only the specific frame JSON files needed for the user's timestamp, question, or validation sample.

Treat `all_frames_understanding.jsonl` as a machine-readable artifact for downstream processing, not as chat content.

## Validation

After running the script, verify:

- `manifest.json` exists and has `status` equal to `ok` or `ok_with_warnings`
- `processed_count` equals `frame_count` when there were no failures and no warnings
- `warning_count` is `0`, or warnings are explained to the user
- `frames/` contains extracted frame images
- `frame_json/` contains one JSON file per successfully processed frame
- `all_frames_understanding.jsonl` exists
- `summary.md` exists
- failures, if any, are listed in `manifest.json`

Also spot-check 1 to 3 frame JSON files for:

- exactly three top-level fields: `timestamp`, `video_topic`, and `frame_content`
- non-empty `timestamp` and `video_topic`
- no obvious model refusal or unrelated response in `frame_content`

If `status` is `ok_with_warnings`, read `manifest.failures` and `manifest.warnings`. Fix the cause, then rerun with the same `--output-dir`; default `--skip-existing` will resume unfinished frames. Use `--overwrite` only when the prior outputs are untrustworthy.

If the script fails before model calls, report the structured error and fix the missing prerequisite.

## Trigger Evaluation

For trigger samples, see `{SKILL_ROOT}/eval/trigger_samples.md` when evaluating or editing this skill.

## Prerequisites

Required:

- Python 3.9+
- `ffmpeg` available on `PATH`
- local Ollama running
- an installed local vision-language model, default `qwen3-vl:8b`
- Python package `ollama`

Install Python dependency when needed:

```bash
pip install -r "{SKILL_ROOT}/requirements.txt"
```

Pull the default model when needed:

```bash
ollama pull qwen3-vl:8b
```
