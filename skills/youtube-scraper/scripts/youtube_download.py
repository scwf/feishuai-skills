#!/usr/bin/env python3
"""Download a YouTube video or an audio-only file on explicit request."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from console_output import emit_stdout_json


class SmartDefaultsFormatter(argparse.ArgumentDefaultsHelpFormatter):
    """Show defaults only when they add signal for end users."""

    def _get_help_string(self, action: argparse.Action) -> str:
        help_text = action.help or ""
        if "%(default)" in help_text:
            return help_text
        if action.required:
            return help_text
        if action.default in (None, False, argparse.SUPPRESS):
            return help_text
        return super()._get_help_string(action)


def structured_error(
    error_type: str,
    failed_step: str,
    message: str,
    retryable: bool,
    suggestion: str | None = None,
    details: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "status": "error",
        "error_type": error_type,
        "failed_step": failed_step,
        "message": message,
        "retryable": retryable,
    }
    if suggestion:
        payload["suggestion"] = suggestion
    if details:
        payload["details"] = details
    return payload


def exit_with_error(
    error_type: str,
    failed_step: str,
    message: str,
    retryable: bool,
    suggestion: str | None = None,
    details: Dict[str, Any] | None = None,
) -> "NoReturn":
    emit_stdout_json(
        structured_error(
            error_type=error_type,
            failed_step=failed_step,
            message=message,
            retryable=retryable,
            suggestion=suggestion,
            details=details,
        )
    )
    raise SystemExit(1)


def get_yt_dlp_module():
    try:
        import yt_dlp  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "Missing Python dependency `yt_dlp`. Install it with `pip install yt-dlp`."
        ) from exc
    return yt_dlp


def normalize_url(url: str) -> str:
    value = url.strip()
    if not value:
        raise ValueError("URL cannot be empty.")
    if not re.match(r"^https?://", value, flags=re.IGNORECASE):
        raise ValueError("A full YouTube URL is required.")
    return value


def build_paths(output_dir: Path, label: str) -> tuple[Path, Path]:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_label = re.sub(r"[^a-zA-Z0-9_.-]+", "_", label).strip("._") or "youtube"
    sidecar_path = output_dir / f"{safe_label}_{timestamp}.download.json"
    return output_dir, sidecar_path


def default_output_dir() -> Path:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return Path(f"youtube-{timestamp}")


def make_output_template(output_dir: Path) -> str:
    return str(output_dir / "%(title).200B [%(id)s].%(ext)s")


def collect_payload(
    mode: str,
    source_url: str,
    output_path: Path,
    info: Dict[str, Any],
    sidecar_path: Path,
) -> Dict[str, Any]:
    return {
        "status": "ok",
        "mode": mode,
        "source_url": source_url,
        "resolved_url": info.get("webpage_url") or source_url,
        "video_id": info.get("id"),
        "title": info.get("title"),
        "channel_name": info.get("channel") or info.get("uploader"),
        "channel_id": info.get("channel_id"),
        "uploader": info.get("uploader"),
        "duration_seconds": info.get("duration"),
        "description": info.get("description"),
        "extractor": info.get("extractor"),
        "ext": output_path.suffix.lstrip("."),
        "output_path": str(output_path),
        "sidecar_path": str(sidecar_path),
    }


def build_console_summary(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "status": payload.get("status"),
        "mode": payload.get("mode"),
        "video_id": payload.get("video_id"),
        "output_path": payload.get("output_path"),
        "sidecar_path": payload.get("sidecar_path"),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download a YouTube video or audio-only file on explicit request.",
        formatter_class=SmartDefaultsFormatter,
    )
    parser.add_argument(
        "url",
        help="Required. YouTube video URL to download.",
    )
    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument(
        "--download-video",
        action="store_true",
        help="Required mode choice. Download the video file.",
    )
    mode_group.add_argument(
        "--extract-audio",
        action="store_true",
        help="Required mode choice. Download an audio-only media file.",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help=(
            "Optional. Directory where the media file and sidecar JSON will be written. "
            "If omitted, creates a timestamped directory like ./youtube-YYYYMMDD-HHMMSS."
        ),
    )
    parser.add_argument(
        "--request-timeout",
        type=int,
        default=60,
        help="Optional. Network timeout in seconds for downloader requests.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    try:
        source_url = normalize_url(args.url)
    except ValueError as exc:
        exit_with_error(
            error_type="invalid_arguments",
            failed_step="validate_args",
            message=str(exc),
            retryable=False,
        )

    output_dir = Path(args.output_dir) if args.output_dir else default_output_dir()
    output_dir.mkdir(parents=True, exist_ok=True)
    mode = "audio" if args.extract_audio else "video"
    _, sidecar_path = build_paths(output_dir, mode)

    try:
        yt_dlp = get_yt_dlp_module()
    except RuntimeError as exc:
        exit_with_error(
            error_type="missing_dependency",
            failed_step="import_yt_dlp",
            message=str(exc),
            retryable=False,
        )

    ydl_opts: Dict[str, Any] = {
        "outtmpl": make_output_template(output_dir),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": args.request_timeout,
    }
    if mode == "audio":
        ydl_opts["format"] = "bestaudio/best"
    else:
        ydl_opts["format"] = "bestvideo*+bestaudio/best"
        ydl_opts["merge_output_format"] = "mp4"

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(source_url, download=True)
            output_path = Path(ydl.prepare_filename(info))
            requested_downloads = info.get("requested_downloads") or []
            if requested_downloads and requested_downloads[0].get("filepath"):
                output_path = Path(requested_downloads[0]["filepath"])
            final_requested = info.get("requested_formats") or []
            if final_requested:
                possible = output_path.with_suffix(".mp4")
                if possible.exists():
                    output_path = possible
    except Exception as exc:
        message = str(exc)
        if "ffmpeg is not installed" in message.lower():
            suggestion = "Install ffmpeg or retry with `--extract-audio` if audio-only output is acceptable."
        else:
            suggestion = "Retry later or try a different public YouTube video URL."
        exit_with_error(
            error_type="download_failed",
            failed_step="yt_dlp_download",
            message=message,
            retryable=True,
            suggestion=suggestion,
            details={"url": source_url, "mode": mode},
        )

    if not output_path.exists():
        matches = sorted(output_dir.glob("*"), key=lambda path: path.stat().st_mtime, reverse=True)
        media_files = [path for path in matches if path.is_file() and path.suffix != ".json"]
        if media_files:
            output_path = media_files[0]

    if not output_path.exists():
        exit_with_error(
            error_type="download_failed",
            failed_step="validate_output",
            message="yt-dlp reported success but no output media file was found.",
            retryable=False,
            suggestion="Retry the download and inspect the output directory.",
            details={"output_dir": str(output_dir), "mode": mode},
        )

    payload = collect_payload(
        mode=mode,
        source_url=source_url,
        output_path=output_path,
        info=info,
        sidecar_path=sidecar_path,
    )
    with sidecar_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)

    emit_stdout_json(build_console_summary(payload))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
