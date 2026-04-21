#!/usr/bin/env python3
"""Batch X scraper built on top of the single-target scraper."""

from __future__ import annotations

import argparse
import json
import logging
import os
import random
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import x_scrape
from x_scrape_env import load_default_env

logger = logging.getLogger("x_scrape_batch")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch X tweets for multiple targets with batch pacing and stop-on-rate-limit behavior.",
        epilog=(
            "Defaults: --batch-size 10, --target-delay-min/max 10/30, "
            "--batch-delay-min/max 60/120, --retweet-mode include, --max-fetch 500. "
            "Only pass non-default switches when they are required by the request."
        ),
    )
    parser.add_argument(
        "targets",
        help=(
            "Required. Comma-separated aliases/usernames, or a text file path with one target per line."
        ),
    )
    parser.add_argument(
        "--alias-file",
        default=str(Path(__file__).resolve().parents[1] / "config" / "x_target_accounts.json"),
        help="Target account list JSON. Default: config/x_target_accounts.json.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help=(
            "Maximum number of final tweets to return per target. "
            "Default: 20 in count mode; no final limit in time-range mode unless explicitly set."
        ),
    )
    parser.add_argument(
        "--max-fetch",
        type=int,
        default=500,
        help="Maximum number of tweets to scan internally in time-range mode only. Default: 500.",
    )
    parser.add_argument("--days-lookback", type=int, help="Relative lookback window in days. Optional.")
    parser.add_argument("--since-date", help="Absolute range start in YYYY-MM-DD. Optional.")
    parser.add_argument("--until-date", help="Absolute range end in YYYY-MM-DD. Optional.")
    parser.add_argument(
        "--output-dir",
        default=".",
        help='Base output directory. Default: current directory ".".',
    )
    parser.add_argument(
        "--retweet-mode",
        choices=["exclude", "include", "only"],
        default="include",
        help="How to handle retweets. Default: include.",
    )
    parser.add_argument(
        "--include-replies",
        action="store_true",
        help="Include replies. Default: off.",
    )
    parser.add_argument(
        "--request-timeout",
        type=int,
        default=30,
        help="HTTP request timeout in seconds. Default: 30.",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=1,
        help="Extra retry attempts for timeout or network errors. Default: 1.",
    )
    parser.add_argument(
        "--page-delay-min",
        type=float,
        default=6.0,
        help="Minimum delay in seconds between pages for one target. Default: 6.",
    )
    parser.add_argument(
        "--page-delay-max",
        type=float,
        default=10.0,
        help="Maximum delay in seconds between pages for one target. Default: 10.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=10,
        help="Targets per batch before batch cooldown applies. Default: 10.",
    )
    parser.add_argument(
        "--target-delay-min",
        type=float,
        default=10.0,
        help="Minimum cooldown in seconds between targets inside a batch. Default: 10.",
    )
    parser.add_argument(
        "--target-delay-max",
        type=float,
        default=30.0,
        help="Maximum cooldown in seconds between targets inside a batch. Default: 30.",
    )
    parser.add_argument(
        "--batch-delay-min",
        type=float,
        default=60.0,
        help="Minimum cooldown in seconds between batches. Default: 60.",
    )
    parser.add_argument(
        "--batch-delay-max",
        type=float,
        default=120.0,
        help="Maximum cooldown in seconds between batches. Default: 120.",
    )
    return parser.parse_args()


def parse_targets(raw_targets: str) -> List[str]:
    path = Path(raw_targets)
    if path.exists() and path.is_file():
        items = []
        for line in path.read_text(encoding="utf-8").splitlines():
            value = line.strip()
            if not value or value.startswith("#"):
                continue
            items.append(value)
        return items
    return [item.strip() for item in raw_targets.split(",") if item.strip()]


def validate_batch_args(args: argparse.Namespace) -> None:
    x_scrape.validate_args(args)
    if args.batch_size <= 0:
        raise SystemExit("--batch-size must be > 0.")
    if args.target_delay_min < 0 or args.target_delay_max < 0:
        raise SystemExit("--target-delay-min and --target-delay-max must be >= 0.")
    if args.target_delay_min > args.target_delay_max:
        raise SystemExit("--target-delay-min must be <= --target-delay-max.")
    if args.batch_delay_min < 0 or args.batch_delay_max < 0:
        raise SystemExit("--batch-delay-min and --batch-delay-max must be >= 0.")
    if args.batch_delay_min > args.batch_delay_max:
        raise SystemExit("--batch-delay-min must be <= --batch-delay-max.")


def build_batch_output_dir(base_dir: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return base_dir / f"x-posts-batch-{timestamp}"


def build_flat_output_paths(output_dir: Path, username: str) -> tuple[Path, Path]:
    safe_username = re.sub(r"[^a-zA-Z0-9_.-]+", "_", username)
    return output_dir / f"{safe_username}.json", output_dir / f"{safe_username}.md"


def get_categories_for_result(
    *,
    target_accounts: Dict[str, Dict[str, Any]],
    resolved_alias: str | None,
    resolved_username: str,
) -> List[str]:
    if resolved_alias and resolved_alias in target_accounts:
        return list(target_accounts[resolved_alias].get("categories", []))

    lowered_username = resolved_username.lower()
    for entry in target_accounts.values():
        username = entry.get("username")
        if isinstance(username, str) and username.lower() == lowered_username:
            return list(entry.get("categories", []))

    return []


def build_batch_category_index(results: List[Dict[str, Any]], raw_root: Path) -> Dict[str, Any]:
    grouped: Dict[str, List[str]] = {}
    for item in results:
        relative_path = item.get("relative_json_path")
        if not isinstance(relative_path, str) or not relative_path:
            continue
        for category in item.get("categories", []):
            grouped.setdefault(category, []).append(relative_path)

    normalized_categories = {
        category: sorted(dict.fromkeys(paths))
        for category, paths in sorted(grouped.items())
        if paths
    }
    return {
        "raw_root": str(raw_root.resolve()),
        "categories": normalized_categories,
    }


def render_agent_readme(*, category_index_path: Path) -> str:
    lines = [
        "# Agent Instructions",
        "",
        "If you are an AI agent reading this batch output, start with this file.",
        "",
        "## Analyze One Category",
        "",
        "1. Read `batch_category_index.json` first.",
        "2. Find the category you need inside the `categories` object.",
        "3. Read only the filenames listed for that category.",
        "",
        "## Resolve File Paths",
        "",
        "1. Read `raw_root` from `batch_category_index.json`.",
        "2. Treat each listed filename as relative to `raw_root`.",
        "3. Open only those resolved files for analysis.",
        "",
        "## Hard Rules",
        "",
        "- Do not scan the whole `raw/` directory before choosing a category.",
        "- Do not load files from categories you were not asked to analyze.",
        "- The same file may appear in multiple categories. That is expected.",
        "",
        "## Example",
        "",
        "If you are asked to analyze `super_agent`:",
        "",
        "1. Open `batch_category_index.json`.",
        "2. Read `categories.super_agent` to get the allowed JSON filenames.",
        "3. Read `raw_root`.",
        "4. Join each filename with `raw_root`.",
        "5. Open only those resolved files and analyze them.",
        "",
        "## Category Index",
        "",
        f"- Path: `{category_index_path.resolve()}`",
        "",
    ]
    return "\n".join(lines)


def sleep_with_log(kind: str, delay_min: float, delay_max: float) -> None:
    sleep_seconds = random.uniform(delay_min, delay_max)
    logger.info("Sleeping between %s: sleep=%.1fs", kind, sleep_seconds)
    time.sleep(sleep_seconds)


def is_rate_limit_reason(reason: str) -> bool:
    lowered = reason.lower()
    return "rate limit" in lowered or "rate limited" in lowered or "429" in lowered


def render_summary_markdown(summary: Dict[str, Any]) -> str:
    lines = [
        "# X Scrape Batch Summary",
        "",
        f"- Run Status: `{summary['run_status']}`",
        f"- Total Targets: `{summary['total_targets']}`",
        f"- Completed Targets: `{summary['completed_targets']}`",
        f"- Successful Targets: `{summary['successful_targets']}`",
        f"- Partial Targets: `{summary['partial_targets']}`",
        f"- Failed Targets: `{summary['failed_targets']}`",
        f"- Batch Size: `{summary['batch_size']}`",
        f"- Target Delay Seconds: `{summary['target_delay_min']}-{summary['target_delay_max']}`",
        f"- Batch Delay Seconds: `{summary['batch_delay_min']}-{summary['batch_delay_max']}`",
        "",
    ]
    if summary.get("stopped_on_target"):
        lines.extend(
            [
                "## Stop Info",
                "",
                f"- Stopped On Target: `{summary['stopped_on_target']}`",
                f"- Stop Reason: `{summary['stop_reason']}`",
                f"- Next Target: `{summary.get('next_target') or ''}`",
                "",
            ]
        )
    lines.extend(["## Per Target Results", ""])
    for item in summary["targets"]:
        lines.extend(
            [
                f"### {item['target']}",
                "",
                f"- Resolved Username: `@{item['resolved_username']}`",
                f"- Resolved Alias: `{item['resolved_alias'] or ''}`",
                f"- Run Status: `{item['run_status']}`",
                f"- Tweet Count: `{item['tweet_count']}`",
                f"- JSON: `{item['json_path']}`",
                f"- Markdown: `{item['md_path']}`",
                f"- Partial Failure Reason: `{item['partial_failure_reason'] or ''}`",
                "",
            ]
        )
    return "\n".join(lines)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = parse_args()
    validate_batch_args(args)
    targets = parse_targets(args.targets)
    if not targets:
        raise SystemExit("No targets were provided.")

    target_accounts = x_scrape.load_target_accounts(Path(args.alias_file))
    alias_map = {alias: entry["username"] for alias, entry in target_accounts.items()}
    output_dir = build_batch_output_dir(Path(args.output_dir))
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_output_dir = output_dir / "raw"
    raw_output_dir.mkdir(parents=True, exist_ok=True)
    env_file_used = bool(load_default_env(Path(__file__).resolve().parents[1] / "config" / "x.env"))

    account_pool = x_scrape.AccountPool.from_env()
    logger.info(
        "Loaded scraping accounts: count=%s order=%s",
        len(account_pool.accounts),
        [account.index for account in account_pool.accounts],
    )
    client = x_scrape.XClient(
        account_pool=account_pool,
        timeout=args.request_timeout,
        max_retries=args.max_retries,
    )

    results: List[Dict[str, Any]] = []
    stopped_on_target = None
    stop_reason = None
    next_target = None

    for index, target in enumerate(targets):
        batch_args = argparse.Namespace(**vars(args), target=target)
        artifacts = x_scrape.scrape_target_to_files(
            args=batch_args,
            client=client,
            alias_map=alias_map,
            output_dir=raw_output_dir,
            env_file_used=env_file_used,
            path_builder=build_flat_output_paths,
        )
        categories = get_categories_for_result(
            target_accounts=target_accounts,
            resolved_alias=artifacts.resolved_alias,
            resolved_username=artifacts.resolved_username,
        )
        relative_json_path = os.path.relpath(artifacts.json_path, raw_output_dir)
        result = {
            "target": target,
            "resolved_username": artifacts.resolved_username,
            "resolved_alias": artifacts.resolved_alias,
            "categories": categories,
            "run_status": artifacts.run_result.status,
            "tweet_count": len(artifacts.exports),
            "partial_failure_reason": artifacts.run_result.partial_failure_reason,
            "json_path": str(artifacts.json_path),
            "md_path": str(artifacts.md_path),
            "relative_json_path": relative_json_path,
        }
        results.append(result)

        reason = artifacts.run_result.partial_failure_reason or ""
        if artifacts.run_result.status == "failed" and reason and is_rate_limit_reason(reason):
            stopped_on_target = target
            stop_reason = reason
            if index + 1 < len(targets):
                next_target = targets[index + 1]
            logger.warning("Stopping batch after first rate limit: target=%s reason=%s", target, reason)
            break

        if artifacts.run_result.status == "partial_success" and reason and is_rate_limit_reason(reason):
            stopped_on_target = target
            stop_reason = reason
            if index + 1 < len(targets):
                next_target = targets[index + 1]
            logger.warning("Stopping batch after first rate limit: target=%s reason=%s", target, reason)
            break

        has_more_targets = index + 1 < len(targets)
        if not has_more_targets:
            continue
        finished_batch = (index + 1) % args.batch_size == 0
        if finished_batch:
            sleep_with_log("batches", args.batch_delay_min, args.batch_delay_max)
        else:
            sleep_with_log("targets", args.target_delay_min, args.target_delay_max)

    successful_targets = sum(1 for item in results if item["run_status"] == "success")
    partial_targets = sum(1 for item in results if item["run_status"] == "partial_success")
    failed_targets = sum(1 for item in results if item["run_status"] == "failed")
    if stop_reason:
        run_status = "stopped_rate_limit"
    elif failed_targets or partial_targets:
        run_status = "completed_with_failures"
    else:
        run_status = "success"
    category_index_path = output_dir / "batch_category_index.json"
    agent_readme_path = output_dir / "AGENT_README.md"
    summary = {
        "run_status": run_status,
        "total_targets": len(targets),
        "completed_targets": len(results),
        "successful_targets": successful_targets,
        "partial_targets": partial_targets,
        "failed_targets": failed_targets,
        "batch_size": args.batch_size,
        "target_delay_min": args.target_delay_min,
        "target_delay_max": args.target_delay_max,
        "batch_delay_min": args.batch_delay_min,
        "batch_delay_max": args.batch_delay_max,
        "stopped_on_target": stopped_on_target,
        "stop_reason": stop_reason,
        "next_target": next_target,
        "targets": results,
    }

    summary_json_path = output_dir / "summary.json"
    summary_md_path = output_dir / "summary.md"
    with summary_json_path.open("w", encoding="utf-8") as handle:
        json.dump(summary, handle, ensure_ascii=False, indent=2)
    with summary_md_path.open("w", encoding="utf-8") as handle:
        handle.write(render_summary_markdown(summary))
    with category_index_path.open("w", encoding="utf-8") as handle:
        json.dump(
            build_batch_category_index(results, raw_output_dir),
            handle,
            ensure_ascii=False,
            indent=2,
        )
    with agent_readme_path.open("w", encoding="utf-8") as handle:
        handle.write(render_agent_readme(category_index_path=category_index_path))

    print(f"Batch output directory: {output_dir}")
    print(f"Run status: {run_status}")
    if stopped_on_target:
        print(f"Stopped on target: {stopped_on_target}")
    if stop_reason:
        print(f"Stop reason: {stop_reason}")
    if next_target:
        print(f"Next target: {next_target}")
    print(f"Saved summary JSON: {summary_json_path}")
    print(f"Saved summary Markdown: {summary_md_path}")
    print(f"Saved batch category index: {category_index_path}")
    print(f"Saved agent README: {agent_readme_path}")
    return 0 if not stop_reason else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
