#!/usr/bin/env python3
"""Basic discovery and routing evals for slide-infographic-reviewer.

This harness deliberately does not judge review quality. Discovery cases check
skill selection. Routing cases check trigger, target, mode, and requested
references. Real review effectiveness is validated with real user cases.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


EVAL_DIR = Path(__file__).resolve().parent
SKILL_DIR = EVAL_DIR.parent
CASES_PATH = EVAL_DIR / "cases.json"
CATALOG_PATH = EVAL_DIR / "catalog.json"
REFERENCE_DIR = SKILL_DIR / "references"


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def parse_skill_frontmatter() -> dict[str, str]:
    text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    parts = text.split("---", 2)
    if len(parts) < 3:
        raise ValueError("SKILL.md frontmatter is missing")
    values: dict[str, str] = {}
    for line in parts[1].splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        if key.strip() in {"name", "description"}:
            values[key.strip()] = value.strip()
    if set(values) != {"name", "description"}:
        raise ValueError("SKILL.md frontmatter must contain name and description")
    return values


def load_cases() -> list[dict[str, Any]]:
    payload = load_json(CASES_PATH)
    if payload.get("schema_version") != 4:
        raise ValueError("cases.json schema_version must be 4")
    if payload.get("scope") != "basic discovery and routing only":
        raise ValueError("cases.json scope must remain basic discovery and routing only")
    cases = payload.get("cases")
    if not isinstance(cases, list):
        raise ValueError("cases.json cases must be an array")
    return cases


def load_catalog() -> list[dict[str, str]]:
    payload = load_json(CATALOG_PATH)
    if payload.get("schema_version") != 2:
        raise ValueError("catalog.json schema_version must be 2")
    neighbors = payload.get("neighbor_skills")
    if not isinstance(neighbors, list):
        raise ValueError("catalog.json neighbor_skills must be an array")
    return [parse_skill_frontmatter(), *neighbors]


def reference_handles() -> list[str]:
    return [path.name for path in sorted(REFERENCE_DIR.glob("*.md"))]


def artifact_manifest(case: dict[str, Any]) -> list[dict[str, str | int]]:
    manifest: list[dict[str, str | int]] = []
    for relative in case.get("artifacts", []):
        path = (EVAL_DIR / relative).resolve()
        path.relative_to(EVAL_DIR)
        if not path.is_file():
            raise FileNotFoundError(f"Missing fixture for {case['id']}: {relative}")
        manifest.append(
            {
                "name": path.name,
                "mime_type": mimetypes.guess_type(path.name)[0] or "application/octet-stream",
                "size_bytes": path.stat().st_size,
            }
        )
    return manifest


def opaque_case_id(index: int) -> str:
    return f"eval-{index + 1:03d}"


def build_envelope(case: dict[str, Any], index: int) -> dict[str, Any]:
    layer = case["layer"]
    envelope: dict[str, Any] = {
        "case_id": opaque_case_id(index),
        "layer": layer,
        "request": case["request"],
        "artifacts": artifact_manifest(case),
    }
    if layer == "discovery":
        envelope.update(
            {
                "skill_catalog": load_catalog(),
                "instruction": (
                    "Select the single best skill from the catalog, or null when none applies. "
                    "Return only the trace JSON."
                ),
                "trace_contract": {
                    "case_id": "opaque case id",
                    "selected_skill": "catalog skill name or null",
                    "reason": "short string",
                },
            }
        )
        return envelope
    if layer != "routing":
        raise ValueError(f"Unknown eval layer: {layer!r}")
    frontmatter = parse_skill_frontmatter()
    envelope.update(
        {
            "skill": {
                "name": frontmatter["name"],
                "skill_md": (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8"),
                "reference_handles": reference_handles(),
            },
            "instruction": (
                "Decide whether the supplied skill applies. If it applies, determine the "
                "review target, primary mode, and reference handles to load. Encode each target "
                "canonically: use the exact artifact manifest name for a supplied file; use "
                "slide_N or page_N for a page inside a container; use inline_prompt or "
                "inline_structural only when the target exists solely in the request. Do not "
                "perform the review. Return only the routing trace JSON."
            ),
            "trace_contract": {
                "case_id": "opaque case id",
                "triggered": "boolean",
                "reason": "string or null",
                "target": "canonical target id or null: exact artifact name, slide_N, page_N, inline_prompt, or inline_structural",
                "targets": "ordered array of canonical target ids or null",
                "mode": "Prompt, Structural, Rendered, or null",
                "modes": "array or null",
                "references": "ordered array of reference handles",
                "reviews": "for multiple targets: array of target, mode, and references objects",
            },
        }
    )
    return envelope


def contains_expected(value: Any) -> bool:
    if isinstance(value, dict):
        return any(key.startswith("expected_") or contains_expected(item) for key, item in value.items())
    if isinstance(value, list):
        return any(contains_expected(item) for item in value)
    return False


def self_check(cases: list[dict[str, Any]]) -> list[str]:
    failures: list[str] = []
    ids = [case.get("id") for case in cases]
    if len(ids) != len(set(ids)):
        failures.append("case ids must be unique")
    if {case.get("layer") for case in cases} != {"discovery", "routing"}:
        failures.append("cases must cover discovery and routing")
    required_categories = {
        "explicit_trigger",
        "implicit_trigger",
        "negative_trigger",
        "combined_input",
        "noisy_context",
        "exception_path",
        "multi_target",
    }
    missing = sorted(required_categories - {case.get("category") for case in cases})
    if missing:
        failures.append(f"missing categories: {', '.join(missing)}")
    catalog_names = {item.get("name") for item in load_catalog()}
    if parse_skill_frontmatter()["name"] not in catalog_names:
        failures.append("live skill frontmatter is missing from discovery catalog")

    for index, case in enumerate(cases):
        case_id = case.get("id", "<missing-id>")
        if "request" not in case:
            failures.append(f"{case_id}: request is required")
        if case.get("layer") == "discovery" and "expected_selected_skill" not in case:
            failures.append(f"{case_id}: expected_selected_skill is required")
        if case.get("layer") == "routing" and "expected_trigger" not in case:
            failures.append(f"{case_id}: expected_trigger is required")
        try:
            artifact_manifest(case)
            envelope = build_envelope(case, index)
            if contains_expected(envelope):
                failures.append(f"{case_id}: expected answer leaked into adapter envelope")
        except (FileNotFoundError, ValueError) as exc:
            failures.append(str(exc))
        for reference in case.get("expected_references", []):
            if reference not in reference_handles():
                failures.append(f"{case_id}: missing reference {reference}")
    return failures


def validate_trace(case: dict[str, Any], actual: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    if case["layer"] == "discovery":
        selected = actual.get("selected_skill")
        if selected is not None and not isinstance(selected, str):
            failures.append("selected_skill must be a string or null")
        return failures
    if not isinstance(actual.get("triggered"), bool):
        failures.append("triggered must be a boolean")
        return failures
    if not actual["triggered"]:
        return failures
    references = actual.get("references")
    if not isinstance(references, list) or not all(isinstance(item, str) for item in references):
        failures.append("references must be an array of strings")
    elif not set(references).issubset(reference_handles()):
        failures.append("references contain an unknown handle")
    reviews = actual.get("reviews")
    if reviews is not None:
        if not isinstance(reviews, list) or not all(isinstance(item, dict) for item in reviews):
            failures.append("reviews must be an array of objects")
        else:
            for index, review in enumerate(reviews, start=1):
                item_references = review.get("references")
                if not isinstance(item_references, list) or not all(isinstance(item, str) for item in item_references):
                    failures.append(f"review {index} references must be an array of strings")
    return failures


def compare_case(case: dict[str, Any], actual: dict[str, Any]) -> list[str]:
    failures = validate_trace(case, actual)
    for key, expected in case.items():
        if not key.startswith("expected_"):
            continue
        actual_key = key[len("expected_") :]
        actual_key = {"trigger": "triggered"}.get(actual_key, actual_key)
        if actual.get(actual_key) != expected:
            failures.append(f"{actual_key}: expected {expected!r}, got {actual.get(actual_key)!r}")
    return failures


def invoke_adapter(command: list[str], envelope: dict[str, Any], timeout: float) -> tuple[dict[str, Any] | None, str | None]:
    adapter_env = os.environ.copy()
    adapter_env["PYTHONIOENCODING"] = "utf-8"
    adapter_env["PYTHONUTF8"] = "1"
    try:
        completed = subprocess.run(
            command,
            input=json.dumps(envelope, ensure_ascii=False).encode("utf-8"),
            capture_output=True,
            check=False,
            timeout=timeout,
            env=adapter_env,
        )
    except subprocess.TimeoutExpired:
        return None, f"timeout after {timeout:g}s"
    if completed.returncode != 0:
        error = completed.stderr.decode("utf-8", errors="replace").strip()
        return None, error or f"exit {completed.returncode}"
    try:
        payload = json.loads(completed.stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, f"invalid adapter JSON: {exc}"
    if not isinstance(payload, dict):
        return None, "adapter output must be a JSON object"
    return payload, None


def run_adapter(cases: list[dict[str, Any]], executable: str, adapter_args: list[str], timeout: float) -> list[dict[str, Any]]:
    observations: list[dict[str, Any]] = []
    command = [executable, *adapter_args]
    for index, case in enumerate(cases):
        envelope = build_envelope(case, index)
        actual, error = invoke_adapter(command, envelope, timeout)
        observations.append(
            actual if actual is not None else {"case_id": envelope["case_id"], "adapter_error": error}
        )
    return observations


def evaluate(cases: list[dict[str, Any]], observations: list[dict[str, Any]]) -> dict[str, Any]:
    by_opaque: dict[str, list[dict[str, Any]]] = {}
    for item in observations:
        if isinstance(item, dict) and isinstance(item.get("case_id"), str):
            by_opaque.setdefault(item["case_id"], []).append(item)
    expected_opaque = {opaque_case_id(index) for index in range(len(cases))}
    unknown_ids = sorted(set(by_opaque) - expected_opaque)
    results: list[dict[str, Any]] = []
    for index, case in enumerate(cases):
        adapter_id = opaque_case_id(index)
        matches = by_opaque.get(adapter_id, [])
        if not matches:
            actual, failures = {}, ["missing observation"]
        elif len(matches) > 1:
            actual, failures = matches[-1], ["duplicate observations"]
        else:
            actual = matches[0]
            failures = [actual["adapter_error"]] if "adapter_error" in actual else compare_case(case, actual)
        results.append(
            {
                "case_id": case["id"],
                "adapter_case_id": adapter_id,
                "passed": not failures,
                "failures": failures,
                "actual": actual,
            }
        )
    failed = sum(1 for result in results if not result["passed"]) + len(unknown_ids)
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "basic discovery and routing only",
        "summary": {"passed": len(results) - (failed - len(unknown_ids)), "failed": failed, "total": len(results) + len(unknown_ids)},
        "unknown_case_ids": unknown_ids,
        "results": results,
    }


def load_observations(path: Path) -> list[dict[str, Any]]:
    payload = load_json(path)
    if isinstance(payload, list):
        observations = payload
    elif isinstance(payload, dict) and "case_id" in payload:
        observations = [payload]
    elif isinstance(payload, dict) and "observations" in payload:
        observations = payload["observations"]
    elif isinstance(payload, dict) and "results" in payload:
        results = payload["results"]
        observations = [item["actual"] for item in results] if isinstance(results, list) and all(isinstance(item, dict) and "actual" in item for item in results) else results
    else:
        raise ValueError("results JSON must contain an observation object or array")
    if not isinstance(observations, list) or not all(isinstance(item, dict) for item in observations):
        raise ValueError("observations must be an array of JSON objects")
    return observations


def positive_float(value: str) -> float:
    parsed = float(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--self-check", action="store_true", help="Validate cases, catalog, fixtures, and envelopes")
    group.add_argument("--results", type=Path, help="Validate saved discovery/routing observations")
    group.add_argument("--adapter-executable", help="Executable that accepts one eval envelope on stdin")
    parser.add_argument("--adapter-arg", action="append", default=[], help="Repeat for each adapter argument")
    parser.add_argument("--adapter-timeout", type=positive_float, default=120.0, help="Per-case timeout in seconds")
    parser.add_argument("--output", type=Path, default=EVAL_DIR / "latest-results.json")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cases = load_cases()
    failures = self_check(cases)
    if failures:
        for failure in failures:
            print(f"SELF-CHECK FAIL: {failure}", file=sys.stderr)
        return 2
    if args.self_check:
        print(f"SELF-CHECK PASS: {len(cases)} basic discovery/routing cases are valid")
        return 0
    observations = load_observations(args.results) if args.results else run_adapter(cases, args.adapter_executable, args.adapter_arg, args.adapter_timeout)
    report = evaluate(cases, observations)
    write_json(args.output, report)
    print(json.dumps(report["summary"], ensure_ascii=False))
    return 0 if report["summary"]["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
