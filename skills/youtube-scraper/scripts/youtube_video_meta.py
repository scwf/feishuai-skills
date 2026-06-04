#!/usr/bin/env python3
"""Fetch metadata for one YouTube video without downloading media."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional


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
    suggestion: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
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
    suggestion: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
) -> "NoReturn":
    print(
        json.dumps(
            structured_error(
                error_type=error_type,
                failed_step=failed_step,
                message=message,
                retryable=retryable,
                suggestion=suggestion,
                details=details,
            ),
            ensure_ascii=False,
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
        raise ValueError("A full YouTube video URL is required.")
    lowered = value.lower()
    if not any(marker in lowered for marker in ("youtube.com/watch?", "youtu.be/", "youtube.com/shorts/")):
        raise ValueError("A YouTube watch, youtu.be, or shorts URL is required.")
    return value


def default_output_dir() -> Path:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return Path(f"youtube-video-{timestamp}")


def build_output_paths(output_dir: Path, label: str) -> tuple[Path, Path]:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_label = re.sub(r"[^a-zA-Z0-9_.-]+", "_", label).strip("._") or "youtube_video"
    return output_dir / f"{safe_label}_{timestamp}.json", output_dir / f"{safe_label}_{timestamp}.md"


def format_duration(seconds: Optional[int]) -> Optional[str]:
    if seconds is None:
        return None
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    remaining_seconds = seconds % 60
    if hours:
        return f"{hours}:{minutes:02d}:{remaining_seconds:02d}"
    return f"{minutes}:{remaining_seconds:02d}"


def normalize_upload_date(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    if re.fullmatch(r"\d{8}", value):
        return f"{value[:4]}-{value[4:6]}-{value[6:]}"
    return value


def first_thumbnail(info: Dict[str, Any]) -> str:
    thumbnails = info.get("thumbnails") or []
    if not isinstance(thumbnails, list):
        return ""
    for thumbnail in reversed(thumbnails):
        if isinstance(thumbnail, dict) and thumbnail.get("url"):
            return str(thumbnail["url"])
    return ""


def collect_payload(
    source_url: str,
    info: Dict[str, Any],
    json_path: Path,
    markdown_path: Path,
) -> Dict[str, Any]:
    duration_seconds = info.get("duration")
    if duration_seconds is not None:
        try:
            duration_seconds = int(duration_seconds)
        except (TypeError, ValueError):
            duration_seconds = None

    return {
        "status": "ok",
        "mode": "single_video_metadata",
        "source_url": source_url,
        "resolved_url": info.get("webpage_url") or source_url,
        "video_id": info.get("id"),
        "title": info.get("title"),
        "published_at": normalize_upload_date(info.get("upload_date")),
        "channel_name": info.get("channel") or info.get("uploader"),
        "channel_id": info.get("channel_id"),
        "uploader": info.get("uploader"),
        "duration_seconds": duration_seconds,
        "duration_text": format_duration(duration_seconds),
        "description": info.get("description") or "",
        "thumbnail_url": info.get("thumbnail") or first_thumbnail(info),
        "extractor": info.get("extractor"),
        "json_path": str(json_path),
        "markdown_path": str(markdown_path),
    }


def validate_payload(payload: Dict[str, Any], json_path: Path, markdown_path: Path) -> Dict[str, Any]:
    warnings = []
    if not json_path.exists():
        warnings.append("json_output_missing")
    if not markdown_path.exists():
        warnings.append("markdown_output_missing")
    if not payload.get("video_id"):
        warnings.append("missing_video_id")
    if not payload.get("title"):
        warnings.append("missing_title")
    if not payload.get("description"):
        warnings.append("missing_description")
    if not payload.get("channel_id"):
        warnings.append("missing_channel_id")

    return {
        "ok": len(warnings) == 0,
        "warnings": warnings,
        "json_exists": json_path.exists(),
        "markdown_exists": markdown_path.exists(),
        "video_id": payload.get("video_id"),
    }


def render_markdown(payload: Dict[str, Any], validation: Dict[str, Any]) -> str:
    return "\n".join(
        [
            f"# YouTube Video Metadata - {payload.get('video_id') or 'unknown'}",
            "",
            f"- Source URL: {payload.get('source_url') or ''}",
            f"- Resolved URL: {payload.get('resolved_url') or ''}",
            f"- Video ID: {payload.get('video_id') or ''}",
            f"- Title: {payload.get('title') or ''}",
            f"- Published At: {payload.get('published_at') or ''}",
            f"- Channel Name: {payload.get('channel_name') or ''}",
            f"- Channel ID: {payload.get('channel_id') or ''}",
            f"- Duration Seconds: {payload.get('duration_seconds') if payload.get('duration_seconds') is not None else ''}",
            f"- Duration Text: {payload.get('duration_text') or ''}",
            f"- Thumbnail URL: {payload.get('thumbnail_url') or ''}",
            f"- Validation OK: `{validation['ok']}`",
            f"- Validation Warnings: `{', '.join(validation['warnings']) if validation['warnings'] else ''}`",
            "",
            "## Description",
            "",
            payload.get("description") or "(empty)",
            "",
        ]
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch metadata for one YouTube video without downloading media.",
        formatter_class=SmartDefaultsFormatter,
    )
    parser.add_argument(
        "url",
        help="Required. YouTube watch, youtu.be, or shorts URL.",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help=(
            "Optional. Directory where JSON and Markdown outputs will be written. "
            "If omitted, creates a timestamped directory like ./youtube-video-YYYYMMDD-HHMMSS."
        ),
    )
    parser.add_argument(
        "--request-timeout",
        type=int,
        default=60,
        help="Optional. Network timeout in seconds for metadata requests.",
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

    try:
        yt_dlp = get_yt_dlp_module()
    except RuntimeError as exc:
        exit_with_error(
            error_type="missing_dependency",
            failed_step="import_yt_dlp",
            message=str(exc),
            retryable=False,
        )

    output_dir = Path(args.output_dir) if args.output_dir else default_output_dir()
    output_dir.mkdir(parents=True, exist_ok=True)

    ydl_opts: Dict[str, Any] = {
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "socket_timeout": args.request_timeout,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(source_url, download=False)
    except Exception as exc:
        exit_with_error(
            error_type="metadata_fetch_failed",
            failed_step="yt_dlp_extract_info",
            message=str(exc),
            retryable=True,
            suggestion="Retry later or try a different public YouTube video URL.",
            details={"url": source_url},
        )

    label = str(info.get("id") or "youtube_video")
    json_path, markdown_path = build_output_paths(output_dir, label)
    payload = collect_payload(source_url, info, json_path, markdown_path)

    with json_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)

    validation = validate_payload(payload, json_path, markdown_path)
    payload["status"] = "ok" if validation["ok"] else "ok_with_warnings"
    payload["validation"] = validation

    markdown = render_markdown(payload, validation)
    with markdown_path.open("w", encoding="utf-8") as handle:
        handle.write(markdown)

    validation = validate_payload(payload, json_path, markdown_path)
    validation["ok"] = len(validation["warnings"]) == 0
    payload["status"] = "ok" if validation["ok"] else "ok_with_warnings"
    payload["validation"] = validation

    with json_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)

    markdown = render_markdown(payload, validation)
    with markdown_path.open("w", encoding="utf-8") as handle:
        handle.write(markdown)

    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
