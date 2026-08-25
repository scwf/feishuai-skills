#!/usr/bin/env python3
"""Burn bilingual SRT subtitles into a video and verify before promotion."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
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
    subtitle: Path, font: str, font_size: float, margin_v: int, outline: float
) -> str:
    safe_font = font.replace("'", "").replace(",", " ")
    style = (
        f"FontName={safe_font},FontSize={font_size:g},"
        "PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,"
        f"BorderStyle=1,Outline={outline:g},Shadow=0,Alignment=2,MarginV={margin_v}"
    )
    return f"subtitles=filename='{escape_filter_path(subtitle)}':force_style='{style}'"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def qa_times(duration: float, requested: list[float]) -> list[float]:
    candidates = requested or [min(5.0, duration / 4), duration / 2, max(0.0, duration - 5)]
    valid = {round(value, 3) for value in candidates if 0 <= value < duration}
    return sorted(valid)


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
    require_tool("ffmpeg")
    require_tool("ffprobe")
    source = args.input_video.resolve()
    subtitle = args.subtitle.resolve()
    output = args.output.resolve()
    work_dir = args.work_dir.resolve()
    if not source.is_file():
        raise RuntimeError(f"input video does not exist: {source}")
    if not subtitle.is_file():
        raise RuntimeError(f"subtitle does not exist: {subtitle}")
    output.parent.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)
    with output_lock(output):
        return render_locked(args, source, subtitle, output, work_dir)


def render_locked(
    args: argparse.Namespace,
    source: Path,
    subtitle: Path,
    output: Path,
    work_dir: Path,
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
    if "audio" not in source_types and not args.allow_silent:
        raise RenderError(
            "input has no audio stream",
            reason="missing_audio_stream",
            suggested_fix=(
                "Ask the user whether a silent final video is acceptable. "
                "Retry with --allow-silent only after explicit acceptance."
            ),
        )

    staged_subtitle = work_dir / f".render-subtitle-{run_id}.srt"
    shutil.copy2(subtitle, staged_subtitle)
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
            Path(staged_subtitle.name),
            args.font_name or default_font(),
            args.font_size,
            args.margin_v,
            args.outline,
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
        staged_subtitle.unlink(missing_ok=True)

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

    frame_paths = extract_frames(
        partial, work_dir / "qa", qa_times(output_duration, args.qa_time)
    )
    archived = publish_verified_render(partial, output, work_dir, run_id)
    return {
        "status": "ok",
        "input_video": str(source),
        "subtitle": str(subtitle),
        "output": str(output),
        "archived_previous_output": archived,
        "encoder": selected_encoder,
        "font_name": args.font_name or default_font(),
        "font_size": args.font_size,
        "margin_v": args.margin_v,
        "source_duration_seconds": source_duration,
        "output_duration_seconds": output_duration,
        "duration_tolerance_seconds": tolerance,
        "source_stream_types": source_types,
        "output_stream_types": output_types,
        "full_decode_scan": "ok",
        "warnings": (
            ["source and rendered output are intentionally silent"]
            if "audio" not in source_types
            else []
        ),
        "qa_frames": frame_paths,
        "output_size_bytes": output.stat().st_size,
        "output_sha256": sha256(output),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Render and verify a bilingual subtitled MP4.")
    parser.add_argument("--input-video", type=Path, required=True)
    parser.add_argument("--subtitle", type=Path, required=True)
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
        "output": args.output.resolve(),
        "report": report_path,
    }
    protected_paths = {
        args.input_video.resolve(),
        args.subtitle.resolve(),
        args.output.resolve(),
    }
    path_identities = {name: file_identity(path) for name, path in resolved_paths.items()}
    protected_path_identities = {file_identity(path) for path in protected_paths}
    if len(set(path_identities.values())) != len(path_identities):
        report = {
            "status": "error",
            "reason": "path_collision",
            "message": "input video, subtitle, rendered output, and report paths must all differ",
            "input_video": str(args.input_video),
            "subtitle": str(args.subtitle),
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
        exit_code = 0
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
