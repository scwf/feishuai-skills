#!/usr/bin/env python3
"""Extract and format X posts from a batch directory by category."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract X posts by category from a batch.")
    parser.add_argument(
        "--batch-dir",
        default="~/data/x-daily/latest",
        help="Path to an x-scraper batch directory, or to a pointer directory with meta.json containing batch_dir.",
    )
    parser.add_argument(
        "--category",
        required=True,
        help="Category key from batch_category_index.json",
    )
    parser.add_argument("--output", help="Optional output file path; defaults to stdout")
    return parser.parse_args()


def load_json(path: Path) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        raise ValueError(f"Failed to load JSON from {path}: {exc}") from exc


def format_post(item: Dict[str, Any], account_label: str) -> str:
    """Format a single post into a concise text block."""
    username = item.get("username", "")
    display_name = item.get("display_name", username)
    created_at = item.get("created_at", "")
    is_rt = item.get("is_retweet", False)

    # Prefer full retweeted original text; fallback to original_text
    text = ""
    if is_rt and item.get("retweeted_original_text"):
        text = item["retweeted_original_text"]
    else:
        text = item.get("original_text", "")

    # Metrics
    metrics = item.get("metrics", {})
    view_count = metrics.get("view_count", 0)
    like_count = metrics.get("like_count", 0)
    retweet_count = metrics.get("retweet_count", 0)

    # URLs
    urls = item.get("urls", [])
    url_str = " ".join(urls) if urls else ""

    # Post URL
    post_url = item.get("url", "")

    lines = [
        f"[@{username} / {display_name}] · {created_at}",
    ]
    if is_rt:
        lines.append("[RT]")
    lines.append(text)
    lines.append(f"[互动: 浏览{view_count} · 赞{like_count} · 转{retweet_count}]")
    if url_str:
        lines.append(f"[链接: {url_str}]")
    if post_url:
        lines.append(f"[原文: {post_url}]")
    lines.append("——")
    return "\n".join(lines)


def extract_category(batch_dir: Path, category: str) -> str:
    index_path = batch_dir / "batch_category_index.json"
    if not index_path.exists():
        raise FileNotFoundError(f"Category index not found: {index_path}")

    index = load_json(index_path)

    categories = index.get("categories", {})
    if category not in categories:
        available = ", ".join(categories.keys())
        raise ValueError(f"Unknown category '{category}'. Available: {available}")

    raw_root = Path(index.get("raw_root", str(batch_dir / "raw")))
    if not raw_root.is_absolute():
        raw_root = batch_dir / raw_root

    files = categories[category]

    output_lines: List[str] = []
    output_lines.append(f"# X Posts Category: {category}")
    output_lines.append(f"# Batch: {batch_dir}")
    output_lines.append(f"# Accounts: {len(files)}")
    output_lines.append("")

    total_posts = 0
    for filename in files:
        json_path = raw_root / filename
        if not json_path.exists():
            output_lines.append(f"[WARN] File not found: {json_path}")
            continue

        try:
            data = load_json(json_path)
        except ValueError as exc:
            output_lines.append(f"[WARN] {exc}")
            continue

        items = data.get("items", [])
        if not items:
            continue

        account_label = data.get("resolved_username", filename.replace(".json", ""))
        output_lines.append(f"## Account: @{account_label} ({len(items)} posts)")
        output_lines.append("")
        for item in items:
            output_lines.append(format_post(item, account_label))
            total_posts += 1
        output_lines.append("")

    output_lines.insert(3, f"# Total Posts: {total_posts}")
    return "\n".join(output_lines)


def main() -> None:
    args = parse_args()
    latest_dir = Path(args.batch_dir).expanduser().resolve()

    # If pointing to the latest marker dir, resolve actual batch via meta.json
    if latest_dir.name == "latest":
        meta_path = latest_dir / "meta.json"
        if not meta_path.exists():
            raise FileNotFoundError(
                f"Default latest pointer not found: {meta_path}. "
                "Pass --batch-dir with an x-scraper batch directory."
            )
        meta = load_json(meta_path)
        if meta.get("batch_dir"):
            batch_dir = Path(meta["batch_dir"]).expanduser().resolve()
        else:
            raise ValueError("meta.json missing batch_dir field")
    else:
        batch_dir = latest_dir

    result = extract_category(batch_dir, args.category)

    if args.output:
        out_path = Path(args.output)
        out_path.write_text(result, encoding="utf-8")
        print(f"Extracted {args.category} to {out_path}")
    else:
        print(result)


if __name__ == "__main__":
    main()
