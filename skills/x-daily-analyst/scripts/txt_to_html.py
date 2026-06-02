#!/usr/bin/env python3
"""Convert structured X-daily TXT report to structured HTML.

Parses the structured markers in the TXT (【类别】, 【主题 0X】, 事实：,
产品判断：/技术判断：/实践启示：, 推文链接：, 今日总判断) and emits a layered HTML file with deep-blue headers,
category containers, white topic cards, and color-coded fact/judgement/link labels.

Usage:
    python3 txt_to_html.py <input.txt> <output.html>

Common pitfalls the parser handles (see ../references/report-output.md):
- Last category not flushed when summary mode is hit (close_category() before summary).
- Category-level orphan notes (lines like "本类别今日有效主题不足 5 个..." that
  appear after the last topic, not associated with any topic) need a separate
  category-level note buffer that flushes in close_category().
- Cross-category "详见" topic fact content is preserved verbatim (rendered as a
  normal topic); the email-body generator, not this script, decides to skip it.
"""

from __future__ import annotations

import re
import sys
from html import escape
from pathlib import Path


def txt_to_html(txt_path: Path, html_path: Path) -> None:
    text = txt_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    n = len(lines)

    # Parse the header
    title = ""
    perspective = ""
    meta = {
        "抓取批次": "",
        "批次来源": "",
        "报告日期": "",
        "类别数量": "",
        "推文总数": "",
    }

    i = 0
    while i < n and lines[i].strip() != "══════════════":
        line = lines[i].strip()
        if line.startswith("X 每日情报分析"):
            m = re.search(r"X 每日情报分析 · (\d{4}-\d{2}-\d{2})", line)
            if m:
                title = f"X 每日情报分析 · {m.group(1)}"
        elif line.startswith("视角："):
            perspective = line.replace("视角：", "").strip()
        elif "：" in line:
            k, v = line.split("：", 1)
            if k in meta:
                meta[k] = v.strip()
        i += 1

    out: list = []
    out.append("<!doctype html>")
    out.append('<html lang="zh-CN">')
    out.append("<head>")
    out.append('  <meta charset="utf-8">')
    out.append('  <meta name="viewport" content="width=device-width, initial-scale=1">')
    out.append(f"  <title>{escape(title)}</title>")
    out.append(_css())
    out.append("</head>")
    out.append("<body>")
    out.append('<main class="page">')

    # Header
    out.append('  <header class="report-header">')
    out.append(f'    <div class="report-title">{escape(title)}</div>')
    out.append(f'    <div class="report-subtitle">视角：{escape(perspective)}</div>')
    out.append("  </header>")

    # Meta card
    out.append('  <section class="meta-card">')
    out.append("    <table>")
    for k, v in meta.items():
        out.append(f"      <tr><td>{escape(k)}</td><td>{escape(v)}</td></tr>")
    out.append("    </table>")
    out.append("  </section>")

    # State
    category_re = re.compile(r"^【类别】(.+?) · (\d{4}-\d{2}-\d{2})\s*$")
    topic_re = re.compile(r"^【主题 (\d{2})】(.+)$")
    section_divider_re = re.compile(r"^═+")
    horizontal_divider_re = re.compile(r"^─+$")
    summary_marker = "今日总判断"

    current_category = None
    current_topic = None
    current_topic_buffer = []
    category_note = None
    summary_mode = False
    summary_buffer = []
    judgement_labels = ("产品判断", "技术判断", "实践启示")

    def is_judgement_heading(text: str) -> bool:
        return any(text.startswith(f"{label}：") for label in judgement_labels)

    def close_topic():
        nonlocal current_topic, current_topic_buffer
        if current_topic is None:
            return
        cat_body = current_category
        topic_num = current_topic["num"]
        topic_title = current_topic["title"]
        blocks = current_topic_buffer
        current_topic = None
        current_topic_buffer = []
        if cat_body is None:
            return
        cat_body.append('        <article class="topic-card">')
        cat_body.append('          <div class="topic-title-row">')
        cat_body.append(f'            <span class="topic-no">{topic_num}</span>')
        cat_body.append(f'            <h2 class="topic-title">{escape(topic_title)}</h2>')
        cat_body.append("          </div>")
        for btype, btext in blocks:
            if btype == "fact":
                cat_body.append('          <div class="content-block">')
                cat_body.append('            <span class="label label-fact">事实</span>')
                for para in btext.strip().split("\n\n"):
                    if para.strip():
                        cat_body.append(f"            <p>{escape(para.strip())}</p>")
                cat_body.append("          </div>")
            elif btype == "judgement":
                label, text = btext
                cat_body.append('          <div class="content-block">')
                cat_body.append(f'            <span class="label label-judgement">{escape(label)}</span>')
                for para in text.strip().split("\n\n"):
                    if para.strip():
                        cat_body.append(f"            <p>{escape(para.strip())}</p>")
                cat_body.append("          </div>")
            elif btype == "link":
                cat_body.append('          <div class="content-block">')
                cat_body.append('            <span class="label label-link">推文链接</span>')
                cat_body.append("            <ul>")
                for lnk in btext.strip().splitlines():
                    lnk = lnk.strip()
                    if not lnk:
                        continue
                    if lnk.startswith("- "):
                        lnk = lnk[2:].strip()
                    if lnk.startswith("http"):
                        cat_body.append(f'              <li><a href="{escape(lnk)}">{escape(lnk)}</a></li>')
                    else:
                        cat_body.append(f"              <li>{escape(lnk)}</li>")
                cat_body.append("            </ul>")
                cat_body.append("          </div>")
        cat_body.append("        </article>")

    def close_category():
        # NOTE: nonlocal is required for ANY new outer-scope variable written here.
        nonlocal current_category, category_note
        if current_category is None:
            return
        close_topic()
        if category_note is not None and category_note.strip():
            current_category.append('        <div class="note">')
            current_category.append(f'          {escape(category_note.strip())}')
            current_category.append('        </div>')
        out.extend(current_category)
        out.append("      </div>")  # category-body
        out.append("    </section>")
        current_category = None
        category_note = None

    while i < n:
        line = lines[i]
        stripped = line.strip()

        if section_divider_re.match(stripped) or horizontal_divider_re.match(stripped):
            i += 1
            continue

        if summary_marker in stripped:
            summary_mode = True
            i += 1
            continue

        if summary_mode:
            if stripped:
                summary_buffer.append(stripped)
            i += 1
            continue

        # Category-level note detection (after last topic, before divider)
        if current_category is not None and current_topic is None and (
            "本类别今日有效主题不足" in stripped or "实际筛选出" in stripped
        ):
            buf = [stripped]
            i += 1
            while i < n:
                nxt_s = lines[i].strip()
                if (
                    category_re.match(nxt_s)
                    or topic_re.match(nxt_s)
                    or section_divider_re.match(nxt_s)
                    or horizontal_divider_re.match(nxt_s)
                    or summary_marker in nxt_s
                ):
                    break
                if nxt_s:
                    buf.append(nxt_s)
                i += 1
            category_note = " ".join(buf)
            continue

        m_cat = category_re.match(stripped)
        if m_cat:
            close_category()
            cat_name = m_cat.group(1)
            cat_date = m_cat.group(2)
            current_category = [
                '    <section class="category-section">',
                f'      <div class="category-header">{escape(cat_name)} · {escape(cat_date)}</div>',
                '      <div class="category-body">',
            ]
            i += 1
            continue

        m_topic = topic_re.match(stripped)
        if m_topic:
            close_topic()
            current_topic = {
                "num": m_topic.group(1),
                "title": m_topic.group(2).strip(),
            }
            current_topic_buffer = []
            i += 1
            continue

        if current_topic is not None:
            if stripped.startswith("事实："):
                buf = []
                i += 1
                while i < n:
                    nxt_s = lines[i].strip()
                    if (
                        is_judgement_heading(nxt_s)
                        or nxt_s.startswith("推文链接：")
                        or category_re.match(nxt_s)
                        or topic_re.match(nxt_s)
                        or section_divider_re.match(nxt_s)
                        or horizontal_divider_re.match(nxt_s)
                    ):
                        break
                    buf.append(lines[i])
                    i += 1
                current_topic_buffer.append(("fact", "\n".join(buf)))
                continue
            if is_judgement_heading(stripped):
                judgement_label = stripped.split("：", 1)[0]
                buf = []
                i += 1
                while i < n:
                    nxt_s = lines[i].strip()
                    if (
                        nxt_s.startswith("事实：")
                        or nxt_s.startswith("推文链接：")
                        or category_re.match(nxt_s)
                        or topic_re.match(nxt_s)
                        or section_divider_re.match(nxt_s)
                        or horizontal_divider_re.match(nxt_s)
                    ):
                        break
                    buf.append(lines[i])
                    i += 1
                current_topic_buffer.append(("judgement", (judgement_label, "\n".join(buf))))
                continue
            if stripped.startswith("推文链接："):
                buf = []
                i += 1
                while i < n:
                    nxt_s = lines[i].strip()
                    if (
                        nxt_s.startswith("事实：")
                        or is_judgement_heading(nxt_s)
                        or category_re.match(nxt_s)
                        or topic_re.match(nxt_s)
                        or section_divider_re.match(nxt_s)
                        or horizontal_divider_re.match(nxt_s)
                    ):
                        break
                    if nxt_s:
                        buf.append(lines[i])
                    i += 1
                current_topic_buffer.append(("link", "\n".join(buf)))
                continue

        i += 1

    # Close any open structure. CRITICAL: do this BEFORE the summary block,
    # otherwise the last category never gets flushed to `out`.
    if current_category is not None:
        close_category()

    if summary_mode:
        out.append('  <section class="summary-card">')
        out.append("    <h2>今日总判断</h2>")
        out.append("    <ol>")
        for item in summary_buffer:
            # Strip leading numbering "1." / "2." if present
            cleaned = re.sub(r"^\d+\.\s*", "", item)
            out.append(f"      <li>{escape(cleaned)}</li>")
        out.append("    </ol>")
        out.append("  </section>")

    out.append("</main>")
    out.append("</body>")
    out.append("</html>")

    html_path.write_text("\n".join(out), encoding="utf-8")


def _css() -> str:
    return """  <style>
    body {
      background: #f3f6fb;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI",
                   "Microsoft YaHei", "PingFang SC",
                   "Noto Sans CJK SC", Arial, sans-serif;
      color: #111827;
      margin: 0;
      padding: 0;
    }
    .page { max-width: 900px; margin: 0 auto; padding: 24px 16px 60px; }
    .report-header {
      background: #0F3D91; color: #ffffff;
      border-radius: 16px 16px 0 0; padding: 24px 28px;
    }
    .report-title { font-size: 22px; font-weight: 800; letter-spacing: 0.5px; }
    .report-subtitle { font-size: 15px; margin-top: 6px; opacity: 0.92; }
    .meta-card {
      background: #ffffff; border: 1px solid #e5e7eb; border-top: 0;
      border-radius: 0 0 16px 16px; padding: 18px 28px; margin-bottom: 20px;
    }
    .meta-card table { width: 100%; border-collapse: collapse; }
    .meta-card td { padding: 6px 4px; font-size: 14px; color: #1f2937; border-bottom: 1px dashed #eef2f7; vertical-align: top; }
    .meta-card td:first-child { width: 110px; color: #6b7280; font-weight: 600; }
    .meta-card tr:last-child td { border-bottom: 0; }
    .category-section {
      border: 1px solid #cbd5e1; border-radius: 18px;
      background: #eef6ff; overflow: hidden; margin-bottom: 26px;
    }
    .category-header {
      background: #0F3D91; color: #ffffff;
      padding: 16px 22px; font-weight: 800; font-size: 16px; letter-spacing: 0.4px;
    }
    .category-body { background: #f8fbff; border-left: 6px solid #0F3D91; padding: 18px; }
    .topic-card {
      background: #ffffff; border: 1px solid #dbe4f0; border-radius: 14px;
      padding: 20px 22px; margin-bottom: 16px;
    }
    .topic-card:last-child { margin-bottom: 0; }
    .topic-title-row { display: flex; align-items: center; gap: 12px; margin-bottom: 14px; }
    .topic-no {
      background: #0F3D91; color: #ffffff; border-radius: 999px;
      padding: 4px 12px; font-size: 12px; font-weight: 800;
      letter-spacing: 1px; white-space: nowrap;
    }
    .topic-title { font-size: 18px; line-height: 1.5; color: #111827; margin: 0; font-weight: 700; }
    .content-block { margin-top: 12px; }
    .content-block p { font-size: 15px; line-height: 1.85; color: #1f2937; margin: 6px 0 0 0; white-space: pre-wrap; }
    .label {
      display: inline-block; padding: 4px 10px; border-radius: 999px;
      font-size: 13px; font-weight: 700; letter-spacing: 0.4px;
    }
    .label-fact { color: #0F3D91; background: #EEF3FB; border: 1px solid #d6e3f5; }
    .label-judgement { color: #92400E; background: #FEF3C7; border: 1px solid #fde68a; }
    .label-link { color: #047857; background: #ECFDF5; border: 1px solid #a7f3d0; }
    .content-block ul { list-style: disc; padding-left: 22px; margin: 8px 0 0 0; }
    .content-block li { font-size: 14.5px; line-height: 1.7; color: #1f2937; word-break: break-all; }
    .content-block a { color: #0F3D91; text-decoration: none; }
    .content-block a:hover { text-decoration: underline; }
    .summary-card {
      background: #ffffff; border: 1px solid #BFDBFE; border-left: 6px solid #0F3D91;
      border-radius: 18px; padding: 24px 26px; margin-bottom: 20px;
    }
    .summary-card h2 { color: #0F3D91; font-size: 18px; margin: 0 0 14px 0; font-weight: 800; }
    .summary-card ol { padding-left: 22px; margin: 0; }
    .summary-card li { color: #111827; font-size: 15px; line-height: 1.85; margin-bottom: 8px; }
    .note {
      background: #fff7ed; border: 1px solid #fed7aa; border-radius: 10px;
      padding: 10px 14px; color: #7c2d12; font-size: 14px; line-height: 1.7; margin-top: 10px;
    }
  </style>"""


if __name__ == "__main__":
    txt_path = Path(sys.argv[1])
    html_path = Path(sys.argv[2])
    txt_to_html(txt_path, html_path)
    print(f"OK {html_path} {html_path.stat().st_size} bytes")
