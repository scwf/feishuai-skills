#!/usr/bin/env python3
"""Generate plain-text email body from an X-daily report TXT.

Produces "今日各领域首要事实速览" — one block per category (first non-skip topic).

Usage:
    python3 email_body.py <input.txt> <YYYY-MM-DD> [-o output.txt] [--no-pdf] [--footer TEXT]

Footer: --footer or env X_DAILY_EMAIL_FOOTER (omit both for no footer line).

Skip detection (cross-category "详见" placeholders; see references/report-output.md):
- title starts with "详见"  OR
- fact starts with "详见" AND contains "不重复展开"  OR
- fact is empty

This handles the cross-category dedup case where one category's first topic
is "详见 super_agent 主题 01。本主题不重复展开。" and we want to skip it.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path


def extract_first_topic_per_category(txt_path: Path) -> list:
    text = txt_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    n = len(lines)
    i = 0
    category_re = re.compile(r"^【类别】(.+?) · (\d{4}-\d{2}-\d{2})\s*$")
    topic_re = re.compile(r"^【主题 (\d{2})】(.+)$")
    section_divider_re = re.compile(r"^═+")
    horizontal_divider_re = re.compile(r"^─+$")
    summary_marker = "今日总判断"
    judgement_labels = ("产品判断", "技术判断", "实践启示")

    def is_judgement_heading(text: str) -> bool:
        return any(text.startswith(f"{label}：") for label in judgement_labels)

    results = []
    current_category = None
    current_topic = None

    def is_skip_topic(topic: dict) -> bool:
        title = topic.get("title", "")
        fact = topic.get("fact", "")
        if any(p in title for p in ("详见",)):
            return True
        if fact.startswith("详见") and "不重复展开" in fact:
            return True
        if not fact:
            return True
        return False

    while i < n:
        line = lines[i]
        stripped = line.strip()

        if section_divider_re.match(stripped) or horizontal_divider_re.match(stripped):
            if current_topic is not None:
                results.append((current_category, current_topic))
                current_topic = None
            i += 1
            continue

        if summary_marker in stripped:
            if current_topic is not None:
                results.append((current_category, current_topic))
                current_topic = None
            break

        m_cat = category_re.match(stripped)
        if m_cat:
            if current_topic is not None:
                results.append((current_category, current_topic))
                current_topic = None
            current_category = m_cat.group(1)
            i += 1
            continue

        m_topic = topic_re.match(stripped)
        if m_topic:
            if current_topic is not None:
                results.append((current_category, current_topic))
            current_topic = {
                "num": m_topic.group(1),
                "title": m_topic.group(2).strip(),
                "fact": "",
                "judgement": "",
                "judgement_label": "产品判断",
                "links": [],
                "is_skip": False,
            }
            i += 1
            continue

        if current_topic is not None:
            if stripped.startswith("事实："):
                buf = []
                i += 1
                while i < n:
                    nxt = lines[i]
                    nxt_s = nxt.strip()
                    if (is_judgement_heading(nxt_s) or nxt_s.startswith("推文链接：")
                        or category_re.match(nxt_s) or topic_re.match(nxt_s)
                        or section_divider_re.match(nxt_s) or horizontal_divider_re.match(nxt_s)):
                        break
                    buf.append(nxt)
                    i += 1
                current_topic["fact"] = "\n".join(buf).strip()
                current_topic["is_skip"] = is_skip_topic(current_topic)
                continue
            if is_judgement_heading(stripped):
                current_topic["judgement_label"] = stripped.split("：", 1)[0]
                buf = []
                i += 1
                while i < n:
                    nxt = lines[i]
                    nxt_s = nxt.strip()
                    if (nxt_s.startswith("事实：") or nxt_s.startswith("推文链接：")
                        or category_re.match(nxt_s) or topic_re.match(nxt_s)
                        or section_divider_re.match(nxt_s) or horizontal_divider_re.match(nxt_s)):
                        break
                    buf.append(nxt)
                    i += 1
                current_topic["judgement"] = "\n".join(buf).strip()
                continue
            if stripped.startswith("推文链接："):
                buf = []
                i += 1
                while i < n:
                    nxt = lines[i]
                    nxt_s = nxt.strip()
                    if (nxt_s.startswith("事实：") or is_judgement_heading(nxt_s)
                        or category_re.match(nxt_s) or topic_re.match(nxt_s)
                        or section_divider_re.match(nxt_s) or horizontal_divider_re.match(nxt_s)):
                        break
                    if nxt_s:
                        buf.append(nxt_s)
                    i += 1
                for ln in buf:
                    ln = ln.strip().lstrip("- ")
                    if ln.startswith("http"):
                        current_topic["links"].append(ln)
                continue

        i += 1

    if current_topic is not None:
        results.append((current_category, current_topic))

    return results


def build_email_body(
    txt_path: Path,
    date_str: str,
    *,
    attach_pdf: bool = True,
    footer: str = "",
) -> str:
    topics = extract_first_topic_per_category(txt_path)

    def condense(text: str, max_chars: int = 200) -> str:
        text = (text or "").strip()
        if len(text) <= max_chars:
            return text
        return text[: max_chars - 1] + "…"

    # Group by category, then pick first non-skip
    by_cat: dict = {}
    for cat, topic in topics:
        by_cat.setdefault(cat, []).append(topic)

    picks = []
    for cat, topic_list in by_cat.items():
        chosen = None
        for t in topic_list:
            if t.get("is_skip"):
                continue
            chosen = t
            break
        if chosen is None and topic_list:
            chosen = topic_list[0]
        if chosen is not None:
            picks.append((cat, chosen))

    out = []
    out.append("今日各领域首要事实速览")
    out.append("")
    out.append(f"日期：{date_str}")
    out.append("")

    for cat, t in picks:
        out.append(f"【{cat}】")
        out.append(t["title"])
        out.append(f"事实：{condense(t.get('fact', ''), 220)}")
        judgement_label = t.get("judgement_label", "产品判断")
        out.append(f"{judgement_label}：{condense(t.get('judgement', ''), 140)}")
        links = t.get("links", [])[:2]
        if links:
            out.append("链接：")
            for ln in links:
                out.append(f"- {ln}")
        out.append("")

    out.append("各领域更多事件和推文解读，请参见附件：")
    out.append(f"- x_daily_analysis_{date_str}_full.txt")
    if attach_pdf:
        out.append(f"- x_daily_analysis_{date_str}_full.pdf")
    else:
        out.append("")
        out.append("注：PDF 生成失败，本次仅附 TXT 完整报告。")
    if footer.strip():
        out.append("")
        out.append(footer.strip())
        out.append("")

    return "\n".join(out)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build X-daily email body from report TXT.")
    p.add_argument("report_txt", type=Path, help="Full report TXT path")
    p.add_argument("date", help="Report date YYYY-MM-DD")
    p.add_argument("-o", "--output", type=Path, help="Write body to file (default: stdout)")
    p.add_argument("--no-pdf", action="store_true", help="Footer lists TXT only (PDF failed)")
    p.add_argument(
        "--footer",
        default=os.environ.get("X_DAILY_EMAIL_FOOTER", ""),
        help="Closing line (env X_DAILY_EMAIL_FOOTER)",
    )
    p.add_argument(
        "--pdf",
        type=Path,
        help="PDF path for attach detection (default: <report_dir>/x_daily_analysis_<date>_full.pdf)",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()
    txt_path = args.report_txt.expanduser().resolve()
    date_str = args.date

    if args.no_pdf:
        attach_pdf = False
    elif args.pdf:
        pdf = args.pdf.expanduser().resolve()
        attach_pdf = pdf.exists() and pdf.stat().st_size > 0
    else:
        pdf = txt_path.parent / f"x_daily_analysis_{date_str}_full.pdf"
        attach_pdf = pdf.exists() and pdf.stat().st_size > 0

    body = build_email_body(
        txt_path, date_str, attach_pdf=attach_pdf, footer=args.footer
    )
    if args.output:
        args.output.expanduser().resolve().write_text(body, encoding="utf-8")
    else:
        print(body)


if __name__ == "__main__":
    main()
