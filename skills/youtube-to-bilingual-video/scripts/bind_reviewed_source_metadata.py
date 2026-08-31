#!/usr/bin/env python3
"""Bind reviewed English-source evidence to the exact final source SRT bytes."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import uuid
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from path_safety import file_identity
from validate_bilingual_srt import (
    ALLOWED_SOURCE_LANGUAGE_ORIGINS,
    MIN_ASR_LANGUAGE_PROBABILITY,
    language_matches,
    parse_srt,
)


def sha256_path(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".metadata-{uuid.uuid4().hex}.tmp"
    try:
        temporary.write_text(text, encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def print_json(payload: dict[str, object]) -> None:
    rendered = json.dumps(payload, ensure_ascii=True, indent=2)
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


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create exact-hash metadata for an evidence-reviewed English source SRT."
    )
    parser.add_argument("--source-srt", type=Path, required=True)
    parser.add_argument("--upstream-metadata", type=Path, required=True)
    parser.add_argument(
        "--audit-report",
        type=Path,
        required=True,
        action="append",
        help="Ordered audit chain from the exact upstream source SRT to the reviewed source; repeat for each stage.",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-source-language", default="en")
    parser.add_argument("--reviewed-by", required=True, help="Actual reviewer, e.g. ai:<name> or human:<name>.")
    parser.add_argument("--review-note", required=True, help="Evidence and conclusions for every accepted change, or their audit record path.")
    parser.add_argument(
        "--accept-reviewed-changes",
        action="store_true",
        help="Explicitly acknowledge every lexical or structural review item in the supplied audit report.",
    )
    args = parser.parse_args()
    source = args.source_srt.resolve()
    upstream_path = args.upstream_metadata.resolve()
    audit_paths = [path.resolve() for path in args.audit_report]
    output = args.output.resolve()

    inputs = (source, upstream_path, *audit_paths)
    if file_identity(output) in {file_identity(path) for path in inputs}:
        print_json({"status": "error", "reason": "path_collision"})
        return 1
    try:
        parse_srt(source)
        upstream = json.loads(upstream_path.read_text(encoding="utf-8-sig"))
        if not isinstance(upstream, dict):
            raise ValueError("upstream metadata must be a JSON object")
        if not language_matches(
            upstream.get("source_language"), args.expected_source_language
        ) or not language_matches(
            upstream.get("required_source_language"), args.expected_source_language
        ):
            raise ValueError("upstream metadata did not pass the required-language gate")
        if upstream.get("source_language_origin") not in ALLOWED_SOURCE_LANGUAGE_ORIGINS - {
            "reviewed_source_handoff"
        }:
            raise ValueError("upstream metadata has an unsupported evidence origin")
        if upstream.get("source_language_origin") == "asr_detection":
            probability = upstream.get("source_language_probability")
            if (
                not isinstance(probability, (int, float))
                or isinstance(probability, bool)
                or not math.isfinite(float(probability))
                or float(probability) < MIN_ASR_LANGUAGE_PROBABILITY
            ):
                raise ValueError("upstream ASR language confidence is insufficient")
        if upstream.get("source_srt_hash_algorithm") != "sha256":
            raise ValueError("upstream metadata must declare an exact source SRT SHA-256")
        upstream_source_path = Path(str(upstream.get("source_srt_path", ""))).resolve()
        upstream_source_hash = sha256_path(upstream_source_path)
        if upstream.get("source_srt_sha256") != upstream_source_hash:
            raise ValueError("upstream metadata hash does not match its source SRT")

        audits: list[dict[str, object]] = []
        expected_before_path = upstream_source_path
        expected_before_hash = upstream_source_hash
        review_gate = False
        for position, audit_path in enumerate(audit_paths, start=1):
            audit = json.loads(audit_path.read_text(encoding="utf-8-sig"))
            if not isinstance(audit, dict):
                raise ValueError(f"audit report {position} must be a JSON object")
            before_path = Path(str(audit.get("before_path", ""))).resolve()
            after_path = Path(str(audit.get("after_path", ""))).resolve()
            before_hash = sha256_path(before_path)
            after_hash = sha256_path(after_path)
            if file_identity(before_path) != file_identity(expected_before_path):
                raise ValueError(f"audit report {position} does not continue the source lineage")
            if before_hash != expected_before_hash or audit.get("before_sha256") != before_hash:
                raise ValueError(f"audit report {position} before hash does not match its source file")
            if audit.get("after_sha256") != after_hash:
                raise ValueError(f"audit report {position} after hash does not match its source file")
            audit_requires_review = audit.get("status") == "review_required" or (
                audit.get("status") == "error"
                and audit.get("reason") == "structural_change"
            )
            if audit.get("status") not in {"ok", "review_required"} and not (
                audit.get("status") == "error"
                and audit.get("reason") == "structural_change"
            ):
                raise ValueError(f"audit report {position} is not an accepted audit result")
            review_gate = review_gate or audit_requires_review
            audits.append(audit)
            expected_before_path = after_path
            expected_before_hash = after_hash

        source_hash = sha256_path(source)
        if (
            file_identity(expected_before_path) != file_identity(source)
            or expected_before_hash != source_hash
        ):
            raise ValueError("audit chain does not end at the reviewed source SRT")
        if review_gate and not args.accept_reviewed_changes:
            raise ValueError(
                "audit report requires review; rerun with --accept-reviewed-changes only after evidence review"
            )
        payload = {
            "source_language": args.expected_source_language,
            "source_language_origin": "reviewed_source_handoff",
            "required_source_language": args.expected_source_language,
            "source_srt_hash_algorithm": "sha256",
            "source_srt_sha256": source_hash,
            "reviewed_by": args.reviewed_by.strip(),
            "review_note": args.review_note.strip(),
            "upstream_metadata_path": str(upstream_path),
            "upstream_metadata_sha256": sha256_path(upstream_path),
            "audit_reports": [
                {
                    "path": str(path),
                    "sha256": sha256_path(path),
                    "status": audit.get("status"),
                    "reason": audit.get("reason"),
                }
                for path, audit in zip(audit_paths, audits)
            ],
            "accepted_review_required_changes": bool(args.accept_reviewed_changes),
        }
        if not payload["reviewed_by"] or not payload["review_note"]:
            raise ValueError("reviewed-by and review-note must be non-empty")
        write_text_atomic(output, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        print_json({"status": "ok", "metadata_path": str(output), "source_srt_sha256": source_hash})
        return 0
    except (OSError, UnicodeError, ValueError) as exc:
        print_json(
            {
                "status": "error",
                "reason": "source_metadata_binding_failure",
                "message": str(exc),
                "output_path": str(output),
            }
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
