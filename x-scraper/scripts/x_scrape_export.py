from __future__ import annotations

import re
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def render_markdown(
    items: List[Dict[str, Any]],
    query_target: str,
    resolved_username: str,
    resolved_alias: Optional[str],
    mode: str,
    limit: Optional[int],
    max_fetch: Optional[int],
    since_date: Optional[str],
    until_date: Optional[str],
    run_status: str,
    pages_fetched: int,
    partial_failure_reason: Optional[str],
) -> str:
    lines = [
        f"# X Scrape Raw Result - @{resolved_username}",
        "",
        f"- Query Target: `{query_target}`",
        f"- Resolved Username: `@{resolved_username}`",
        f"- Resolved Alias: `{resolved_alias or ''}`",
        f"- Mode: `{mode}`",
        f"- Limit: `{limit if limit is not None else ''}`",
        f"- Max Fetch: `{max_fetch if max_fetch is not None else ''}`",
        f"- Since Date: `{since_date or ''}`",
        f"- Until Date: `{until_date or ''}`",
        f"- Run Status: `{run_status}`",
        f"- Pages Fetched: `{pages_fetched}`",
        f"- Tweet Count: `{len(items)}`",
        "",
    ]

    if partial_failure_reason:
        lines.extend(
            [
                "## Run Notes",
                "",
                f"- Partial Failure Reason: `{partial_failure_reason}`",
                "",
            ]
        )

    for index, item in enumerate(items, start=1):
        retweet_block = []
        if item.get("is_retweet"):
            retweet_block = [
                "",
                "### Retweet Info",
                "",
                f"- Retweeted From: @{item.get('retweeted_from_username') or ''}",
                f"- Retweeted Original URL: {item.get('retweeted_original_url') or ''}",
                "",
                item.get("retweeted_original_text") or "(missing retweeted original text)",
                "",
            ]
        lines.extend(
            [
                f"## {index}. {item['display_name']} (@{item['username']})",
                "",
                f"- Date: {item['created_at'] or ''}",
                f"- URL: {item['url']}",
                f"- Is Retweet: {item.get('is_retweet', False)}",
                "",
                "### Original",
                "",
                item["original_text"] or "(empty)",
                "",
                *retweet_block,
            ]
        )

    return "\n".join(lines)


def build_output_paths(output_dir: Path, username: str) -> Tuple[Path, Path]:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    safe_username = re.sub(r"[^a-zA-Z0-9_.-]+", "_", username)
    run_dir = output_dir / f"x-posts-{timestamp}"
    json_path = run_dir / f"{safe_username}.json"
    md_path = run_dir / f"{safe_username}.md"
    return json_path, md_path


def build_run_metadata(
    *,
    args: Any,
    resolved_username: str,
    resolved_alias: Optional[str],
    mode: str,
    limit: Optional[int],
    max_fetch: Optional[int],
    since_date: Optional[str],
    run_result: Any,
    exports: List[Dict[str, Any]],
    env_file_used: bool,
) -> Dict[str, Any]:
    metadata = OrderedDict(
        [
            ("query_target", args.target),
            ("resolved_username", resolved_username),
            ("resolved_alias", resolved_alias),
            ("mode", mode),
            ("limit", limit),
            ("max_fetch", max_fetch),
            ("since_date", since_date),
            ("until_date", args.until_date),
            ("retweet_mode", args.retweet_mode),
            ("run_status", run_result.status),
            ("pages_fetched", run_result.pages_fetched),
            ("partial_failure_reason", run_result.partial_failure_reason),
            ("env_file_used", env_file_used),
            ("tweet_count", len(exports)),
            ("items", exports),
        ]
    )
    return dict(metadata)
