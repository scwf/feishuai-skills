#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
DEFAULT_MODEL = "qwen3-vl:8b"


PROMPT_TEMPLATE = """你是一个科技发布会视频帧发布材料理解助手。

视频主题：{video_topic}
当前帧时间戳：{timestamp}

你的任务不是描述整张现场照片，而是优先理解画面中的发布材料内容，包括大屏幕、PPT、演示界面、图表、架构图、产品页、时间线、数据页或 Demo 界面。

请优先提取和解读：
1. 屏幕/PPT/演示界面上的清晰可见文字；
2. 产品名、技术名、能力点、指标、时间线、架构关系；
3. 图表、流程图、架构图、表格或 Demo 界面表达的结构和含义；
4. 这一页发布材料正在表达的核心信息。

请忽略或极度压缩以下现场元素，除非它们直接出现在发布材料中并影响理解：
- 演讲者衣着、姿态、动作；
- 麦克风、遥控器；
- 舞台灯光、观众席、座椅、会场氛围；
- “有人在演讲”这类泛泛描述。

如果屏幕上出现演讲者姓名、职位、公司标识或会议标题，这些属于发布材料内容，可以提取。
如果这一帧没有清晰可读的发布材料内容，请明确写“未看到清晰可读的发布材料内容”，并只用极短文字说明可见标识或背景。

不要根据常识、品牌背景、上下文或猜测补充图片中不存在的信息。
如果文字或发布材料内容看不清，请明确写“看不清”或“无法确认”。

请严格输出 JSON，不要输出 Markdown，不要输出额外解释。

JSON 字段只能包含：
{{
  "timestamp": "{timestamp}",
  "video_topic": "{video_topic}",
  "frame_content": "屏幕/PPT/演示界面中清晰可见的发布材料内容，包括文字、标题、图表、架构、产品信息、技术信息和关键视觉结构；忽略与发布材料无关的现场元素",
  "frame_interpretation": "基于屏幕/PPT/演示界面可见内容，对这一页发布材料在讲什么做忠实解读；不补充画面中不存在的信息"
}}
"""


GENERIC_TOPIC_NAMES = {
    "video",
    "videos",
    "recording",
    "screen recording",
    "screenrecording",
    "meeting",
    "demo",
    "test",
    "untitled",
    "input",
    "output",
    "clip",
    "movie",
    "sample",
    "录屏",
    "屏幕录制",
    "会议",
    "视频",
    "测试",
    "未命名",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract video frames and understand them serially with a local Ollama vision model."
    )
    parser.add_argument("video_path", help="Path to the local video file.")
    parser.add_argument(
        "--video-topic",
        default=None,
        help="Confirmed video topic. If omitted, the script tries a conservative filename-only inference.",
    )
    parser.add_argument(
        "--interval-seconds",
        type=float,
        default=30.0,
        help="Frame extraction interval in seconds. Default: 30.",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"Ollama vision model name. Default: {DEFAULT_MODEL}.",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Result directory. Defaults to ./<video_stem>-frame-understanding-YYYYMMDD-HHMMSS/.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite frame and JSON outputs inside the selected output directory.",
    )
    parser.add_argument(
        "--skip-existing",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Skip frames that already have JSON outputs. Default: true.",
    )
    return parser.parse_args()


def fail(error_type: str, message: str, **extra: Any) -> None:
    payload = {"status": "failed", "error_type": error_type, "message": message}
    payload.update(extra)
    print(json.dumps(payload, ensure_ascii=False, indent=2), file=sys.stderr)
    raise SystemExit(1)


def sanitize_path_part(value: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).strip(" ._")
    return cleaned or "video"


def infer_topic_from_filename(video_path: Path) -> str | None:
    stem = video_path.stem
    normalized = re.sub(r"[_\-]+", " ", stem)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    normalized = re.sub(r"\b(720p|1080p|2k|4k|8k|hdr|uhd|fhd)\b", "", normalized, flags=re.I)
    normalized = re.sub(r"\b\d{4}[-_.]?\d{1,2}[-_.]?\d{1,2}\b", "", normalized)
    normalized = re.sub(r"\b\d{8}[-_]?\d{0,6}\b", "", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()

    if not normalized:
        return None
    if normalized.lower() in GENERIC_TOPIC_NAMES:
        return None
    if len(normalized) < 4 and not re.search(r"[\u4e00-\u9fff]", normalized):
        return None
    return normalized


def resolve_video_topic(video_path: Path, provided_topic: str | None) -> str:
    if provided_topic and provided_topic.strip():
        return provided_topic.strip()

    inferred = infer_topic_from_filename(video_path)
    if inferred:
        return inferred

    fail(
        "missing_video_topic",
        "Could not infer a reliable video topic from the file name. Confirm the topic before running and pass --video-topic.",
        video_file=video_path.name,
    )


def make_output_dir(video_path: Path, output_dir: str | None) -> Path:
    if output_dir:
        return Path(output_dir).expanduser().resolve()
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    name = f"{sanitize_path_part(video_path.stem)}-frame-understanding-{timestamp}"
    return (Path.cwd() / name).resolve()


def require_ffmpeg() -> None:
    if shutil.which("ffmpeg") is None:
        fail("missing_dependency", "ffmpeg was not found on PATH. Install ffmpeg before running this skill.")


def format_timestamp(seconds: float) -> str:
    total = int(round(seconds))
    hours = total // 3600
    minutes = (total % 3600) // 60
    secs = total % 60
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def timestamp_for_frame(frame_path: Path, interval_seconds: float, index: int) -> str:
    match = re.search(r"_(\d{2})-(\d{2})-(\d{2})\.", frame_path.name)
    if match:
        return ":".join(match.groups())
    return format_timestamp((index - 1) * interval_seconds)


def clear_directory(path: Path) -> None:
    if not path.exists():
        return
    for item in path.iterdir():
        if item.is_dir():
            shutil.rmtree(item)
        else:
            item.unlink()


def extract_frames(video_path: Path, frames_dir: Path, interval_seconds: float, overwrite: bool) -> list[Path]:
    if interval_seconds <= 0:
        fail("invalid_argument", "--interval-seconds must be greater than 0.", interval_seconds=interval_seconds)

    frames_dir.mkdir(parents=True, exist_ok=True)
    existing = sorted(p for p in frames_dir.iterdir() if p.suffix.lower() in IMAGE_SUFFIXES)
    if existing and not overwrite:
        return existing

    if overwrite:
        clear_directory(frames_dir)

    temp_pattern = frames_dir / "raw_frame_%06d.png"
    # Always keep the first frame, then select the next frame only after the
    # configured interval has elapsed. This avoids empty output for short videos.
    select_filter = f"select=eq(n\\,0)+gte(t-prev_selected_t\\,{interval_seconds})"
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(video_path),
        "-vf",
        select_filter,
        "-vsync",
        "vfr",
        str(temp_pattern),
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        fail(
            "ffmpeg_failed",
            "ffmpeg failed to extract frames.",
            stderr=result.stderr.strip(),
            command=" ".join(command),
        )

    raw_frames = sorted(frames_dir.glob("raw_frame_*.png"))
    if not raw_frames:
        fail("no_frames_extracted", "No frames were extracted from the video.", video_path=str(video_path))

    renamed: list[Path] = []
    for index, raw_path in enumerate(raw_frames, start=1):
        ts = format_timestamp((index - 1) * interval_seconds).replace(":", "-")
        new_path = frames_dir / f"frame_{index:06d}_{ts}.png"
        raw_path.rename(new_path)
        renamed.append(new_path)
    return renamed


def parse_json_content(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text)
    return json.loads(text)


def normalize_frame_record(record: dict[str, Any], timestamp: str, video_topic: str) -> dict[str, str]:
    return {
        "timestamp": str(record.get("timestamp") or timestamp),
        "video_topic": str(record.get("video_topic") or video_topic),
        "frame_content": str(record.get("frame_content") or ""),
        "frame_interpretation": str(record.get("frame_interpretation") or ""),
    }


def understand_frame(frame_path: Path, timestamp: str, video_topic: str, model: str) -> dict[str, str]:
    try:
        from ollama import chat
    except ImportError:
        fail("missing_dependency", "Python package 'ollama' is not installed. Run: pip install ollama")

    prompt = PROMPT_TEMPLATE.format(video_topic=video_topic, timestamp=timestamp)
    response = chat(
        model=model,
        messages=[
            {
                "role": "user",
                "content": prompt,
                "images": [frame_path.read_bytes()],
            }
        ],
        format="json",
        options={
            "temperature": 0,
            "num_ctx": 8192,
            "num_predict": 1536,
        },
        keep_alive="30m",
    )

    content = response.message.content
    try:
        parsed = parse_json_content(content)
        return normalize_frame_record(parsed, timestamp, video_topic)
    except Exception:
        return {
            "timestamp": timestamp,
            "video_topic": video_topic,
            "frame_content": "无法解析模型输出。",
            "frame_interpretation": content.strip(),
        }


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def rebuild_jsonl(frame_json_dir: Path, jsonl_path: Path) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    for json_path in sorted(frame_json_dir.glob("*.json")):
        records.append(load_json(json_path))
    with jsonl_path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return records


def compact_text(value: str, limit: int = 220) -> str:
    text = re.sub(r"\s+", " ", value).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def similarity_key(record: dict[str, Any]) -> str:
    content = str(record.get("frame_content", ""))
    interpretation = str(record.get("frame_interpretation", ""))
    key = (content + " " + interpretation).lower()
    key = re.sub(r"\s+", "", key)
    return key[:240]


def build_summary(records: list[dict[str, Any]], summary_path: Path, video_topic: str) -> None:
    lines = [
        f"# 视频帧理解汇总",
        "",
        f"- 视频主题：{video_topic}",
        f"- 帧记录数：{len(records)}",
        "",
        "本汇总仅根据逐帧 JSON 记录整理，用于人工快速阅读；不添加画面外事实、观点或商业判断。",
        "",
        "## 逐帧内容",
        "",
    ]

    previous_key = None
    duplicate_count = 0

    for record in records:
        current_key = similarity_key(record)
        if current_key and current_key == previous_key:
            duplicate_count += 1
            continue

        if duplicate_count:
            lines.append(f"- 已省略连续相似帧：{duplicate_count}")
            lines.append("")
            duplicate_count = 0

        previous_key = current_key
        timestamp = record.get("timestamp", "")
        content = compact_text(str(record.get("frame_content", "")), 360)
        interpretation = compact_text(str(record.get("frame_interpretation", "")), 360)

        lines.append(f"### {timestamp}")
        lines.append("")
        lines.append(f"- 画面内容：{content or '无法确认'}")
        lines.append(f"- 画面解读：{interpretation or '无法确认'}")
        lines.append("")

    if duplicate_count:
        lines.append(f"- 已省略连续相似帧：{duplicate_count}")
        lines.append("")

    summary_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    args = parse_args()
    video_path = Path(args.video_path).expanduser().resolve()
    if not video_path.exists() or not video_path.is_file():
        fail("missing_video", "Video file does not exist.", video_path=str(video_path))

    video_topic = resolve_video_topic(video_path, args.video_topic)
    require_ffmpeg()

    output_dir = make_output_dir(video_path, args.output_dir)
    frames_dir = output_dir / "frames"
    frame_json_dir = output_dir / "frame_json"
    jsonl_path = output_dir / "all_frames_understanding.jsonl"
    summary_path = output_dir / "summary.md"
    manifest_path = output_dir / "manifest.json"

    output_dir.mkdir(parents=True, exist_ok=True)
    frame_json_dir.mkdir(parents=True, exist_ok=True)
    if args.overwrite:
        clear_directory(frame_json_dir)

    started_at = datetime.now().isoformat(timespec="seconds")
    frames = extract_frames(video_path, frames_dir, args.interval_seconds, args.overwrite)

    failures: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    for index, frame_path in enumerate(frames, start=1):
        timestamp = timestamp_for_frame(frame_path, args.interval_seconds, index)
        out_json_path = frame_json_dir / f"{frame_path.stem}.json"

        if args.skip_existing and out_json_path.exists():
            print(f"[SKIP] {index}/{len(frames)} {frame_path.name}")
            continue

        print(f"[RUN ] {index}/{len(frames)} {frame_path.name}")
        try:
            result = understand_frame(frame_path, timestamp, video_topic, args.model)
            if result.get("frame_content") == "无法解析模型输出。":
                warnings.append(
                    {
                        "warning_type": "model_json_parse_fallback",
                        "frame_index": index,
                        "frame_file": frame_path.name,
                        "timestamp": timestamp,
                        "message": "Model output was not valid JSON; raw output was preserved in frame_interpretation.",
                    }
                )
            write_json(out_json_path, result)
        except Exception as exc:
            error = {
                "frame_index": index,
                "frame_file": frame_path.name,
                "timestamp": timestamp,
                "error": str(exc),
            }
            failures.append(error)
            error_path = frame_json_dir / f"{frame_path.stem}.error.txt"
            error_path.write_text(json.dumps(error, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"[ERR ] {index}/{len(frames)} {frame_path.name}: {exc}")

        time.sleep(0.2)

    records = rebuild_jsonl(frame_json_dir, jsonl_path)
    build_summary(records, summary_path, video_topic)

    processed_count = len(records)
    parse_warning_timestamps = {
        item.get("timestamp")
        for item in warnings
        if item.get("warning_type") == "model_json_parse_fallback"
    }
    for record in records:
        timestamp = record.get("timestamp", "")
        if record.get("frame_content") == "无法解析模型输出。" and timestamp not in parse_warning_timestamps:
            warnings.append(
                {
                    "warning_type": "model_json_parse_fallback",
                    "timestamp": timestamp,
                    "message": "A frame JSON contains model output that could not be parsed as valid JSON.",
                }
            )

    if processed_count < len(frames):
        warnings.append(
            {
                "warning_type": "incomplete_processing",
                "message": "Processed frame JSON count is lower than extracted frame count.",
                "frame_count": len(frames),
                "processed_count": processed_count,
            }
        )

    status = "ok" if not failures and not warnings else "ok_with_warnings"
    manifest = {
        "status": status,
        "video_path": str(video_path),
        "video_topic": video_topic,
        "interval_seconds": args.interval_seconds,
        "model": args.model,
        "output_dir": str(output_dir),
        "frames_dir": str(frames_dir),
        "frame_json_dir": str(frame_json_dir),
        "jsonl_path": str(jsonl_path),
        "summary_path": str(summary_path),
        "frame_count": len(frames),
        "processed_count": processed_count,
        "failure_count": len(failures),
        "warning_count": len(warnings),
        "failures": failures,
        "warnings": warnings,
        "started_at": started_at,
        "finished_at": datetime.now().isoformat(timespec="seconds"),
    }
    write_json(manifest_path, manifest)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
