#!/usr/bin/env python3
"""Fetch YouTube channel publication metadata via RSS."""

from __future__ import annotations

import argparse
import difflib
import json
import logging
import random
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET


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


logger = logging.getLogger("youtube_channel_meta_skill")

RSS_BASE = "https://www.youtube.com/feeds/videos.xml?channel_id="
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
UA_PROFILES = [
    {
        "user_agent": USER_AGENT,
        "impersonate": "chrome131",
    },
    {
        "user_agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        ),
        "impersonate": "chrome131",
    },
]

ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}
YT_NS = {"yt": "http://www.youtube.com/xml/schemas/2015"}
MEDIA_NS = {"media": "http://search.yahoo.com/mrss/"}


@dataclass
class VideoItem:
    video_id: str
    title: str
    published_at: Optional[datetime]
    url: str
    channel_name: str
    channel_id: str
    description: str
    thumbnail_url: str
    rss_url: str
    duration_seconds: Optional[int] = None
    duration_text: Optional[str] = None
    source_type: str = "YouTube"

    def to_export_dict(self) -> Dict[str, Any]:
        item = asdict(self)
        item["published_at"] = self.published_at.isoformat() if self.published_at else None
        return item


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


def fetch_text(url: str, timeout: int) -> str:
    profile = random.choice(UA_PROFILES)

    try:
        from curl_cffi import requests as curl_requests  # type: ignore

        response = curl_requests.get(
            url,
            headers={
                "User-Agent": profile["user_agent"],
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": "https://www.youtube.com/",
            },
            impersonate=profile["impersonate"],
            timeout=timeout,
        )
        if response.status_code >= 400:
            raise RuntimeError(f"HTTP {response.status_code} for {url}: {response.text[:200]}")
        return response.text
    except ImportError:
        pass

    request = Request(
        url,
        headers={
            "User-Agent": profile["user_agent"],
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.youtube.com/",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.read().decode("utf-8", errors="replace")
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} for {url}: {body[:200]}") from exc
    except URLError as exc:
        raise RuntimeError(f"Network error for {url}: {exc}") from exc


def format_duration(seconds: Optional[int]) -> Optional[str]:
    if seconds is None:
        return None
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    remaining_seconds = seconds % 60
    if hours:
        return f"{hours}:{minutes:02d}:{remaining_seconds:02d}"
    return f"{minutes}:{remaining_seconds:02d}"


def extract_duration_seconds_from_html(html: str) -> Optional[int]:
    patterns = [
        r'"lengthSeconds":"(\d+)"',
        r'"approxDurationMs":"(\d+)"',
    ]
    for index, pattern in enumerate(patterns):
        match = re.search(pattern, html)
        if not match:
            continue
        value = int(match.group(1))
        if index == 1:
            return round(value / 1000)
        return value
    return None


def enrich_videos_with_duration(items: List[VideoItem], timeout: int) -> List[str]:
    warnings: List[str] = []
    for item in items:
        if not item.url:
            item.duration_seconds = None
            item.duration_text = None
            warnings.append(f"duration_missing_url:{item.video_id or 'unknown'}")
            continue
        try:
            html = fetch_text(item.url, timeout)
            item.duration_seconds = extract_duration_seconds_from_html(html)
            item.duration_text = format_duration(item.duration_seconds)
            if item.duration_seconds is None:
                warnings.append(f"duration_not_found:{item.video_id or item.url}")
        except RuntimeError:
            item.duration_seconds = None
            item.duration_text = None
            warnings.append(f"duration_fetch_failed:{item.video_id or item.url}")
    return warnings


def load_alias_map(alias_file: Path) -> Dict[str, str]:
    with alias_file.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)

    if isinstance(payload, dict):
        return {str(alias): str(channel_id) for alias, channel_id in payload.items()}

    if isinstance(payload, list):
        alias_map: Dict[str, str] = {}
        for index, item in enumerate(payload):
            if not isinstance(item, dict):
                raise ValueError(f"Invalid alias catalog entry at index {index}: expected object.")
            alias = item.get("alias")
            channel_id = item.get("channel_id")
            if not alias or not channel_id:
                raise ValueError(
                    f"Invalid alias catalog entry at index {index}: missing alias or channel_id."
                )
            alias_map[str(alias)] = str(channel_id)
        return alias_map

    raise ValueError("Alias file must be a JSON object or a JSON array of channel records.")


def normalize_target(target: str) -> str:
    value = target.strip()
    if not value:
        raise ValueError("Target cannot be empty.")
    return value


def suggest_aliases(target: str, alias_map: Dict[str, str], limit: int = 5) -> List[str]:
    aliases = list(alias_map.keys())
    return difflib.get_close_matches(target, aliases, n=limit, cutoff=0.4)


def resolve_channel_id(target: str, alias_map: Dict[str, str], timeout: int) -> Tuple[str, Optional[str], str]:
    raw_target = normalize_target(target)
    alias_lookup = {alias.lower(): (alias, channel_id) for alias, channel_id in alias_map.items()}

    if raw_target.lower() in alias_lookup:
        alias, channel_id = alias_lookup[raw_target.lower()]
        return channel_id, alias, "alias"

    if raw_target.upper().startswith("YT_"):
        suggestions = suggest_aliases(raw_target, alias_map)
        suggestion_text = f" Nearby aliases: {', '.join(suggestions)}." if suggestions else ""
        raise RuntimeError(f"Unknown YouTube alias: {raw_target}.{suggestion_text}")

    if re.fullmatch(r"UC[\w-]{10,}", raw_target):
        return raw_target, None, "channel_id"

    if raw_target.startswith("http://") or raw_target.startswith("https://"):
        resolution_source = classify_youtube_url(raw_target)
        channel_id = extract_channel_id_from_html(fetch_text(raw_target, timeout))
        if not channel_id:
            raise RuntimeError(f"Could not resolve channel ID from URL: {raw_target}")
        return channel_id, None, resolution_source

    handle = raw_target.lstrip("@")
    html = fetch_text(f"https://www.youtube.com/@{handle}", timeout)
    channel_id = extract_channel_id_from_html(html)
    if not channel_id:
        raise RuntimeError(f"Could not resolve channel ID from handle: {raw_target}")
    return channel_id, None, "handle"


def classify_youtube_url(url: str) -> str:
    value = url.lower()
    if "/watch?" in value or "youtu.be/" in value or "/shorts/" in value:
        return "video_url"
    if "/@" in value:
        return "handle_url"
    if "/channel/" in value or "/c/" in value or "/user/" in value:
        return "channel_url"
    return "url"


def extract_channel_id_from_html(html: str) -> Optional[str]:
    patterns = [
        r'itemprop="channelId"\s+content="(UC[\w-]+)"',
        r'"externalId":"(UC[\w-]+)"',
        r'"browseId":"(UC[\w-]+)"',
        r'"channelId":"(UC[\w-]+)"',
    ]
    for pattern in patterns:
        match = re.search(pattern, html)
        if match:
            return match.group(1)
    return None


def fetch_feed(channel_id: str, timeout: int) -> Tuple[str, str]:
    rss_url = f"{RSS_BASE}{channel_id}"
    return rss_url, fetch_text(rss_url, timeout)


def parse_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def text_or_empty(element: Optional[ET.Element]) -> str:
    if element is None or element.text is None:
        return ""
    return element.text.strip()


def parse_feed(xml_text: str, rss_url: str, fallback_channel_id: str) -> Tuple[str, str, List[VideoItem]]:
    root = ET.fromstring(xml_text)
    feed_channel_name = text_or_empty(root.find("atom:title", ATOM_NS))
    parsed_feed_channel_id = text_or_empty(root.find("yt:channelId", YT_NS))
    feed_channel_id = (
        parsed_feed_channel_id
        if re.fullmatch(r"UC[\w-]{10,}", parsed_feed_channel_id or "")
        else fallback_channel_id
    )
    entries: List[VideoItem] = []

    for entry in root.findall("atom:entry", ATOM_NS):
        video_id = text_or_empty(entry.find("yt:videoId", YT_NS))
        title = text_or_empty(entry.find("atom:title", ATOM_NS))
        published_at = parse_datetime(text_or_empty(entry.find("atom:published", ATOM_NS)))

        link_url = ""
        for link in entry.findall("atom:link", ATOM_NS):
            rel = (link.attrib.get("rel") or "").lower()
            href = link.attrib.get("href") or ""
            if rel in ("alternate", "") and href:
                link_url = href
                break

        author_name = text_or_empty(entry.find("atom:author/atom:name", ATOM_NS)) or feed_channel_name
        media_group = entry.find("media:group", MEDIA_NS)
        description = text_or_empty(
            media_group.find("media:description", MEDIA_NS) if media_group is not None else None
        )
        thumbnail_url = ""
        if media_group is not None:
            thumbnail = media_group.find("media:thumbnail", MEDIA_NS)
            if thumbnail is not None:
                thumbnail_url = thumbnail.attrib.get("url", "")

        entries.append(
            VideoItem(
                video_id=video_id,
                title=title,
                published_at=published_at,
                url=link_url,
                channel_name=author_name,
                channel_id=feed_channel_id,
                description=description,
                thumbnail_url=thumbnail_url,
                rss_url=rss_url,
            )
        )

    return feed_channel_name, feed_channel_id, entries


def compute_since_date(args: argparse.Namespace) -> Optional[str]:
    if args.since_date:
        return args.since_date
    if args.days_lookback is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=args.days_lookback)
        return cutoff.strftime("%Y-%m-%d")
    return None


def parse_date_arg(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def filter_videos(
    items: List[VideoItem],
    since_date: Optional[str],
    until_date: Optional[str],
) -> List[VideoItem]:
    since_dt = parse_date_arg(since_date)
    until_dt = parse_date_arg(until_date)
    if until_dt is not None:
        until_dt = until_dt.replace(hour=23, minute=59, second=59)

    filtered: List[VideoItem] = []
    for item in items:
        if item.published_at is None:
            continue
        if since_dt and item.published_at < since_dt:
            continue
        if until_dt and item.published_at > until_dt:
            continue
        filtered.append(item)
    return filtered


def validate_exports(
    items: List[Dict[str, Any]],
    resolved_channel_id: str,
    feed_channel_id: str,
    json_path: Path,
    md_path: Path,
    include_duration: bool,
) -> Dict[str, Any]:
    warnings: List[str] = []
    if not json_path.exists():
        warnings.append("json_output_missing")
    if not md_path.exists():
        warnings.append("markdown_output_missing")
    if any(not item.get("video_id") for item in items):
        warnings.append("missing_video_id")
    if any(not item.get("url") for item in items):
        warnings.append("missing_video_url")
    if include_duration and any(item.get("duration_seconds") is None for item in items):
        warnings.append("missing_video_duration")
    if feed_channel_id and feed_channel_id != resolved_channel_id:
        warnings.append("feed_channel_id_mismatch")
    if not items:
        warnings.append("empty_result")

    return {
        "ok": len(warnings) == 0,
        "warnings": warnings,
        "export_count": len(items),
        "resolved_channel_id": resolved_channel_id,
        "feed_channel_id": feed_channel_id,
        "json_exists": json_path.exists(),
        "markdown_exists": md_path.exists(),
    }


def render_markdown(
    items: List[Dict[str, Any]],
    query_target: str,
    resolved_alias: Optional[str],
    resolved_channel_id: str,
    resolution_source: str,
    since_date: Optional[str],
    until_date: Optional[str],
    effective_limit: int,
    validation: Dict[str, Any],
    include_duration: bool,
) -> str:
    lines = [
        f"# YouTube Scrape Result - {resolved_channel_id}",
        "",
        f"- Query Target: `{query_target}`",
        f"- Resolved Alias: `{resolved_alias or ''}`",
        f"- Resolved Channel ID: `{resolved_channel_id}`",
        f"- Resolution Source: `{resolution_source}`",
        f"- Since Date: `{since_date or ''}`",
        f"- Until Date: `{until_date or ''}`",
        f"- Effective Limit: `{effective_limit}`",
        f"- Video Count: `{len(items)}`",
        f"- Include Duration: `{include_duration}`",
        f"- Validation OK: `{validation['ok']}`",
        f"- Validation Warnings: `{', '.join(validation['warnings']) if validation['warnings'] else ''}`",
        "",
    ]

    for index, item in enumerate(items, start=1):
        lines.extend(
            [
                f"## {index}. {item['title'] or '(untitled)'}",
                "",
                f"- Published At: {item['published_at'] or ''}",
                f"- Video URL: {item['url'] or ''}",
                f"- Channel Name: {item['channel_name'] or ''}",
                f"- Channel ID: {item['channel_id'] or ''}",
                f"- Duration Seconds: {item.get('duration_seconds') if item.get('duration_seconds') is not None else ''}",
                f"- Duration Text: {item.get('duration_text') or ''}",
                f"- Thumbnail URL: {item['thumbnail_url'] or ''}",
                "",
                "### Description",
                "",
                item["description"] or "(empty)",
                "",
            ]
        )

    return "\n".join(lines)


def build_output_paths(output_dir: Path, label: str) -> Tuple[Path, Path]:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_label = re.sub(r"[^a-zA-Z0-9_.-]+", "_", label)
    json_path = output_dir / f"{safe_label}_{timestamp}.json"
    md_path = output_dir / f"{safe_label}_{timestamp}.md"
    return json_path, md_path


def default_output_dir() -> Path:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return Path(f"youtube-{timestamp}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch YouTube channel publication metadata via RSS.",
        formatter_class=SmartDefaultsFormatter,
    )
    parser.add_argument(
        "target",
        help="Required. Alias, @handle, channel URL, video URL, or channel ID to resolve.",
    )
    parser.add_argument(
        "--alias-file",
        default=None,
        help=(
            "Optional. Path to alias mapping JSON used for configured channel shortcuts. "
            "If omitted, uses {SKILL_ROOT}/defaults/youtube_channels.json."
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        help=(
            "Optional. Maximum number of final videos to keep. If omitted, the script keeps up to 20 items "
            "for open-ended queries, or up to 100 items when a date filter is active."
        ),
    )
    parser.add_argument(
        "--days-lookback",
        type=int,
        help=(
            "Optional. Relative lookback window in days. If omitted, no relative date filter is applied. "
            "Mutually exclusive with --since-date."
        ),
    )
    parser.add_argument(
        "--since-date",
        help=(
            "Optional. Absolute range start in YYYY-MM-DD. If omitted, no start-date filter is applied. "
            "Mutually exclusive with --days-lookback."
        ),
    )
    parser.add_argument(
        "--until-date",
        help="Optional. Absolute range end in YYYY-MM-DD. If omitted, no end-date filter is applied.",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help=(
            "Optional. Directory where JSON and Markdown outputs will be written. "
            "If omitted, creates a timestamped directory like ./youtube-YYYYMMDD-HHMMSS."
        ),
    )
    parser.add_argument(
        "--request-timeout",
        type=int,
        default=30,
        help="Optional. HTTP request timeout in seconds for RSS and page fetches.",
    )
    parser.add_argument(
        "--skip-duration",
        action="store_true",
        help=(
            "Optional flag. If omitted, the script fetches each video page to enrich results with duration "
            "metadata. Set this flag to skip duration enrichment."
        ),
    )
    return parser.parse_args()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = parse_args()
    if args.alias_file is None:
        args.alias_file = str(Path(__file__).resolve().parents[1] / "defaults" / "youtube_channels.json")

    if args.days_lookback is not None and args.since_date:
        exit_with_error(
            error_type="invalid_arguments",
            failed_step="validate_args",
            message="Use either --days-lookback or --since-date, not both.",
            retryable=False,
        )
    if args.limit is not None and args.limit <= 0:
        exit_with_error(
            error_type="invalid_arguments",
            failed_step="validate_args",
            message="--limit must be > 0.",
            retryable=False,
        )

    alias_map = load_alias_map(Path(args.alias_file))
    try:
        resolved_channel_id, resolved_alias, resolution_source = resolve_channel_id(
            args.target, alias_map, args.request_timeout
        )
    except RuntimeError as exc:
        message = str(exc)
        suggestion = None
        retryable = False
        error_type = "target_resolution_failed"
        if "Unknown YouTube alias" in message:
            suggestion = "Use a nearby alias match or pass a direct channel_id."
        elif "Could not resolve channel ID" in message:
            suggestion = "Pass a direct channel_id if you know it."
            retryable = True
        elif "Network error" in message or "HTTP " in message:
            suggestion = "Retry the request or try again with a direct channel URL/channel_id."
            retryable = True
            error_type = "network_error"
        exit_with_error(
            error_type=error_type,
            failed_step="resolve_target",
            message=message,
            retryable=retryable,
            suggestion=suggestion,
            details={"target": args.target},
        )
    since_date = compute_since_date(args)
    output_dir = Path(args.output_dir) if args.output_dir else default_output_dir()
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        rss_url, xml_text = fetch_feed(resolved_channel_id, args.request_timeout)
    except RuntimeError as exc:
        exit_with_error(
            error_type="feed_fetch_failed",
            failed_step="fetch_feed",
            message=str(exc),
            retryable=True,
            suggestion="Retry later or pass a direct channel_id to skip handle resolution.",
            details={"resolved_channel_id": resolved_channel_id},
        )
    feed_channel_name, feed_channel_id, items = parse_feed(xml_text, rss_url, resolved_channel_id)
    items = filter_videos(items, since_date=since_date, until_date=args.until_date)
    items.sort(key=lambda item: item.published_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)

    final_limit = args.limit if args.limit is not None else (100 if since_date or args.until_date else 20)
    items = items[:final_limit]
    duration_warnings: List[str] = []
    include_duration = not args.skip_duration
    if include_duration:
        duration_warnings = enrich_videos_with_duration(items, args.request_timeout)
    exports = [item.to_export_dict() for item in items]

    label = resolved_alias or feed_channel_name or resolved_channel_id
    json_path, md_path = build_output_paths(output_dir, label)
    with json_path.open("w", encoding="utf-8") as handle:
        json.dump(
            {
                "query_target": args.target,
                "resolved_alias": resolved_alias,
                "resolved_channel_id": resolved_channel_id,
                "resolution_source": resolution_source,
                "feed_channel_name": feed_channel_name,
                "feed_channel_id": feed_channel_id,
                "since_date": since_date,
                "until_date": args.until_date,
                "effective_limit": final_limit,
                "include_duration": include_duration,
                "target_kind": resolution_source,
                "video_count": len(exports),
                "items": exports,
            },
            handle,
            ensure_ascii=False,
            indent=2,
        )

    markdown = render_markdown(
        items=exports,
        query_target=args.target,
        resolved_alias=resolved_alias,
        resolved_channel_id=resolved_channel_id,
        resolution_source=resolution_source,
        since_date=since_date,
        until_date=args.until_date,
        effective_limit=final_limit,
        validation={"ok": True, "warnings": []},
        include_duration=include_duration,
    )
    with md_path.open("w", encoding="utf-8") as handle:
        handle.write(markdown)

    validation = validate_exports(
        items=exports,
        resolved_channel_id=resolved_channel_id,
        feed_channel_id=feed_channel_id,
        json_path=json_path,
        md_path=md_path,
        include_duration=include_duration,
    )
    validation["warnings"].extend(duration_warnings)
    validation["warnings"] = list(dict.fromkeys(validation["warnings"]))
    validation["ok"] = len(validation["warnings"]) == 0

    with json_path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    payload["status"] = "ok" if validation["ok"] else "ok_with_warnings"
    payload["validation"] = validation
    with json_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)

    markdown = render_markdown(
        items=exports,
        query_target=args.target,
        resolved_alias=resolved_alias,
        resolved_channel_id=resolved_channel_id,
        resolution_source=resolution_source,
        since_date=since_date,
        until_date=args.until_date,
        effective_limit=final_limit,
        validation=validation,
        include_duration=include_duration,
    )
    with md_path.open("w", encoding="utf-8") as handle:
        handle.write(markdown)

    print(
        json.dumps(
            {
                "status": "ok" if validation["ok"] else "ok_with_warnings",
                "resolved_channel_id": resolved_channel_id,
                "resolved_alias": resolved_alias,
                "resolution_source": resolution_source,
                "since_date": since_date,
                "until_date": args.until_date,
                "effective_limit": final_limit,
                "include_duration": include_duration,
                "video_count": len(exports),
                "json_path": str(json_path),
                "markdown_path": str(md_path),
                "validation": validation,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
