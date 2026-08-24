#!/usr/bin/env python3
"""Validate timing, ordering, and Chinese-first bilingual SRT structure."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import unicodedata
import uuid
from dataclasses import dataclass
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from path_safety import file_identity


TIMING_RE = re.compile(
    r"^(?P<sh>[0-9]{2}):(?P<sm>[0-5][0-9]):(?P<ss>[0-5][0-9]),(?P<sms>[0-9]{3})"
    r"\s*-->\s*"
    r"(?P<eh>[0-9]{2}):(?P<em>[0-5][0-9]):(?P<es>[0-5][0-9]),(?P<ems>[0-9]{3})$"
)
CJK_RE = re.compile(r"[\u3400-\u9fff]")


class SourceLanguageError(ValueError):
    pass


class SourceMetadataError(ValueError):
    pass


ALLOWED_SOURCE_LANGUAGE_ORIGINS = {
    "asr_detection",
    "fixed_asr_language",
    "manual_subtitle_track",
    "reviewed_source_handoff",
}
MIN_ASR_LANGUAGE_PROBABILITY = 0.5


def language_matches(actual: object, expected: str) -> bool:
    if not isinstance(actual, str) or not actual.strip():
        return False
    actual_normalized = actual.lower().replace("_", "-")
    expected_normalized = expected.lower().replace("_", "-")
    return (
        actual_normalized == expected_normalized
        or actual_normalized.startswith(f"{expected_normalized}-")
        or expected_normalized.startswith(f"{actual_normalized}-")
    )


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


def script_counts(text: str) -> tuple[int, int]:
    cjk_count = len(CJK_RE.findall(text))
    latin_count = sum(
        1
        for char in text
        if unicodedata.category(char).startswith("L")
        and "LATIN" in unicodedata.name(char, "")
    )
    return cjk_count, latin_count


def normalized_lines(lines: list[str]) -> list[str]:
    return [
        re.sub(r"\s+", " ", unicodedata.normalize("NFC", line)).strip()
        for line in lines
    ]


def require_finite_nonnegative(
    name: str, value: float | None, *, allow_zero: bool = True
) -> None:
    if value is None:
        return
    if not math.isfinite(value) or value < 0 or (not allow_zero and value == 0):
        qualifier = "a positive finite number" if not allow_zero else "a finite non-negative number"
        raise ValueError(f"{name} must be {qualifier}")


def validate(
    cues: list[Cue],
    source_cues: list[Cue],
    duration: float | None,
    tolerance: float,
    timing_tolerance: float,
    max_head_gap: float | None,
    max_tail_gap: float | None,
) -> dict[str, object]:
    require_finite_nonnegative("duration", duration, allow_zero=False)
    require_finite_nonnegative("duration tolerance", tolerance)
    require_finite_nonnegative("timing tolerance", timing_tolerance)
    require_finite_nonnegative("maximum head gap", max_head_gap)
    require_finite_nonnegative("maximum tail gap", max_tail_gap)
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
            first_cjk, first_latin = script_counts(cue.lines[0])
            last_cjk, last_latin = script_counts(cue.lines[-1])
            if not first_cjk:
                issues.append({"cue": cue.index, "type": "first_line_not_chinese"})
            if not last_latin:
                issues.append({"cue": cue.index, "type": "last_line_not_english"})
            if first_cjk and last_latin:
                first_cjk_ratio = first_cjk / (first_cjk + first_latin)
                last_cjk_ratio = last_cjk / (last_cjk + last_latin)
                if first_cjk_ratio <= last_cjk_ratio:
                    issues.append(
                        {
                            "cue": cue.index,
                            "type": "ambiguous_or_reversed_language_order",
                            "first_line_cjk_ratio": round(first_cjk_ratio, 4),
                            "last_line_cjk_ratio": round(last_cjk_ratio, 4),
                        }
                    )
    if len(cues) != len(source_cues):
        issues.append(
            {
                "type": "source_cue_count_mismatch",
                "source_cue_count": len(source_cues),
                "bilingual_cue_count": len(cues),
            }
        )
    for source, bilingual in zip(source_cues, cues):
        if source.index != bilingual.index:
            issues.append(
                {
                    "cue": bilingual.index,
                    "type": "source_numbering_mismatch",
                    "source_index": source.index,
                }
            )
        if (
            abs(source.start - bilingual.start) > timing_tolerance
            or abs(source.end - bilingual.end) > timing_tolerance
        ):
            issues.append(
                {
                    "cue": bilingual.index,
                    "type": "source_timing_mismatch",
                    "source_start": source.start,
                    "source_end": source.end,
                    "bilingual_start": bilingual.start,
                    "bilingual_end": bilingual.end,
                    "tolerance": timing_tolerance,
                }
            )
        source_lines = normalized_lines(source.lines)
        source_line_count = len(source_lines)
        bilingual_source_lines = (
            normalized_lines(bilingual.lines[-source_line_count:])
            if len(bilingual.lines) >= source_line_count
            else []
        )
        if bilingual_source_lines != source_lines:
            issues.append(
                {
                    "cue": bilingual.index,
                    "type": "source_text_mismatch",
                    "expected_source_lines": source_lines,
                    "bilingual_source_lines": bilingual_source_lines,
                }
            )
        translation_lines = (
            bilingual.lines[:-source_line_count]
            if len(bilingual.lines) >= source_line_count
            else []
        )
        for line_number, line in enumerate(translation_lines, start=1):
            cjk_count, latin_count = script_counts(line)
            if not cjk_count and latin_count:
                issues.append(
                    {
                        "cue": bilingual.index,
                        "type": "unexpected_english_line_before_source",
                        "line": line_number,
                        "text": line,
                    }
                )

    first_start = cues[0].start
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
    coverage_fix = (
        "Do not invent bilingual cues to close this gap. Listen to the media. "
        "If the gap is verified silent intro/outro, ask before widening the gap limit. "
        "If it contains speech missing from the source SRT, repair the audited English "
        "source with targeted interval re-transcription, then translate the added cues."
    )
    if max_head_gap is not None and first_start > max_head_gap:
        issues.append(
            {
                "cue": cues[0].index,
                "type": "video_head_coverage_gap",
                "head_gap_seconds": first_start,
                "maximum_seconds": max_head_gap,
                "suggested_fix": coverage_fix,
            }
        )
    tail_gap = None if duration is None else duration - last_end
    if max_tail_gap is not None and tail_gap is not None and tail_gap > max_tail_gap:
        issues.append(
            {
                "cue": cues[-1].index,
                "type": "video_tail_coverage_gap",
                "tail_gap_seconds": tail_gap,
                "maximum_seconds": max_tail_gap,
                "suggested_fix": coverage_fix,
            }
        )
    coverage_checked = (
        max_head_gap is not None
        and max_tail_gap is not None
        and duration is not None
    )
    warnings = []
    if not coverage_checked:
        warnings.append(
            "head/tail coverage was not fully checked; pass --video or --duration before treating this result as render-ready"
        )
    return {
        "status": "ok" if not issues else "error",
        "cue_count": len(cues),
        "source_cue_count": len(source_cues),
        "first_start_seconds": first_start,
        "last_end_seconds": last_end,
        "video_duration_seconds": duration,
        "tail_gap_seconds": tail_gap,
        "timing_tolerance_seconds": timing_tolerance,
        "max_head_gap_seconds": max_head_gap,
        "max_tail_gap_seconds": max_tail_gap,
        "coverage_checked": coverage_checked,
        "warnings": warnings,
        "issues": issues,
    }


def write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".report-{uuid.uuid4().hex}.tmp"
    try:
        temporary.write_text(text, encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def print_json(report: dict[str, object]) -> None:
    rendered = json.dumps(report, ensure_ascii=True, indent=2, allow_nan=False)
    try:
        print(rendered, flush=True)
    except (BrokenPipeError, OSError, UnicodeEncodeError, ValueError):
        try:
            stdout_fd = sys.stdout.fileno()
            null_fd = os.open(os.devnull, os.O_WRONLY)
            try:
                os.dup2(null_fd, stdout_fd)
            finally:
                os.close(null_fd)
        except Exception:
            pass


def validate_source_metadata(
    metadata: dict[str, object],
    source_srt_path: Path,
    expected_language: str,
) -> None:
    source_language = metadata.get("source_language")
    if not language_matches(source_language, expected_language):
        raise SourceLanguageError(
            f"source language {source_language!r} does not match required {expected_language!r}"
        )
    required_language = metadata.get("required_source_language")
    if not language_matches(required_language, expected_language):
        raise SourceMetadataError(
            "source metadata was not produced under the expected required-language gate"
        )
    origin = metadata.get("source_language_origin")
    if origin not in ALLOWED_SOURCE_LANGUAGE_ORIGINS:
        raise SourceMetadataError(f"unsupported source language origin: {origin!r}")
    if origin == "asr_detection":
        probability = metadata.get("source_language_probability")
        if (
            not isinstance(probability, (int, float))
            or isinstance(probability, bool)
            or not math.isfinite(float(probability))
            or float(probability) < MIN_ASR_LANGUAGE_PROBABILITY
        ):
            raise SourceMetadataError(
                f"ASR source language probability must be at least {MIN_ASR_LANGUAGE_PROBABILITY}"
            )
    if origin == "reviewed_source_handoff":
        required_fields = (
            "reviewed_by",
            "review_note",
            "upstream_metadata_sha256",
        )
        missing = [field for field in required_fields if not metadata.get(field)]
        if missing:
            raise SourceMetadataError(
                f"reviewed source handoff is missing evidence fields: {', '.join(missing)}"
            )
        audit_reports = metadata.get("audit_reports")
        if not isinstance(audit_reports, list) or not audit_reports:
            raise SourceMetadataError(
                "reviewed source handoff must include a non-empty audit report chain"
            )
    if metadata.get("source_srt_hash_algorithm") != "sha256":
        raise SourceMetadataError("source metadata must declare sha256")
    expected_hash = metadata.get("source_srt_sha256")
    actual_hash = hashlib.sha256(source_srt_path.read_bytes()).hexdigest()
    if not isinstance(expected_hash, str) or expected_hash.lower() != actual_hash:
        raise SourceMetadataError(
            "source metadata SHA-256 does not match the supplied source SRT"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a Chinese-first bilingual SRT.")
    parser.add_argument("srt", type=Path)
    parser.add_argument("--source-srt", type=Path, required=True)
    parser.add_argument("--source-metadata", type=Path, required=True, help="Transcription metadata proving the source language.")
    parser.add_argument("--expected-source-language", default="en")
    parser.add_argument("--video", type=Path, help="Optional video for duration validation")
    parser.add_argument("--duration", type=float, help="Video duration in seconds")
    parser.add_argument("--duration-tolerance", type=float, default=1.0)
    parser.add_argument("--timing-tolerance", type=float, default=0.001)
    parser.add_argument("--max-head-gap-seconds", type=float)
    parser.add_argument("--max-tail-gap-seconds", type=float)
    parser.add_argument("--output", type=Path, help="Write JSON report here")
    args = parser.parse_args()
    srt_path = args.srt.resolve()
    source_srt_path = args.source_srt.resolve()
    source_metadata_path = args.source_metadata.resolve()
    video_path = args.video.resolve() if args.video else None
    output_path = args.output.resolve() if args.output else None
    resolved_paths = [srt_path, source_srt_path, source_metadata_path]
    if video_path:
        resolved_paths.append(video_path)
    if output_path:
        resolved_paths.append(output_path)
    if len({file_identity(path) for path in resolved_paths}) != len(resolved_paths):
        print_json(
            {
                "status": "error",
                "reason": "path_collision",
                "message": "bilingual SRT, source SRT, source metadata, video, and report paths must all differ",
                "output_path": None if output_path is None else str(output_path),
            }
        )
        return 1
    try:
        if args.video and args.duration is not None:
            raise ValueError("use either --video or --duration, not both")
        duration = probe_duration(video_path) if video_path else args.duration
        source_metadata = json.loads(source_metadata_path.read_text(encoding="utf-8-sig"))
        if not isinstance(source_metadata, dict):
            raise ValueError("source metadata must be a JSON object")
        source_language = source_metadata.get("source_language")
        validate_source_metadata(
            source_metadata,
            source_srt_path,
            args.expected_source_language,
        )
        default_gap_limit = None if duration is None else max(30.0, duration * 0.1)
        max_head_gap = (
            args.max_head_gap_seconds
            if args.max_head_gap_seconds is not None
            else default_gap_limit
        )
        max_tail_gap = (
            args.max_tail_gap_seconds
            if args.max_tail_gap_seconds is not None
            else default_gap_limit
        )
        cues = parse_srt(srt_path)
        source_cues = parse_srt(source_srt_path)
        report = validate(
            cues,
            source_cues,
            duration,
            args.duration_tolerance,
            args.timing_tolerance,
            max_head_gap,
            max_tail_gap,
        )
        report["srt_path"] = str(srt_path)
        report["source_srt_path"] = str(source_srt_path)
        report["source_metadata_path"] = str(source_metadata_path)
        report["source_language"] = source_language
        report["expected_source_language"] = args.expected_source_language
        if video_path:
            report["video_path"] = str(video_path)
        exit_code = 0 if report["status"] == "ok" else 1
    except SourceLanguageError as exc:
        report = {
            "status": "error",
            "reason": "source_language_mismatch",
            "message": str(exc),
            "srt_path": str(args.srt),
            "source_metadata_path": str(source_metadata_path),
        }
        exit_code = 1
    except SourceMetadataError as exc:
        report = {
            "status": "error",
            "reason": "source_metadata_mismatch",
            "message": str(exc),
            "srt_path": str(args.srt),
            "source_srt_path": str(source_srt_path),
            "source_metadata_path": str(source_metadata_path),
        }
        exit_code = 1
    except (OSError, UnicodeError, ValueError) as exc:
        report = {
            "status": "error",
            "reason": "validation_failure",
            "message": str(exc),
            "srt_path": str(args.srt),
        }
        exit_code = 1
    rendered = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)
    try:
        if output_path:
            write_text_atomic(output_path, rendered + "\n")
            print_json(
                {
                    "status": report.get("status"),
                    "reason": report.get("reason"),
                    "cue_count": report.get("cue_count"),
                    "source_cue_count": report.get("source_cue_count"),
                    "issue_count": len(report.get("issues", [])),
                    "report_path": str(output_path),
                }
            )
        else:
            print_json(report)
        return exit_code
    except (OSError, UnicodeError, ValueError) as exc:
        print_json(
            {
                "status": "error",
                "reason": "report_write_failure",
                "message": str(exc),
                "output_path": None if output_path is None else str(output_path),
            }
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
