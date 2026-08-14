#!/usr/bin/env python3
"""Audit an SRT correction pass and stop on lexical or structural changes."""

from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path


TIMING_RE = re.compile(
    r"^(?P<start>\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*"
    r"(?P<end>\d{2}:\d{2}:\d{2},\d{3})$"
)
TOKEN_RE = re.compile(
    r"[#@$]?[A-Za-z0-9]+"
    r"(?:['’._:/@#&-][A-Za-z0-9]+|\++|#)*"
    r"|[\u3400-\u9fff]+"
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
    return TOKEN_RE.findall(text)


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


def write_report(report: dict[str, object], output: Path | None) -> None:
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare two SRT files and require review for lexical changes."
    )
    parser.add_argument("before", type=Path, help="Baseline SRT")
    parser.add_argument("after", type=Path, help="Corrected or optimized SRT")
    parser.add_argument("--output", type=Path, help="Write the JSON report here")
    args = parser.parse_args()
    try:
        report, exit_code = audit(args.before, args.after)
    except (OSError, UnicodeError, ValueError) as exc:
        report = {
            "status": "error",
            "reason": "parse_failure",
            "message": str(exc),
            "before_path": str(args.before),
            "after_path": str(args.after),
        }
        exit_code = 1
    write_report(report, args.output)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
