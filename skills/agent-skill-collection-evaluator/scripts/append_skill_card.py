#!/usr/bin/env python3
"""Append an Agent skill card to a Markdown skill library without overwriting."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


DEFAULT_LIBRARY = Path.home() / ".agents" / "my_skills_library.md"


SECTION_RE = re.compile(r"^##\s+(\d+)(?:[.\s]|$)", re.MULTILINE)
NAME_RE = re.compile(r"^🛠️\s*技能名称：\s*(.+?)\s*$", re.MULTILINE)
FIELD_LABELS = [
    "🛠️ 技能名称",
    "技能名称",
    "来源地址",
    "技能定位",
    "适用场景",
    "输入",
    "输出",
    "实现逻辑",
    "是否推荐收录",
]
FIELD_RE = re.compile(
    rf"^(?P<label>{'|'.join(re.escape(label) for label in FIELD_LABELS)})\s*[:：]\s*(?P<value>.*?)(?=^\s*(?:{'|'.join(re.escape(label) for label in FIELD_LABELS)})\s*[:：]|\Z)",
    re.MULTILINE | re.DOTALL,
)
FIELD_ORDER = [
    "来源地址",
    "技能定位",
    "适用场景",
    "输入",
    "输出",
    "实现逻辑",
]


def next_section_number(existing: str) -> int:
    numbers = [int(match.group(1)) for match in SECTION_RE.finditer(existing)]
    return max(numbers, default=0) + 1


def extract_title(card: str) -> str:
    match = NAME_RE.search(card)
    if not match:
        return "未命名技能"
    return match.group(1).strip().strip("[]") or "未命名技能"


def parse_card_fields(card: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for match in FIELD_RE.finditer(card):
        label = match.group("label").replace(" ", "")
        if label.startswith("🛠️"):
            label = "技能名称"
        fields[label] = match.group("value").strip()
    return fields


def render_library_section(section_number: int, card: str) -> str:
    title = extract_title(card)
    fields = parse_card_fields(card)
    if not fields:
        return f"## {section_number}. {title}\n\n{card.strip()}\n"

    lines = [f"## {section_number}. 🛠️ {title}", ""]
    source_url = fields.get("来源地址")
    if source_url:
        lines.extend([f"**来源地址**：{source_url}", ""])

    positioning = fields.get("技能定位")
    if positioning:
        lines.extend([f"> {positioning}", ""])

    for label in FIELD_ORDER:
        value = fields.get(label)
        if not value:
            continue
        if label in {"来源地址", "技能定位"}:
            continue
        lines.extend([f"### {label}", "", value, ""])

    return "\n".join(lines).rstrip() + "\n"


def append_card(library: Path, card: str) -> str:
    library = library.expanduser()
    card = card.strip()
    if not card:
        raise ValueError("card content is empty")

    library.parent.mkdir(parents=True, exist_ok=True)
    existing = library.read_text(encoding="utf-8") if library.exists() else ""

    section_number = next_section_number(existing)
    title = extract_title(card)
    section = render_library_section(section_number, card)

    if not existing.strip():
        separator = ""
    elif existing.endswith("\n\n"):
        separator = ""
    elif existing.endswith("\n"):
        separator = "\n"
    else:
        separator = "\n\n"
    with library.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(separator + section)
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
