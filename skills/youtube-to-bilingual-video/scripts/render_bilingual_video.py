#!/usr/bin/env python3
"""Burn bilingual SRT subtitles into a video and verify before promotion."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import re
import shutil
import subprocess
import sys
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import BinaryIO, Iterator

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from path_safety import UnsafeLockPathError, file_identity, open_safe_lock_file


CJK_RE = re.compile(r"[\u3400-\u9fff]")
WORD_RE = re.compile(r"[A-Za-z0-9]+(?:['’][A-Za-z0-9]+)?")
SRT_TIMING_RE = re.compile(
    r"^(\d{2}):(\d{2}):(\d{2}),(\d{3})\s*-->\s*"
    r"(\d{2}):(\d{2}):(\d{2}),(\d{3})$"
)
DEFAULT_MARGIN_L = 10
DEFAULT_MARGIN_R = 10
DEFAULT_WRAP_STYLE = 1
ASS_PLAY_RES_Y = 288


def run(
    command: list[str], *, check: bool = True, cwd: Path | None = None
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=cwd,
    )
    if check and result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"command failed ({result.returncode}): {detail}")
    return result


def require_tool(name: str) -> str:
    resolved = shutil.which(name)
    if not resolved:
        raise RuntimeError(f"required executable not found on PATH: {name}")
    return resolved


def probe(path: Path) -> dict[str, object]:
    result = run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(path),
        ]
    )
    return json.loads(result.stdout)


def duration_seconds(data: dict[str, object]) -> float:
    format_data = data.get("format", {})
    if not isinstance(format_data, dict) or "duration" not in format_data:
        raise RuntimeError("ffprobe did not report media duration")
    return float(format_data["duration"])


def stream_types(data: dict[str, object]) -> list[str]:
    streams = data.get("streams", [])
    if not isinstance(streams, list):
        return []
    return [
        str(item.get("codec_type"))
        for item in streams
        if isinstance(item, dict) and item.get("codec_type")
    ]


def video_dimensions(data: dict[str, object]) -> tuple[int, int]:
    streams = data.get("streams", [])
    if isinstance(streams, list):
        for item in streams:
            if not isinstance(item, dict) or item.get("codec_type") != "video":
                continue
            width = item.get("width")
            height = item.get("height")
            if isinstance(width, int) and width > 0 and isinstance(height, int) and height > 0:
                return width, height
    raise RuntimeError("ffprobe did not report positive video dimensions")


def default_font() -> str:
    system = platform.system()
    if system == "Windows":
        return "Microsoft YaHei"
    if system == "Darwin":
        return "PingFang SC"
    return "Noto Sans CJK SC"


def encoder_available(encoder: str) -> bool:
    listed = run(["ffmpeg", "-hide_banner", "-encoders"], check=False)
    if encoder not in listed.stdout:
        return False
    if encoder != "h264_nvenc":
        return True
    probe_result = run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=size=32x32:rate=1:duration=0.1",
            "-c:v",
            "h264_nvenc",
            "-f",
            "null",
            "-",
        ],
        check=False,
    )
    return probe_result.returncode == 0


def choose_encoder(requested: str) -> str:
    if requested == "auto":
        return "h264_nvenc" if encoder_available("h264_nvenc") else "libx264"
    if not encoder_available(requested):
        raise RuntimeError(f"requested encoder is unavailable: {requested}")
    return requested


def escape_filter_path(path: Path) -> str:
    value = str(path.resolve() if path.is_absolute() else path).replace("\\", "/")
    value = value.replace("'", r"\'").replace(":", r"\:")
    value = value.replace("[", r"\[").replace("]", r"\]")
    return value


def subtitle_filter(
    subtitle: Path,
    font: str,
    font_size: float,
    margin_v: int,
    outline: float,
    *,
    margin_l: int = DEFAULT_MARGIN_L,
    margin_r: int = DEFAULT_MARGIN_R,
    wrap_style: int = DEFAULT_WRAP_STYLE,
    wrap_unicode: bool = True,
) -> str:
    safe_font = font.replace("'", "").replace(",", " ")
    style = (
        f"FontName={safe_font},FontSize={font_size:g},"
        "PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,"
        f"BorderStyle=1,Outline={outline:g},Shadow=0,Alignment=2,"
        f"MarginL={margin_l},MarginR={margin_r},MarginV={margin_v},"
        f"WrapStyle={wrap_style}"
    )
    unicode_option = ":wrap_unicode=1" if wrap_unicode else ""
    return (
        f"subtitles=filename='{escape_filter_path(subtitle)}'"
        f"{unicode_option}:force_style='{style}'"
    )


def subtitle_filter_supports_wrap_unicode() -> bool:
    result = run(["ffmpeg", "-hide_banner", "-h", "filter=subtitles"], check=False)
    return result.returncode == 0 and "wrap_unicode" in result.stdout


def _timestamp_seconds(values: tuple[str, str, str, str]) -> float:
    hours, minutes, seconds, millis = (int(value) for value in values)
    return hours * 3600 + minutes * 60 + seconds + millis / 1000


def _join_layout_lines(lines: list[str]) -> str:
    parts = [line.strip() for line in lines if line.strip()]
    if not parts:
        raise ValueError("bilingual layout contains an empty language section")
    joined = parts[0]
    for part in parts[1:]:
        previous = joined[-1]
        following = part[0]
        needs_space = (
            previous.isascii()
            and following.isascii()
            and previous not in "([{/-–—'\""
            and following not in ".,!?;:%)]}'\""
        )
        joined += (" " if needs_space else "") + part
    return joined


def _display_width_units(text: str) -> float:
    return sum(
        1.0
        if CJK_RE.fullmatch(character)
        else 0.33
        if character.isspace()
        else 0.55
        if character.isascii() and character.isalnum()
        else 0.5
        for character in text
    )


def _estimated_line_count(
    text: str,
    *,
    video_width: int,
    video_height: int,
    font_size: float,
    margin_l: int,
    margin_r: int,
) -> int:
    script_width = ASS_PLAY_RES_Y * video_width / video_height
    available_em = max(1.0, (script_width - margin_l - margin_r) / font_size)
    return max(1, math.ceil(_display_width_units(text) / available_em))


def _layout_text_and_metrics(
    subtitle: Path,
    *,
    source_line_counts: list[int],
    video_width: int = 1920,
    video_height: int = 1080,
    font_size: float = 16.0,
    margin_l: int = DEFAULT_MARGIN_L,
    margin_r: int = DEFAULT_MARGIN_R,
) -> tuple[str, list[dict[str, object]], int]:
    raw = subtitle.read_text(encoding="utf-8-sig").replace("\r\n", "\n").strip()
    if not raw:
        raise ValueError("bilingual SRT is empty")
    blocks = re.split(r"\n{2,}", raw)
    if len(source_line_counts) != len(blocks):
        raise ValueError("source line counts do not match bilingual cue count")
    rendered_blocks: list[str] = []
    metrics: list[dict[str, object]] = []
    normalized_count = 0
    for position, block in enumerate(blocks, start=1):
        lines = block.splitlines()
        if len(lines) < 4:
            raise ValueError(f"bilingual cue {position} has fewer than two text lines")
        try:
            cue = int(lines[0].strip())
        except ValueError as exc:
            raise ValueError(f"bilingual cue {position} has an invalid index") from exc
        timing = lines[1].strip()
        match = SRT_TIMING_RE.fullmatch(timing)
        if not match:
            raise ValueError(f"bilingual cue {cue} has invalid timing")
        text_lines = [line.strip() for line in lines[2:] if line.strip()]
        source_line_count = source_line_counts[position - 1]
        if source_line_count >= len(text_lines):
            raise ValueError(f"bilingual cue {cue} has no Chinese language section")
        chinese = _join_layout_lines(text_lines[:-source_line_count])
        english = _join_layout_lines(text_lines[-source_line_count:])
        if len(text_lines) != 2:
            normalized_count += 1
        start = _timestamp_seconds(match.groups()[:4])
        end = _timestamp_seconds(match.groups()[4:])
        cjk_count = len(CJK_RE.findall(chinese))
        chinese_lines = _estimated_line_count(
            chinese,
            video_width=video_width,
            video_height=video_height,
            font_size=font_size,
            margin_l=margin_l,
            margin_r=margin_r,
        )
        english_lines = _estimated_line_count(
            english,
            video_width=video_width,
            video_height=video_height,
            font_size=font_size,
            margin_l=margin_l,
            margin_r=margin_r,
        )
        metrics.append(
            {
                "cue": cue,
                "start_seconds": start,
                "end_seconds": end,
                "duration_seconds": round(end - start, 3),
                "chinese_display_chars": len(chinese),
                "chinese_cjk_chars": cjk_count,
                "english_display_chars": len(english),
                "english_word_count": len(WORD_RE.findall(english)),
                "original_hard_line_count": len(text_lines),
                "normalized_line_count": 2,
                "estimated_chinese_lines": chinese_lines,
                "estimated_english_lines": english_lines,
                "estimated_total_lines": chinese_lines + english_lines,
                "display_load_score": cjk_count * 2
                + (len(chinese) - cjk_count)
                + len(english),
            }
        )
        rendered_blocks.append(f"{cue}\n{timing}\n{chinese}\n{english}")
    return "\n\n".join(rendered_blocks) + "\n", metrics, normalized_count


def prepare_layout_subtitle(
    subtitle: Path,
    work_dir: Path,
    *,
    source_line_counts: list[int],
    video_width: int = 1920,
    video_height: int = 1080,
    font_size: float = 16.0,
) -> tuple[Path, dict[str, object], list[dict[str, object]]]:
    text, metrics, normalized_count = _layout_text_and_metrics(
        subtitle,
        source_line_counts=source_line_counts,
        video_width=video_width,
        video_height=video_height,
        font_size=font_size,
    )
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    layout_dir = work_dir / "layout"
    layout_dir.mkdir(parents=True, exist_ok=True)
    layout_path = layout_dir / f"bilingual-layout-{digest[:12]}.srt"
    if layout_path.exists():
        if layout_path.read_text(encoding="utf-8") != text:
            raise RuntimeError(f"layout subtitle digest collision: {layout_path}")
    else:
        temporary = layout_dir / f".layout-{uuid.uuid4().hex}.tmp"
        try:
            temporary.write_text(text, encoding="utf-8", newline="\n")
            temporary.replace(layout_path)
        finally:
            temporary.unlink(missing_ok=True)
    return (
        layout_path,
        {
            "layout_subtitle_path": str(layout_path.resolve()),
            "layout_subtitle_sha256": digest,
            "layout_normalized": True,
            "hard_line_normalized_cue_count": normalized_count,
        },
        metrics,
    )


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_validation_report(
    report_path: Path, subtitle: Path
) -> dict[str, object]:
    try:
        report = json.loads(report_path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RenderError(
            f"could not parse bilingual validation report: {report_path}",
            reason="validation_report_mismatch",
        ) from exc
    if not isinstance(report, dict):
        raise RenderError(
            "bilingual validation report must be a JSON object",
            reason="validation_report_mismatch",
        )
    if report.get("status") != "ok":
        raise RenderError(
            "bilingual validation report is not successful",
            reason="validation_report_mismatch",
        )
    if report.get("coverage_checked") is not True:
        raise RenderError(
            "bilingual validation report did not verify media head/tail coverage",
            reason="validation_report_mismatch",
        )
    expected_hash = report.get("srt_sha256")
    actual_hash = sha256(subtitle)
    if not isinstance(expected_hash, str) or expected_hash.lower() != actual_hash:
        raise RenderError(
            "bilingual validation report SHA-256 does not match the subtitle",
            reason="validation_report_mismatch",
        )
    relaxed = report.get("source_qc_limits_relaxed_from_default")
    authorized = report.get("source_qc_relaxed_limits_authorized")
    if not isinstance(relaxed, bool) or not isinstance(authorized, bool):
        raise RenderError(
            "bilingual validation report is missing source QC relaxation evidence",
            reason="validation_report_mismatch",
        )
    if relaxed and not authorized:
        raise RenderError(
            "bilingual validation report carries unauthorized relaxed source QC limits",
            reason="validation_report_mismatch",
        )
    source_line_counts = report.get("source_line_counts")
    if (
        not isinstance(source_line_counts, list)
        or not source_line_counts
        or any(
            isinstance(count, bool) or not isinstance(count, int) or count <= 0
            for count in source_line_counts
        )
    ):
        raise RenderError(
            "bilingual validation report is missing valid source line counts",
            reason="validation_report_mismatch",
        )
    return report


def restore_archived_output(archive: Path, output: Path, expected_digest: str) -> None:
    if not archive.exists():
        raise FileNotFoundError(f"expected archive is missing: {archive}")
    temporary = output.parent / f".restore-{output.name}-{uuid.uuid4().hex}.tmp"
    try:
        shutil.copy2(archive, temporary)
        candidate_digest = sha256(temporary)
        if candidate_digest != expected_digest:
            raise OSError(
                f"archive digest mismatch before restore: expected {expected_digest}, "
                f"got {candidate_digest}"
            )
        temporary.replace(output)
        if not output.is_file():
            raise OSError(f"restored canonical output is missing: {output}")
        restored_digest = sha256(output)
        if restored_digest != expected_digest:
            raise OSError(
                f"restored output digest mismatch: expected {expected_digest}, "
                f"got {restored_digest}"
            )
    finally:
        temporary.unlink(missing_ok=True)


def publish_verified_render(
    partial: Path, output: Path, work_dir: Path, run_id: str
) -> str | None:
    archive: Path | None = None
    archive_digest: str | None = None
    archive_moved = False
    try:
        if output.exists():
            archive_dir = work_dir / "archive"
            archive_dir.mkdir(parents=True, exist_ok=True)
            output_digest = hashlib.sha256(str(output).encode("utf-8")).hexdigest()[:12]
            archive = archive_dir / f"previous-{output_digest}-{run_id}{output.suffix}"
            archive_digest = sha256(output)
            output.replace(archive)
            archive_moved = True
        partial.replace(output)
        return str(archive.resolve()) if archive_moved and archive is not None else None
    except Exception as publish_error:
        rollback_error: Exception | None = None
        if archive_moved and archive is not None:
            try:
                if archive_digest is None:
                    raise OSError("archived output digest was not recorded")
                restore_archived_output(archive, output, archive_digest)
            except Exception as exc:
                rollback_error = exc
        archive_evidence = (
            str(archive.resolve())
            if archive is not None and archive.exists()
            else None
        )
        if rollback_error is not None:
            raise RenderError(
                "verified render publication failed and the previous output could not be restored; "
                f"archive evidence: {archive_evidence or 'unavailable'}; {rollback_error}",
                reason="rollback_failure",
                suggested_fix="Recover the reported archive evidence before retrying the render.",
                details={"archived_previous_output": archive_evidence},
            ) from publish_error
        recovery_note = (
            "the previous output was restored"
            if archive_moved
            else "the previous output was not moved"
        )
        raise RenderError(
            f"verified render publication failed: {publish_error}",
            reason="publish_failure",
            suggested_fix=f"Resolve the filesystem error and retry; {recovery_note}.",
            details={"archived_previous_output": archive_evidence},
        ) from publish_error


def select_qa_samples(
    duration: float,
    requested: list[float],
    cue_metrics: list[dict[str, object]],
    *,
    high_load_count: int = 5,
) -> list[dict[str, object]]:
    selected: dict[float, dict[str, object]] = {}

    def add_sample(
        timestamp: float,
        reason: str,
        *,
        cue_metric: dict[str, object] | None = None,
    ) -> None:
        if not 0 <= timestamp < duration:
            return
        key = round(timestamp, 3)
        item = selected.setdefault(
            key,
            {"time_seconds": key, "selection_reasons": []},
        )
        reasons = item["selection_reasons"]
        if isinstance(reasons, list) and reason not in reasons:
            reasons.append(reason)
        if cue_metric is not None:
            item["cue"] = cue_metric["cue"]
            item["load_metrics"] = {
                field: cue_metric[field]
                for field in (
                    "duration_seconds",
                    "chinese_display_chars",
                    "chinese_cjk_chars",
                    "english_display_chars",
                    "english_word_count",
                    "original_hard_line_count",
                    "normalized_line_count",
                    "estimated_chinese_lines",
                    "estimated_english_lines",
                    "estimated_total_lines",
                    "display_load_score",
                )
            }

    defaults = (
        (min(5.0, duration / 4), "ordinary_start"),
        (duration / 2, "ordinary_middle"),
        (max(0.0, duration - 5), "ordinary_end"),
    )
    for timestamp, reason in defaults:
        add_sample(timestamp, reason)
    for timestamp in requested:
        add_sample(timestamp, "user_requested")
    ranked = sorted(
        cue_metrics,
        key=lambda item: (-int(item["display_load_score"]), int(item["cue"])),
    )[:high_load_count]
    for metric in ranked:
        midpoint = (float(metric["start_seconds"]) + float(metric["end_seconds"])) / 2
        add_sample(midpoint, "high_subtitle_load", cue_metric=metric)
    return [selected[key] for key in sorted(selected)]


def layout_limit_findings(
    cue_metrics: list[dict[str, object]],
) -> list[dict[str, object]]:
    return [
        {
            "cue": metric["cue"],
            "estimated_chinese_lines": metric["estimated_chinese_lines"],
            "estimated_english_lines": metric["estimated_english_lines"],
            "estimated_total_lines": metric["estimated_total_lines"],
        }
        for metric in cue_metrics
        if int(metric["estimated_chinese_lines"]) > 2
        or int(metric["estimated_english_lines"]) > 2
        or int(metric["estimated_total_lines"]) > 4
    ]


def extract_frames(video: Path, qa_dir: Path, times: list[float]) -> list[str]:
    qa_dir.mkdir(parents=True, exist_ok=True)
    paths: list[str] = []
    for number, timestamp in enumerate(times, start=1):
        frame = qa_dir / f"qa-{number:02d}-{timestamp:.3f}s.png"
        run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-ss",
                f"{timestamp:.3f}",
                "-i",
                str(video),
                "-frames:v",
                "1",
                "-y",
                str(frame),
            ]
        )
        paths.append(str(frame.resolve()))
    return paths


def write_report(report: dict[str, object], report_path: Path) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = report_path.parent / f".report-{uuid.uuid4().hex}.tmp"
    try:
        temporary.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(report_path)
    finally:
        temporary.unlink(missing_ok=True)


def print_json(report: dict[str, object]) -> None:
    rendered = json.dumps(report, ensure_ascii=True, indent=2)
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


def bounded_text(value: object, limit: int = 1000) -> object:
    if not isinstance(value, str) or len(value) <= limit:
        return value
    return value[:limit] + "...[truncated]"


def print_report_summary(report: dict[str, object], report_path: Path) -> None:
    warnings = report.get("warnings", [])
    bounded_warnings = (
        [bounded_text(item, 500) for item in warnings[:10]]
        if isinstance(warnings, list)
        else []
    )
    print_json(
        {
            "status": report.get("status"),
            "reason": report.get("reason"),
            "message": bounded_text(report.get("message")),
            "suggested_fix": bounded_text(report.get("suggested_fix")),
            "output": report.get("output"),
            "warnings": bounded_warnings,
            "report_path": str(report_path),
        }
    )


def report_write_failure(report_path: Path, exc: Exception) -> dict[str, object]:
    return {
        "status": "error",
        "reason": "report_write_failure",
        "message": str(exc),
        "report_path": str(report_path),
    }


class RenderError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        reason: str,
        suggested_fix: str | None = None,
        details: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.reason = reason
        self.suggested_fix = suggested_fix
        self.details = details or {}


def validate_style_arguments(args: argparse.Namespace) -> None:
    if not math.isfinite(args.font_size) or args.font_size <= 0:
        raise RenderError(
            "font size must be a positive finite number",
            reason="invalid_render_style",
        )
    if not math.isfinite(args.outline) or args.outline < 0 or args.margin_v < 0:
        raise RenderError(
            "outline and vertical margin must be finite non-negative values",
            reason="invalid_render_style",
        )


def _lock_handle(handle: BinaryIO) -> None:
    handle.seek(0)
    if not handle.read(1):
        handle.seek(0)
        handle.write(b"0")
        handle.flush()
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock_handle(handle: BinaryIO) -> None:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def output_lock(output: Path) -> Iterator[Path]:
    lock_key = file_identity(output)
    digest = hashlib.sha256(lock_key.encode("utf-8")).hexdigest()[:16]
    lock_path = output.parent / f".render-{digest}.lock"
    try:
        handle = open_safe_lock_file(lock_path)
    except (OSError, UnsafeLockPathError) as exc:
        raise RenderError(
            f"render lock path is not a safe single-link regular file: {lock_path}",
            reason="unsafe_lock_path",
            suggested_fix="Remove or quarantine the unsafe lock path, then retry.",
        ) from exc
    try:
        try:
            _lock_handle(handle)
        except OSError as exc:
            raise RenderError(
                f"another render is already targeting this output: {output}",
                reason="output_locked",
                suggested_fix="Wait for the active render to finish, then retry.",
            ) from exc
        try:
            yield lock_path
        finally:
            try:
                _unlock_handle(handle)
            except Exception:
                pass
    finally:
        try:
            handle.close()
        except Exception:
            pass


def render_run_id() -> str:
    return f"{datetime.now():%Y%m%d-%H%M%S-%f}-{os.getpid()}-{uuid.uuid4().hex}"


def render(args: argparse.Namespace) -> dict[str, object]:
    validate_style_arguments(args)
    require_tool("ffmpeg")
    require_tool("ffprobe")
    source = args.input_video.resolve()
    subtitle = args.subtitle.resolve()
    validation_report_path = args.validation_report.resolve()
    output = args.output.resolve()
    work_dir = args.work_dir.resolve()
    if not source.is_file():
        raise RuntimeError(f"input video does not exist: {source}")
    if not subtitle.is_file():
        raise RuntimeError(f"subtitle does not exist: {subtitle}")
    if not validation_report_path.is_file():
        raise RenderError(
            f"bilingual validation report does not exist: {validation_report_path}",
            reason="validation_report_mismatch",
        )
    validation_handoff = load_validation_report(validation_report_path, subtitle)
    output.parent.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)
    with output_lock(output):
        return render_locked(
            args,
            source,
            subtitle,
            output,
            work_dir,
            validation_report_path=validation_report_path,
            validation_handoff=validation_handoff,
        )


def render_locked(
    args: argparse.Namespace,
    source: Path,
    subtitle: Path,
    output: Path,
    work_dir: Path,
    *,
    validation_report_path: Path | None = None,
    validation_handoff: dict[str, object] | None = None,
) -> dict[str, object]:
    if output.exists() and not args.replace_existing:
        raise RuntimeError("output already exists; pass --replace-existing to archive and replace it")

    run_id = render_run_id()
    partial = work_dir / f".render-{run_id}.partial.mp4"
    selected_encoder = choose_encoder(args.encoder)
    source_probe = probe(source)
    source_duration = duration_seconds(source_probe)
    source_types = stream_types(source_probe)
    if "video" not in source_types:
        raise RuntimeError("input has no video stream")
    source_width, source_height = video_dimensions(source_probe)
    if "audio" not in source_types and not args.allow_silent:
        raise RenderError(
            "input has no audio stream",
            reason="missing_audio_stream",
            suggested_fix=(
                "Ask the user whether a silent final video is acceptable. "
                "Retry with --allow-silent only after explicit acceptance."
            ),
        )

    temporary_subtitle: Path | None = None
    layout_info: dict[str, object] = {}
    cue_metrics: list[dict[str, object]] = []
    if validation_handoff is not None:
        render_subtitle, layout_info, cue_metrics = prepare_layout_subtitle(
            subtitle,
            work_dir,
            source_line_counts=validation_handoff["source_line_counts"],
            video_width=source_width,
            video_height=source_height,
            font_size=args.font_size,
        )
    else:
        temporary_subtitle = work_dir / f".render-subtitle-{run_id}.srt"
        shutil.copy2(subtitle, temporary_subtitle)
        render_subtitle = temporary_subtitle
    wrap_unicode = subtitle_filter_supports_wrap_unicode()
    subtitle_argument = (
        render_subtitle.relative_to(work_dir)
        if render_subtitle.is_relative_to(work_dir)
        else render_subtitle
    )
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(source),
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
        "-vf",
        subtitle_filter(
            subtitle_argument,
            args.font_name or default_font(),
            args.font_size,
            args.margin_v,
            args.outline,
            wrap_unicode=wrap_unicode,
        ),
        "-c:v",
        selected_encoder,
    ]
    if selected_encoder == "h264_nvenc":
        command.extend(["-preset", "p7", "-tune", "hq", "-rc", "vbr", "-cq", "18", "-b:v", "0"])
    else:
        command.extend(["-preset", "medium", "-crf", "18"])
    command.extend(
        [
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            "-y",
            str(partial),
        ]
    )
    try:
        run(command, cwd=work_dir)
    finally:
        if temporary_subtitle is not None:
            temporary_subtitle.unlink(missing_ok=True)

    output_probe = probe(partial)
    output_duration = duration_seconds(output_probe)
    output_types = stream_types(output_probe)
    if "video" not in output_types:
        raise RuntimeError("rendered file has no video stream")
    if "audio" in source_types and "audio" not in output_types:
        raise RuntimeError("rendered file lost the source audio stream")
    tolerance = max(1.0, source_duration * 0.005)
    if abs(source_duration - output_duration) > tolerance:
        raise RuntimeError(
            f"duration mismatch: source={source_duration:.3f}s output={output_duration:.3f}s"
        )

    decode = run(
        [
            "ffmpeg",
            "-hide_banner",
            "-v",
            "error",
            "-i",
            str(partial),
            "-map",
            "0:v:0",
            "-map",
            "0:a?",
            "-f",
            "null",
            "-",
        ],
        check=False,
    )
    if decode.returncode != 0 or decode.stderr.strip():
        raise RuntimeError(f"full decode scan failed: {decode.stderr.strip()}")

    qa_samples = select_qa_samples(output_duration, args.qa_time, cue_metrics)
    frame_paths = extract_frames(
        partial,
        work_dir / "qa",
        [float(item["time_seconds"]) for item in qa_samples],
    )
    qa_sample_reports = [
        {**sample, "frame_path": frame_path}
        for sample, frame_path in zip(qa_samples, frame_paths)
    ]
    layout_findings = layout_limit_findings(cue_metrics)
    review_candidate: Path | None = None
    if layout_findings:
        review_dir = work_dir / "review"
        review_dir.mkdir(parents=True, exist_ok=True)
        review_candidate = review_dir / f"review-required-{run_id}.mp4"
        partial.replace(review_candidate)
        archived = None
        verified_artifact = review_candidate
    else:
        archived = publish_verified_render(partial, output, work_dir, run_id)
        verified_artifact = output
    warnings = (
        ["source and rendered output are intentionally silent"]
        if "audio" not in source_types
        else []
    )
    if cue_metrics:
        warnings.append("high-load QA frames require viewer-facing inspection")
    if layout_findings:
        warnings.append("estimated subtitle line limits exceeded; candidate is not deliverable")
    report = {
        "status": "review_required" if layout_findings else "ok",
        "input_video": str(source),
        "subtitle": str(subtitle),
        "requested_output": str(output),
        "output": None if review_candidate is not None else str(output),
        "review_candidate": (
            None if review_candidate is None else str(review_candidate.resolve())
        ),
        "archived_previous_output": archived,
        "encoder": selected_encoder,
        "font_name": args.font_name or default_font(),
        "font_size": args.font_size,
        "margin_l": DEFAULT_MARGIN_L,
        "margin_r": DEFAULT_MARGIN_R,
        "margin_v": args.margin_v,
        "wrap_style": DEFAULT_WRAP_STYLE,
        "wrap_unicode": wrap_unicode,
        "source_duration_seconds": source_duration,
        "video_width": source_width,
        "video_height": source_height,
        "output_duration_seconds": output_duration,
        "duration_tolerance_seconds": tolerance,
        "source_stream_types": source_types,
        "output_stream_types": output_types,
        "full_decode_scan": "ok",
        "warnings": warnings,
        "qa_frames": frame_paths,
        "qa_samples": qa_sample_reports,
        "qa_high_load_count": sum(
            1
            for item in qa_sample_reports
            if "high_subtitle_load" in item["selection_reasons"]
        ),
        "qa_review_required": bool(cue_metrics),
        "layout_review_required": bool(layout_findings),
        "layout_limit_findings": layout_findings,
        "output_size_bytes": (
            None if review_candidate is not None else verified_artifact.stat().st_size
        ),
        "output_sha256": (
            None if review_candidate is not None else sha256(verified_artifact)
        ),
        "review_candidate_size_bytes": (
            verified_artifact.stat().st_size if review_candidate is not None else None
        ),
        "review_candidate_sha256": (
            sha256(verified_artifact) if review_candidate is not None else None
        ),
    }
    report.update(layout_info)
    if validation_report_path is not None:
        report["validation_report_path"] = str(validation_report_path.resolve())
        report["validation_report_sha256"] = sha256(validation_report_path)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Render and verify a bilingual subtitled MP4.")
    parser.add_argument("--input-video", type=Path, required=True)
    parser.add_argument("--subtitle", type=Path, required=True)
    parser.add_argument(
        "--validation-report",
        type=Path,
        required=True,
        help="Successful current bilingual validation report bound to --subtitle.",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--font-name")
    parser.add_argument("--font-size", type=float, default=16.0)
    parser.add_argument("--margin-v", type=int, default=8)
    parser.add_argument("--outline", type=float, default=1.5)
    parser.add_argument("--encoder", choices=["auto", "h264_nvenc", "libx264"], default="auto")
    parser.add_argument("--qa-time", action="append", type=float, default=[])
    parser.add_argument("--replace-existing", action="store_true")
    parser.add_argument(
        "--allow-silent",
        action="store_true",
        help="Allow a source with no audio stream. Use only after the user explicitly accepts a silent final video.",
    )
    parser.add_argument("--report", type=Path, help="Defaults to <work-dir>/render-report.json")
    args = parser.parse_args()
    report_path = (args.report or args.work_dir / "render-report.json").resolve()
    resolved_paths = {
        "input_video": args.input_video.resolve(),
        "subtitle": args.subtitle.resolve(),
        "validation_report": args.validation_report.resolve(),
        "output": args.output.resolve(),
        "report": report_path,
    }
    protected_paths = {
        args.input_video.resolve(),
        args.subtitle.resolve(),
        args.validation_report.resolve(),
        args.output.resolve(),
    }
    path_identities = {name: file_identity(path) for name, path in resolved_paths.items()}
    protected_path_identities = {file_identity(path) for path in protected_paths}
    if len(set(path_identities.values())) != len(path_identities):
        report = {
            "status": "error",
            "reason": "path_collision",
            "message": "input video, subtitle, validation report, rendered output, and report paths must all differ",
            "input_video": str(args.input_video),
            "subtitle": str(args.subtitle),
            "validation_report": str(args.validation_report),
            "output": str(args.output),
            "report": str(report_path),
        }
        try:
            if file_identity(report_path) not in protected_path_identities:
                write_report(report, report_path)
            print_report_summary(report, report_path)
        except (OSError, UnicodeError, ValueError) as exc:
            print_json(report_write_failure(report_path, exc))
        return 1
    try:
        report = render(args)
        exit_code = 2 if report.get("status") == "review_required" else 0
    except RenderError as exc:
        report = {
            "status": "error",
            "reason": exc.reason,
            "message": str(exc),
            "input_video": str(args.input_video),
            "subtitle": str(args.subtitle),
            "output": str(args.output),
        }
        if exc.suggested_fix:
            report["suggested_fix"] = exc.suggested_fix
        if exc.details:
            report["details"] = exc.details
        exit_code = 1
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        report = {
            "status": "error",
            "message": str(exc),
            "input_video": str(args.input_video),
            "subtitle": str(args.subtitle),
            "output": str(args.output),
        }
        exit_code = 1
    try:
        write_report(report, report_path)
        print_report_summary(report, report_path)
        return exit_code
    except (OSError, UnicodeError, ValueError) as exc:
        print_json(report_write_failure(report_path, exc))
        return 1


if __name__ == "__main__":
    sys.exit(main())
