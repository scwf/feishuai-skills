#!/usr/bin/env python3
"""Fetch YouTube publication metadata for multiple targets."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, NoReturn, Optional

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
) -> NoReturn:
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


def default_output_dir() -> Path:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return Path(f"youtube-batch-{timestamp}")


def read_targets_file(path: Path) -> List[str]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        data = json.loads(text)
        if isinstance(data, list):
            values = data
        elif isinstance(data, dict) and isinstance(data.get("targets"), list):
            values = data["targets"]
        else:
            raise ValueError("JSON targets file must be a list or an object with a 'targets' list.")
        targets = []
        for value in values:
            if not isinstance(value, str):
                raise ValueError("Every target in the JSON targets file must be a string.")
            cleaned = value.strip()
            if cleaned:
                targets.append(cleaned)
        return targets

    targets = []
    for line in text.splitlines():
        cleaned = line.strip()
        if not cleaned or cleaned.startswith("#"):
            continue
        targets.append(cleaned)
    return targets


def read_alias_targets(path: Path) -> List[str]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if isinstance(data, dict):
        return [str(alias).strip() for alias in data.keys() if str(alias).strip()]
    if isinstance(data, list):
        targets = []
        for index, item in enumerate(data):
            if not isinstance(item, dict):
                raise ValueError(f"Invalid alias catalog entry at index {index}: expected object.")
            alias = item.get("alias")
            if not alias:
                raise ValueError(f"Invalid alias catalog entry at index {index}: missing alias.")
            targets.append(str(alias).strip())
        return targets
    raise ValueError("Alias catalog must be a JSON object or a list of alias objects.")


def ordered_unique_targets(targets: List[str]) -> List[str]:
    unique_targets: List[str] = []
    seen = set()
    for target in targets:
        cleaned = target.strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        unique_targets.append(cleaned)
    return unique_targets


def collect_targets(
    positional_targets: List[str],
    targets_file: Optional[str],
    all_configured: bool,
    alias_file: Optional[str],
) -> List[str]:
    targets: List[str] = [target.strip() for target in positional_targets if target.strip()]
    if targets_file:
        targets.extend(read_targets_file(Path(targets_file)))
    if all_configured:
        catalog_path = (
            Path(alias_file)
            if alias_file
            else Path(__file__).resolve().parents[1] / "defaults" / "youtube_channels.json"
        )
        targets.extend(read_alias_targets(catalog_path))
    return ordered_unique_targets(targets)


def build_child_command(args: argparse.Namespace, target: str, output_dir: Path) -> List[str]:
    script_path = Path(__file__).resolve().with_name("youtube_channel_meta.py")
    command = [sys.executable, str(script_path), target, "--output-dir", str(output_dir)]
    if args.alias_file:
        command.extend(["--alias-file", args.alias_file])
    if args.limit is not None:
        command.extend(["--limit", str(args.limit)])
    if args.days_lookback is not None:
        command.extend(["--days-lookback", str(args.days_lookback)])
    if args.since_date:
        command.extend(["--since-date", args.since_date])
    if args.until_date:
        command.extend(["--until-date", args.until_date])
    if args.request_timeout is not None:
        command.extend(["--request-timeout", str(args.request_timeout)])
    if args.skip_duration:
        command.append("--skip-duration")
    return command


def parse_child_stdout(stdout: str) -> Dict[str, Any]:
    lines = [line.strip() for line in stdout.splitlines() if line.strip()]
    if not lines:
        return structured_error(
            error_type="missing_child_output",
            failed_step="parse_child_stdout",
            message="Child scraper produced no stdout JSON.",
            retryable=True,
        )
    try:
        return json.loads(lines[-1])
    except json.JSONDecodeError as exc:
        return structured_error(
            error_type="invalid_child_output",
            failed_step="parse_child_stdout",
            message=f"Child scraper stdout was not valid JSON: {exc}",
            retryable=True,
            details={"stdout_tail": stdout[-1000:]},
        )


def read_child_artifacts(
    payload: Dict[str, Any],
) -> tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    json_path = payload.get("json_path")
    markdown_path = payload.get("markdown_path")
    if not isinstance(json_path, str) or not json_path or not isinstance(markdown_path, str) or not markdown_path:
        return None, structured_error(
            error_type="missing_child_artifact",
            failed_step="validate_child_artifacts",
            message="Successful child output must include JSON and Markdown artifact paths.",
            retryable=True,
        )
    path = Path(json_path)
    markdown = Path(markdown_path)
    missing = [str(candidate) for candidate in (path, markdown) if not candidate.is_file()]
    if missing:
        return None, structured_error(
            error_type="missing_child_artifact",
            failed_step="validate_child_artifacts",
            message="Child scraper reported success but required artifacts are missing.",
            retryable=True,
            details={"missing_paths": missing},
        )
    try:
        with path.open("r", encoding="utf-8") as handle:
            child_payload = json.load(handle)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return None, structured_error(
            error_type="invalid_child_artifact",
            failed_step="validate_child_artifacts",
            message=f"Could not read child JSON artifact: {exc}",
            retryable=True,
        )
    if not isinstance(child_payload, dict):
        return None, structured_error(
            error_type="invalid_child_artifact",
            failed_step="validate_child_artifacts",
            message="Child JSON artifact must contain an object.",
            retryable=True,
        )
    if child_payload.get("status") not in ("ok", "ok_with_warnings"):
        return None, structured_error(
            error_type="child_artifact_not_successful",
            failed_step="validate_child_artifacts",
            message="Child JSON artifact does not record a successful status.",
            retryable=True,
            details={"artifact_status": child_payload.get("status")},
        )
    return child_payload, None


def read_validation_from_child_json(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    child_payload, error = read_child_artifacts(payload)
    if error is not None or child_payload is None:
        return None
    validation = child_payload.get("validation")
    return validation if isinstance(validation, dict) else None


def build_child_summary_from_disk(
    child_payload: Dict[str, Any],
    locator_payload: Dict[str, Any],
) -> Dict[str, Any]:
    rss_fetch = child_payload.get("rss_fetch")
    if not isinstance(rss_fetch, dict):
        rss_fetch = {}
    return {
        "status": child_payload.get("status"),
        "query_target": child_payload.get("query_target"),
        "resolved_channel_id": child_payload.get("resolved_channel_id"),
        "resolved_alias": child_payload.get("resolved_alias"),
        "resolution_source": child_payload.get("resolution_source"),
        "since_date": child_payload.get("since_date"),
        "until_date": child_payload.get("until_date"),
        "effective_limit": child_payload.get("effective_limit"),
        "include_duration": child_payload.get("include_duration"),
        "video_count": child_payload.get("video_count"),
        "rss_feed_type": rss_fetch.get("selected_feed_type"),
        "rss_url": rss_fetch.get("selected_feed_url"),
        "json_path": locator_payload.get("json_path"),
        "markdown_path": locator_payload.get("markdown_path"),
        "validation": child_payload.get("validation"),
    }


def run_one_target(args: argparse.Namespace, target: str, output_dir: Path) -> Dict[str, Any]:
    command = build_child_command(args, target, output_dir)
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    payload = parse_child_stdout(completed.stdout)
    artifact_error = None
    disk_success = False
    has_artifact_reference = bool(payload.get("json_path") or payload.get("markdown_path"))
    stdout_claims_success = payload.get("status") in ("ok", "ok_with_warnings")
    if completed.returncode == 0 and (has_artifact_reference or stdout_claims_success):
        child_payload, artifact_error = read_child_artifacts(payload)
        if artifact_error is not None:
            payload = artifact_error
        elif child_payload is not None:
            items = child_payload.get("items")
            video_count = child_payload.get("video_count")
            validation = child_payload.get("validation")
            if child_payload.get("query_target") != target:
                artifact_error = structured_error(
                    error_type="child_artifact_target_mismatch",
                    failed_step="validate_child_artifacts",
                    message="Child JSON artifact target does not match the requested target.",
                    retryable=True,
                    details={
                        "requested_target": target,
                        "artifact_target": child_payload.get("query_target"),
                    },
                )
                payload = artifact_error
            elif (
                not isinstance(items, list)
                or isinstance(video_count, bool)
                or not isinstance(video_count, int)
                or video_count != len(items)
                or not isinstance(validation, dict)
            ):
                artifact_error = structured_error(
                    error_type="invalid_child_artifact",
                    failed_step="validate_child_artifacts",
                    message="Child JSON artifact counts or validation payload are inconsistent.",
                    retryable=True,
                )
                payload = artifact_error
            else:
                payload = build_child_summary_from_disk(child_payload, payload)
                disk_success = True
    return {
        "target": target,
        "returncode": completed.returncode,
        "status": payload.get("status", "error"),
        "ok": (
            completed.returncode == 0
            and disk_success
            and artifact_error is None
            and payload.get("status") in ("ok", "ok_with_warnings")
        ),
        "payload": payload,
        "stderr_tail": completed.stderr[-4000:] if completed.stderr else "",
    }


def summarize_status(results: List[Dict[str, Any]]) -> str:
    failures = [result for result in results if not result["ok"]]
    warnings = [
        result
        for result in results
        if result["ok"] and result["payload"].get("status") == "ok_with_warnings"
    ]
    if failures:
        return "partial_failure"
    if warnings:
        return "ok_with_warnings"
    return "ok"


def render_markdown(summary: Dict[str, Any]) -> str:
    lines = [
        "# YouTube Batch Metadata",
        "",
        f"- Status: {summary['status']}",
        f"- Target Count: {summary['target_count']}",
        f"- Success Count: {summary['success_count']}",
        f"- Failure Count: {summary['failure_count']}",
        f"- Output Directory: {summary['output_dir']}",
        f"- Since Date: {summary.get('since_date') or ''}",
        f"- Until Date: {summary.get('until_date') or ''}",
        f"- Effective Limit: {summary.get('limit') if summary.get('limit') is not None else ''}",
        f"- Include Duration: {summary['include_duration']}",
        "",
        "## Results",
        "",
    ]
    for index, result in enumerate(summary["results"], start=1):
        payload = result["payload"]
        lines.extend(
            [
                f"### {index}. {result['target']}",
                "",
                f"- Status: {result['status']}",
                f"- Return Code: {result['returncode']}",
                f"- Resolved Alias: {payload.get('resolved_alias') or ''}",
                f"- Resolved Channel ID: {payload.get('resolved_channel_id') or ''}",
                f"- Video Count: {payload.get('video_count') if payload.get('video_count') is not None else ''}",
                f"- JSON Path: {payload.get('json_path') or ''}",
                f"- Markdown Path: {payload.get('markdown_path') or ''}",
            ]
        )
        validation = payload.get("validation") or {}
        warnings = validation.get("warnings") or []
        if warnings:
            lines.append(f"- Warnings: {', '.join(warnings)}")
        if not result["ok"]:
            lines.append(f"- Error Type: {payload.get('error_type') or ''}")
            lines.append(f"- Failed Step: {payload.get('failed_step') or ''}")
            lines.append(f"- Message: {payload.get('message') or ''}")
        lines.append("")
    return "\n".join(lines)


def write_summary(output_dir: Path, summary: Dict[str, Any]) -> Dict[str, str]:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = output_dir / f"youtube_batch_summary_{timestamp}.json"
    md_path = output_dir / f"youtube_batch_summary_{timestamp}.md"
    with json_path.open("w", encoding="utf-8") as handle:
        json.dump(summary, handle, ensure_ascii=False, indent=2)
    with md_path.open("w", encoding="utf-8") as handle:
        handle.write(render_markdown(summary))
    return {"batch_json_path": str(json_path), "batch_markdown_path": str(md_path)}


def build_console_summary(summary: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "status": summary.get("status"),
        "target_count": summary.get("target_count"),
        "attempted_count": summary.get("attempted_count"),
        "success_count": summary.get("success_count"),
        "failure_count": summary.get("failure_count"),
        "output_dir": summary.get("output_dir"),
        "batch_json_path": summary.get("batch_json_path"),
        "batch_markdown_path": summary.get("batch_markdown_path"),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch YouTube channel publication metadata for multiple targets.",
        formatter_class=SmartDefaultsFormatter,
    )
    parser.add_argument(
        "targets",
        nargs="*",
        help="Aliases, @handles, channel URLs, video URLs, or channel IDs to scrape.",
    )
    parser.add_argument(
        "--targets-file",
        help=(
            "Optional. UTF-8 text file with one target per line, or JSON list/object with a "
            "'targets' list. Blank lines and '#' comments are ignored for text files."
        ),
    )
    parser.add_argument(
        "--all-configured",
        action="store_true",
        help=(
            "Optional flag. Scrape every alias in the default alias catalog, or in --alias-file "
            "when one is provided."
        ),
    )
    parser.add_argument(
        "--alias-file",
        default=None,
        help=(
            "Optional. Path to alias mapping JSON used for configured channel shortcuts. "
            "If omitted, the child scraper uses {SKILL_ROOT}/defaults/youtube_channels.json."
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        help=(
            "Optional. Maximum number of final videos to keep per target. If omitted, the child "
            "scraper keeps up to 20 items for open-ended queries, or up to 100 items when a date "
            "filter is active."
        ),
    )
    parser.add_argument(
        "--days-lookback",
        type=int,
        help=(
            "Optional. Relative lookback window in days. If omitted, no relative date filter is "
            "applied. Mutually exclusive with --since-date."
        ),
    )
    parser.add_argument(
        "--since-date",
        help=(
            "Optional. Absolute range start in YYYY-MM-DD. If omitted, no start-date filter is "
            "applied. Mutually exclusive with --days-lookback."
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
            "Optional. Directory where per-target outputs and batch summary files will be written. "
            "If omitted, creates a timestamped directory like ./youtube-batch-YYYYMMDD-HHMMSS."
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
            "Optional flag. If omitted, each child scrape fetches video pages to enrich duration "
            "metadata. Set this flag to skip duration enrichment."
        ),
    )
    parser.add_argument(
        "--stop-on-error",
        action="store_true",
        help="Optional flag. Stop after the first target failure instead of collecting partial results.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
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
    try:
        targets = collect_targets(
            args.targets,
            args.targets_file,
            args.all_configured,
            args.alias_file,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        exit_with_error(
            error_type="invalid_targets_file",
            failed_step="load_targets",
            message=str(exc),
            retryable=False,
            suggestion=(
                "Use --all-configured for the alias catalog, a UTF-8 text file with one target "
                "per line, or JSON with a targets list."
            ),
        )
    if not targets:
        exit_with_error(
            error_type="invalid_arguments",
            failed_step="validate_args",
            message="Provide at least one target argument or --targets-file.",
            retryable=False,
        )

    output_dir = Path(args.output_dir) if args.output_dir else default_output_dir()
    output_dir.mkdir(parents=True, exist_ok=True)

    results: List[Dict[str, Any]] = []
    for target in targets:
        result = run_one_target(args, target, output_dir)
        results.append(result)
        if args.stop_on_error and not result["ok"]:
            break

    status = summarize_status(results)
    summary: Dict[str, Any] = {
        "status": status,
        "target_count": len(targets),
        "attempted_count": len(results),
        "success_count": sum(1 for result in results if result["ok"]),
        "failure_count": sum(1 for result in results if not result["ok"]),
        "output_dir": str(output_dir),
        "alias_file": args.alias_file,
        "limit": args.limit,
        "days_lookback": args.days_lookback,
        "since_date": args.since_date,
        "until_date": args.until_date,
        "include_duration": not args.skip_duration,
        "stop_on_error": args.stop_on_error,
        "all_configured": args.all_configured,
        "results": results,
    }
    summary.update(write_summary(output_dir, summary))
    emit_stdout_json(build_console_summary(summary))
    return 1 if status == "partial_failure" else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
