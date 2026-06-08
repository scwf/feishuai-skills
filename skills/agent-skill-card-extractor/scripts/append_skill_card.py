#!/usr/bin/env python3
"""Append an Agent skill card to a Markdown skill library without overwriting."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


DEFAULT_LIBRARY = Path(
    r"D:\PARA\areas\01.GenAI\02.Agent\skills\my_skills_library.md"
)


SECTION_RE = re.compile(r"^##\s+(\d+)(?:[.\s]|$)", re.MULTILINE)
NAME_RE = re.compile(r"^🛠️\s*技能名称：\s*(.+?)\s*$", re.MULTILINE)


def next_section_number(existing: str) -> int:
    numbers = [int(match.group(1)) for match in SECTION_RE.finditer(existing)]
    return max(numbers, default=0) + 1


def extract_title(card: str) -> str:
    match = NAME_RE.search(card)
    if not match:
        return "未命名技能"
    return match.group(1).strip().strip("[]") or "未命名技能"


def append_card(library: Path, card: str) -> str:
    card = card.strip()
    if not card:
        raise ValueError("card content is empty")

    library.parent.mkdir(parents=True, exist_ok=True)
    existing = library.read_text(encoding="utf-8") if library.exists() else ""

    section_number = next_section_number(existing)
    title = extract_title(card)
    section = f"## {section_number}. {title}\n\n{card}\n"

    separator = "\n\n" if existing.strip() else ""
    library.write_text(existing.rstrip() + separator + section, encoding="utf-8")
    return f"Appended section {section_number}: {title}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--card-file", required=True, help="Markdown file containing one skill card")
    parser.add_argument("--library", default=str(DEFAULT_LIBRARY), help="Markdown library path")
    args = parser.parse_args()

    card = Path(args.card_file).read_text(encoding="utf-8")
    result = append_card(Path(args.library), card)
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
