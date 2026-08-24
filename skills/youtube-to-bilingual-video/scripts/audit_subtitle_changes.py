#!/usr/bin/env python3
"""Audit an SRT correction pass and stop on lexical or structural changes."""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import re
import sys
import unicodedata
import uuid
from dataclasses import dataclass
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from path_safety import file_identity


TIMING_RE = re.compile(
    r"^(?P<start>\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*"
    r"(?P<end>\d{2}:\d{2}:\d{2},\d{3})$"
)
WORD_TOKEN_RE = re.compile(
    r"[#@$]?[^\W_]+"
    r"(?:['’._:/@#&-][^\W_]+|\++|#)*",
    flags=re.UNICODE,
)
BALANCED_NUMERIC_QUOTE_PATTERNS = (
    re.compile(r"(?<!\d)(?P<open>')\s*[+-]?(?:\d+(?:[.,]\d+)?|[.,]\d+)\s*(?P<close>')(?!\d)"),
    re.compile(r'(?<!\d)(?P<open>")\s*[+-]?(?:\d+(?:[.,]\d+)?|[.,]\d+)\s*(?P<close>")(?!\d)'),
    re.compile(r"(?<!\d)(?P<open>‘)\s*[+-]?(?:\d+(?:[.,]\d+)?|[.,]\d+)\s*(?P<close>’)(?!\d)"),
    re.compile(r"(?<!\d)(?P<open>“)\s*[+-]?(?:\d+(?:[.,]\d+)?|[.,]\d+)\s*(?P<close>”)(?!\d)"),
)


@dataclass(frozen=True)
class Cue:
    index: int
    timing: str
    text: str


def parse_srt(path: Path) -> list[Cue]:
    raw = path.read_text(encoding="utf-8-sig").replace("\r\n", "\n").strip()
    if not raw:
        raise ValueError(f"empty SRT: {path}")
    cues: list[Cue] = []
    for position, block in enumerate(re.split(r"\n{2,}", raw), start=1):
        lines = [line.rstrip() for line in block.splitlines()]
        if len(lines) < 3:
            raise ValueError(f"block {position} has fewer than three lines")
        try:
            index = int(lines[0].strip())
        except ValueError as exc:
            raise ValueError(f"block {position} has invalid cue number") from exc
        timing = lines[1].strip()
        if not TIMING_RE.fullmatch(timing):
            raise ValueError(f"cue {index} has invalid timing: {timing}")
        text = "\n".join(line.strip() for line in lines[2:] if line.strip())
        if not text:
            raise ValueError(f"cue {index} has no text")
        cues.append(Cue(index=index, timing=timing, text=text))
    return cues


def tokens(text: str) -> list[str]:
    normalized_text = unicodedata.normalize("NFC", text)
    items: list[str] = []
    balanced_numeric_quotes: set[int] = set()
    for pattern in BALANCED_NUMERIC_QUOTE_PATTERNS:
        for match in pattern.finditer(normalized_text):
            balanced_numeric_quotes.add(match.start("open"))
            balanced_numeric_quotes.add(match.start("close"))

    def append_meaningful_unmatched(start: int, end: int) -> None:
        for index in range(start, end):
            if index in balanced_numeric_quotes:
                continue
            char = normalized_text[index]
            category = unicodedata.category(char)
            adjacent_to_digit = (
                (index > 0 and normalized_text[index - 1].isdigit())
                or (
                    index + 1 < len(normalized_text)
                    and normalized_text[index + 1].isdigit()
                )
            )
            leading_decimal_separator = (
                char in ".,"
                and index + 1 < len(normalized_text)
                and normalized_text[index + 1].isdigit()
                and (index == 0 or not normalized_text[index - 1].isalnum())
            )
            measurement_prime = char in "'\"‘’“”′″" and adjacent_to_digit
            if (
                category.startswith(("S", "M"))
                or char in "%‰‱"
                or (char in "-−" and adjacent_to_digit)
                or leading_decimal_separator
                or measurement_prime
            ):
                items.append(char)

    cursor = 0
    for match in WORD_TOKEN_RE.finditer(normalized_text):
        append_meaningful_unmatched(cursor, match.start())
        items.append(match.group(0))
        cursor = match.end()
    append_meaningful_unmatched(cursor, len(normalized_text))
    return items


def normalized(items: list[str]) -> list[str]:
    return [item.casefold().replace("’", "'") for item in items]


def lexical_diff(before: str, after: str) -> list[dict[str, object]]:
    before_tokens = tokens(before)
    after_tokens = tokens(after)
    matcher = difflib.SequenceMatcher(
        a=normalized(before_tokens), b=normalized(after_tokens), autojunk=False
    )
    changes: list[dict[str, object]] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        changes.append(
            {
                "operation": tag,
                "before_tokens": before_tokens[i1:i2],
                "after_tokens": after_tokens[j1:j2],
            }
        )
    return changes


def audit(before_path: Path, after_path: Path) -> tuple[dict[str, object], int]:
    before = parse_srt(before_path)
    after = parse_srt(after_path)
    structural: list[dict[str, object]] = []
    if len(before) != len(after):
        structural.append(
            {"type": "cue_count", "before": len(before), "after": len(after)}
        )
    for position, (left, right) in enumerate(zip(before, after), start=1):
        if left.index != right.index:
            structural.append(
                {
                    "type": "cue_number",
                    "position": position,
                    "before": left.index,
                    "after": right.index,
                }
            )
        if left.timing != right.timing:
            structural.append(
                {
                    "type": "timing",
                    "cue": left.index,
                    "before": left.timing,
                    "after": right.timing,
                }
            )
    if structural:
        return (
            {
                "status": "error",
                "reason": "structural_change",
                "before_path": str(before_path.resolve()),
                "after_path": str(after_path.resolve()),
                "before_sha256": hashlib.sha256(before_path.read_bytes()).hexdigest(),
                "after_sha256": hashlib.sha256(after_path.read_bytes()).hexdigest(),
                "structural_changes": structural,
            },
            1,
        )

    changed_cues: list[dict[str, object]] = []
    lexical_changes: list[dict[str, object]] = []
    for left, right in zip(before, after):
        if left.text == right.text:
            continue
        cue_change: dict[str, object] = {
            "cue": left.index,
            "timing": left.timing,
            "before": left.text,
            "after": right.text,
        }
        cue_lexical = lexical_diff(left.text, right.text)
        cue_change["change_type"] = "lexical" if cue_lexical else "non_lexical"
        if cue_lexical:
            cue_change["token_changes"] = cue_lexical
            lexical_changes.append(cue_change)
        changed_cues.append(cue_change)

    review_required = bool(lexical_changes)
    report = {
        "status": "review_required" if review_required else "ok",
        "before_path": str(before_path.resolve()),
        "after_path": str(after_path.resolve()),
        "before_sha256": hashlib.sha256(before_path.read_bytes()).hexdigest(),
        "after_sha256": hashlib.sha256(after_path.read_bytes()).hexdigest(),
        "cue_count": len(before),
        "changed_cue_count": len(changed_cues),
        "lexical_change_count": len(lexical_changes),
        "policy": (
            "Any lexical insertion, deletion, or replacement requires evidence review. "
            "Punctuation, whitespace, and capitalization-only changes may pass."
        ),
        "changes": changed_cues,
        "review_items": lexical_changes,
    }
    return report, 2 if review_required else 0


def write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".report-{uuid.uuid4().hex}.tmp"
    try:
        temporary.write_text(text, encoding="utf-8")
        temporary.replace(path)
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


def print_report(report: dict[str, object], output: Path | None) -> None:
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if output:
        write_text_atomic(output, rendered + "\n")
        print_json(
            {
                "status": report.get("status"),
                "reason": report.get("reason"),
                "cue_count": report.get("cue_count"),
                "changed_cue_count": report.get("changed_cue_count"),
                "lexical_change_count": report.get("lexical_change_count"),
                "report_path": str(output),
            }
        )
    else:
        print_json(report)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare two SRT files and require review for lexical changes."
    )
    parser.add_argument("before", type=Path, help="Baseline SRT")
    parser.add_argument("after", type=Path, help="Corrected or optimized SRT")
    parser.add_argument("--output", type=Path, help="Write the JSON report here")
    args = parser.parse_args()
    before_path = args.before.resolve()
    after_path = args.after.resolve()
    output_path = args.output.resolve() if args.output else None
    if output_path and file_identity(output_path) in {
        file_identity(before_path),
        file_identity(after_path),
    }:
        print_json(
            {
                "status": "error",
                "reason": "path_collision",
                "message": "report output must differ from both SRT inputs",
                "before_path": str(before_path),
                "after_path": str(after_path),
                "output_path": str(output_path),
            }
        )
        return 1
    try:
        report, exit_code = audit(before_path, after_path)
    except (OSError, UnicodeError, ValueError) as exc:
        report = {
            "status": "error",
            "reason": "parse_failure",
            "message": str(exc),
            "before_path": str(args.before),
            "after_path": str(args.after),
        }
        exit_code = 1
    try:
        print_report(report, output_path)
        return exit_code
    except (OSError, UnicodeError, ValueError) as exc:
        print_json(
            {
                "status": "error",
                "reason": "report_write_failure",
                "message": str(exc),
                "output_path": None if output_path is None else str(output_path),
            }
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
