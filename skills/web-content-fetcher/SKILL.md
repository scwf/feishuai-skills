---
name: web-content-fetcher
description: >
  Extract the main content from a web page URL as clean Markdown or JSON.
  Use when reading, extracting, scraping, or summarizing article-like pages such as
  blog posts, news articles, documentation pages, WeChat articles (微信公众号),
  and web essays. The bundled script auto-selects a fetch strategy, supports
  JavaScript-heavy pages, detects paywalls or anti-bot poison pills, and preserves
  headings, links, images, lists, and code blocks. Do not use this skill for
  platform-specific scraping such as YouTube or X/Twitter; use dedicated skills for those.
---

# Web Content Fetcher

Given a URL, return its main content as clean Markdown or structured JSON.
For WeChat articles, prefer high-fidelity extraction that preserves media positions,
counts images/videos, and can localize assets for offline Markdown output.

## Scope

- Handle article-like web pages, blogs, docs, newsletters, and WeChat articles.
- Prefer the bundled script instead of ad hoc scraping code.
- Exclude platform-specific scraping workflows such as YouTube or X/Twitter.

## Default workflow

Run the bundled script and let it select the strategy:

```bash
python3 <SKILL_DIR>/scripts/fetch.py "<url>" [max_chars]
```

Use `--json` when the caller needs metadata such as selected strategy, selector, warnings,
detected failure mode, media inventory, and fidelity checks.
Use `--include-content` and `--include-html` only when the full Markdown or extracted HTML
is actually needed.

### Scrapling script

```bash
python3 <SKILL_DIR>/scripts/fetch.py "<url>" [max_chars] [--strategy auto|fast|stealth|jina] [--json] [--include-content] [--include-html] [--download-assets DIR]
```

`<SKILL_DIR>` is the directory where this SKILL.md lives. Resolve it before calling the script.

The script uses a bounded strategy cascade:
- `auto`: choose based on domain and fallback rules
- `fast`: plain HTTP via Scrapling
- `stealth`: browser-backed fetch for JS-heavy or anti-bot pages
- `jina`: read-only fallback for simple public pages

Use explicit strategies only when you already know the site characteristics.

## WeChat High-Fidelity Rules

When the URL is `mp.weixin.qq.com`, treat the task as "rich article reconstruction", not
just "text extraction".

- Use `--strategy stealth` on the first call.
- Use `--json` when the user asks about image/video counts, completeness, downloading,
  or exact media placement.
- Keep `--json` lightweight by default; add `--include-content` or `--include-html` only
  when the next step truly needs the full body payload.
- Trust `assets`, `asset_count_summary`, and `fidelity_report` over eyeballing Markdown.
- If the user wants offline Markdown with local media, use `--download-assets DIR`.
- Do not claim extraction is complete if `fidelity_report.issues` is non-empty.
- For WeChat video nodes, the script may return either a direct downloadable media URL,
  an embed/player URL, or only a placeholder note. Report that clearly.

## Domain Routing

Use this table to pick the right mode on the first call when needed:

| Domain | Command | Why |
|--------|---------|-----|
| `mp.weixin.qq.com` | `fetch.py <url> --strategy stealth` | WeChat structure and JS-heavy rendering |
| `zhuanlan.zhihu.com` | `fetch.py <url> --stealth` | Anti-scraping + JS |
| `juejin.cn` | `fetch.py <url> --stealth` | JS-rendered SPA |
| `sspai.com` | `fetch.py <url>` | Static HTML |
| `blog.csdn.net` | `fetch.py <url>` | Static HTML |
| `ruanyifeng.com` | `fetch.py <url>` | Static blog |
| `openai.com` | `fetch.py <url>` | Static HTML |
| `blog.google` | `fetch.py <url>` | Static HTML |
| Everything else | `fetch.py <url>` | Auto mode handles fallback |

## Script Options

```bash
# Basic — auto-selects strategy
python3 <SKILL_DIR>/scripts/fetch.py "https://sspai.com/post/73145"

# Force stealth for known JS-heavy sites
python3 <SKILL_DIR>/scripts/fetch.py "https://mp.weixin.qq.com/s/xxx" --strategy stealth

# Limit output to 15000 characters (default: 50000)
python3 <SKILL_DIR>/scripts/fetch.py "https://example.com/article" 15000

# Force Jina fallback for a public page
python3 <SKILL_DIR>/scripts/fetch.py "https://example.com/article" --strategy jina

# JSON output with metadata and warnings
python3 <SKILL_DIR>/scripts/fetch.py "https://example.com" --json

# WeChat high-fidelity JSON with media inventory
python3 <SKILL_DIR>/scripts/fetch.py "https://mp.weixin.qq.com/s/xxx" --strategy stealth --json

# Include full Markdown in JSON only when needed
python3 <SKILL_DIR>/scripts/fetch.py "https://mp.weixin.qq.com/s/xxx" --strategy stealth --json --include-content

# Include both Markdown and extracted HTML fragment
python3 <SKILL_DIR>/scripts/fetch.py "https://mp.weixin.qq.com/s/xxx" --strategy stealth --json --include-content --include-html

# Download assets and rewrite Markdown to local relative paths
python3 <SKILL_DIR>/scripts/fetch.py "https://mp.weixin.qq.com/s/xxx" --strategy stealth --download-assets article-assets

# Show CLI help
python3 <SKILL_DIR>/scripts/fetch.py --help
```

### Parameter reference

- `<url>`
  Required. Target page URL to fetch.

- `[max_chars]`
  Optional. Maximum Markdown characters to keep.
  Default: `50000`.

- `--strategy auto|fast|stealth|jina`
  Optional. Controls the fetch strategy.
  Default: `auto`.
  Use `stealth` for JS-heavy sites such as WeChat, Zhihu, and Juejin.

- `--stealth`
  Optional shortcut for `--strategy stealth`.
  Default: off.

- `--json`
  Optional. Returns structured JSON instead of plain Markdown.
  Default: off.

- `--include-content`
  Optional. Adds full Markdown content to JSON output.
  Only meaningful together with `--json`.
  Default: off.

- `--include-html`
  Optional. Adds the extracted HTML fragment to JSON output.
  Only meaningful together with `--json`.
  Default: off.

- `--download-assets DIR`
  Optional. Downloads localizable images/videos into `DIR` and rewrites Markdown asset links
  to local relative paths.
  Default: off.

- `-h`, `--help`
  Optional. Shows command help and exits.

## JSON Output

`--json` includes lightweight metadata by default:

- `title`, `selector`, `mode`
- `assets.images[]`: image inventory with normalized URL, placeholder flag, download state, and local path
- `assets.videos[]`: video inventory with embed/direct URL info, poster, download state, and local path
- `asset_count_summary`: image/video totals
- `fidelity_report`: DOM-vs-Markdown counts and issues
- `warnings`: blocking or fidelity warnings

Optional heavy fields:

- `content`: included only with `--include-content`
- `html_fragment`: included only with `--include-html`

Use this mode whenever you need to answer:

- "How many images/videos are there?"
- "Did you miss anything?"
- "Were the assets actually downloaded?"
- "Can this Markdown be trusted for offline use?"

## Install Dependencies

First use only. The script checks and tells you if anything is missing:

```bash
pip install scrapling html2text beautifulsoup4
```

If stealth mode reports a missing browser dependency such as `patchright`, install the
browser extra required by your Scrapling setup before retrying.

If on system-managed Python (macOS/Linux), add `--break-system-packages` or use a venv.

## Failure handling

- Prefer one bounded attempt sequence per URL; do not loop indefinitely.
- Trust the script's poison-pill detection:
  - `paywall`
  - `captcha`
  - `cloudflare`
  - `login_required`
  - `rate_limit`
- If the script reports a blocking warning or returns very short content after fallback,
  tell the user extraction was not reliable.
- If `fidelity_report.issues` is non-empty, tell the user the article may be only partially
  reconstructed even if Markdown was produced.
- Do not silently switch into platform scraping mode. Redirect YouTube or X/Twitter work
  to their dedicated skills instead.

## Recommended response patterns

- For ordinary article summarization: plain Markdown output is fine.
- For WeChat article archival: run `--strategy stealth --json` first, inspect counts, then
  rerun with `--download-assets DIR` if the user wants local assets.
- If the user specifically asks for image/video totals, answer from `asset_count_summary`,
  not from manual counting in rendered Markdown.
