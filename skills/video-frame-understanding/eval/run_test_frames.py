#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
from datetime import datetime
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = SKILL_ROOT / "scripts" / "video_frame_understanding.py"
TEST_FRAMES_DIR = SKILL_ROOT / "eval" / "test_frames"
DEFAULT_TOPIC = "阿里云 2026 峰会主论坛下午场"


def load_skill_module():
    spec = importlib.util.spec_from_file_location("video_frame_understanding", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load script module: {SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run video-frame-understanding prompt eval on bundled test frames.")
    parser.add_argument("--video-topic", default=DEFAULT_TOPIC, help="Video topic passed to the prompt.")
    parser.add_argument("--model", default="qwen3-vl:8b", help="Ollama vision model name.")
    parser.add_argument("--output-dir", default=None, help="Output directory. Defaults to eval/test_runs/<timestamp>.")
    return parser.parse_args()


def timestamp_from_name(path: Path) -> str:
    parts = path.stem.split("_")
    if len(parts) >= 3:
        return parts[-1].replace("-", ":")
    return "00:00:00"


def write_json(path: Path, payload) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    args = parse_args()
    module = load_skill_module()
    frames = sorted(TEST_FRAMES_DIR.glob("*.png"))
    if not frames:
        raise SystemExit(f"No test frames found in {TEST_FRAMES_DIR}")

    output_dir = Path(args.output_dir).resolve() if args.output_dir else SKILL_ROOT / "eval" / "test_runs" / datetime.now().strftime("%Y%m%d-%H%M%S")
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"[EVAL_START] frames={len(frames)} topic={args.video_topic} model={args.model}", flush=True)
    records = []
    for index, frame_path in enumerate(frames, start=1):
        timestamp = timestamp_from_name(frame_path)
        print(f"[EVAL_RUN] {index}/{len(frames)} {frame_path.name}", flush=True)
        record = module.understand_frame(frame_path, timestamp, args.video_topic, args.model)
        record["frame_file"] = frame_path.name
        records.append(record)
        write_json(output_dir / f"{frame_path.stem}.json", record)

    jsonl_path = output_dir / "test_frames_understanding.jsonl"
    with jsonl_path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    markdown_lines = [
        "# Video Frame Understanding Eval",
        "",
        f"- Video topic: {args.video_topic}",
        f"- Model: {args.model}",
        f"- Frames: {len(records)}",
        "",
    ]
    for record in records:
        markdown_lines.extend(
            [
                f"## {record['frame_file']} ({record['timestamp']})",
                "",
                record["frame_content"],
                "",
            ]
        )
    markdown_path = output_dir / "summary.md"
    markdown_path.write_text("\n".join(markdown_lines), encoding="utf-8")

    manifest = {
        "status": "ok",
        "video_topic": args.video_topic,
        "model": args.model,
        "frame_count": len(records),
        "output_dir": str(output_dir),
        "jsonl_path": str(jsonl_path),
        "summary_path": str(markdown_path),
    }
    write_json(output_dir / "manifest.json", manifest)
    print(json.dumps(manifest, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
