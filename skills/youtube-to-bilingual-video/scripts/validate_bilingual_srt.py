#!/usr/bin/env python3
"""Validate timing, ordering, and Chinese-first bilingual SRT structure."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


TIMING_RE = re.compile(
    r"^(?P<sh>[0-9]{2}):(?P<sm>[0-5][0-9]):(?P<ss>[0-5][0-9]),(?P<sms>[0-9]{3})"
    r"\s*-->\s*"
    r"(?P<eh>[0-9]{2}):(?P<em>[0-5][0-9]):(?P<es>[0-5][0-9]),(?P<ems>[0-9]{3})$"
)
CJK_RE = re.compile(r"[\u3400-\u9fff]")
LATIN_RE = re.compile(r"[A-Za-z]")


@dataclass(frozen=True)
class Cue:
    index: int
    start: float
    end: float
    lines: list[str]


def to_seconds(hours: str, minutes: str, seconds: str, millis: str) -> float:
    return int(hours) * 3600 + int(minutes) * 60 + int(seconds) + int(millis) / 1000


def parse_srt(path: Path) -> list[Cue]:
    raw = path.read_text(encoding="utf-8-sig").replace("\r\n", "\n").strip()
    if not raw:
        raise ValueError("SRT is empty")
    cues: list[Cue] = []
    for position, block in enumerate(re.split(r"\n{2,}", raw), start=1):
        lines = [line.strip() for line in block.splitlines()]
        if len(lines) < 3:
            raise ValueError(f"block {position} has fewer than three lines")
        try:
            index = int(lines[0])
        except ValueError as exc:
            raise ValueError(f"block {position} has invalid cue number") from exc
        match = TIMING_RE.fullmatch(lines[1])
        if not match:
            raise ValueError(f"cue {index} has invalid timing: {lines[1]}")
        values = match.groupdict()
        start = to_seconds(values["sh"], values["sm"], values["ss"], values["sms"])
        end = to_seconds(values["eh"], values["em"], values["es"], values["ems"])
        text_lines = [line for line in lines[2:] if line]
        if not text_lines:
            raise ValueError(f"cue {index} has no text")
        cues.append(Cue(index=index, start=start, end=end, lines=text_lines))
    return cues


def probe_duration(video: Path) -> float:
    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(video),
    ]
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
    if result.returncode != 0:
        raise ValueError(f"ffprobe failed: {result.stderr.strip()}")
    return float(result.stdout.strip())


def validate(cues: list[Cue], duration: float | None, tolerance: float) -> dict[str, object]:
    issues: list[dict[str, object]] = []
    for position, cue in enumerate(cues, start=1):
        if cue.index != position:
            issues.append(
                {"cue": cue.index, "type": "numbering", "expected": position}
            )
        if cue.end <= cue.start:
            issues.append({"cue": cue.index, "type": "non_positive_duration"})
        if position > 1 and cue.start < cues[position - 2].end:
            issues.append(
                {
                    "cue": cue.index,
                    "type": "overlap",
                    "previous_end": cues[position - 2].end,
                    "start": cue.start,
                }
            )
        if len(cue.lines) < 2:
            issues.append({"cue": cue.index, "type": "missing_bilingual_lines"})
        else:
            if not CJK_RE.search(cue.lines[0]):
                issues.append({"cue": cue.index, "type": "first_line_not_chinese"})
            if not LATIN_RE.search(cue.lines[-1]):
                issues.append({"cue": cue.index, "type": "last_line_not_english"})
    last_end = cues[-1].end
    if duration is not None and last_end > duration + tolerance:
        issues.append(
            {
                "cue": cues[-1].index,
                "type": "subtitle_exceeds_video",
                "subtitle_end": last_end,
                "video_duration": duration,
                "tolerance": tolerance,
            }
        )
    return {
        "status": "ok" if not issues else "error",
        "cue_count": len(cues),
        "first_start_seconds": cues[0].start,
        "last_end_seconds": last_end,
        "video_duration_seconds": duration,
        "tail_gap_seconds": None if duration is None else duration - last_end,
        "issues": issues,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a Chinese-first bilingual SRT.")
    parser.add_argument("srt", type=Path)
    parser.add_argument("--video", type=Path, help="Optional video for duration validation")
    parser.add_argument("--duration", type=float, help="Video duration in seconds")
    parser.add_argument("--duration-tolerance", type=float, default=1.0)
    parser.add_argument("--output", type=Path, help="Write JSON report here")
    args = parser.parse_args()
    try:
        if args.video and args.duration is not None:
            raise ValueError("use either --video or --duration, not both")
        duration = probe_duration(args.video) if args.video else args.duration
        cues = parse_srt(args.srt)
        report = validate(cues, duration, args.duration_tolerance)
        report["srt_path"] = str(args.srt.resolve())
        if args.video:
            report["video_path"] = str(args.video.resolve())
        exit_code = 0 if report["status"] == "ok" else 1
    except (OSError, UnicodeError, ValueError) as exc:
        report = {
            "status": "error",
            "reason": "validation_failure",
            "message": str(exc),
            "srt_path": str(args.srt),
        }
        exit_code = 1
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
