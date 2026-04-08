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
or detected failure mode.

### Scrapling script

```bash
python3 <SKILL_DIR>/scripts/fetch.py "<url>" [max_chars] [--strategy auto|fast|stealth|jina] [--json]
```

`<SKILL_DIR>` is the directory where this SKILL.md lives. Resolve it before calling the script.

The script uses a bounded strategy cascade:
- `auto`: choose based on domain and fallback rules
- `fast`: plain HTTP via Scrapling
- `stealth`: browser-backed fetch for JS-heavy or anti-bot pages
- `jina`: read-only fallback for simple public pages

Use explicit strategies only when you already know the site characteristics.

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

# Limit output to 15000 characters (default: 30000)
python3 <SKILL_DIR>/scripts/fetch.py "https://example.com/article" 15000

# Force Jina fallback for a public page
python3 <SKILL_DIR>/scripts/fetch.py "https://example.com/article" --strategy jina

# JSON output with metadata and warnings
python3 <SKILL_DIR>/scripts/fetch.py "https://example.com" --json
```

## Install Dependencies

First use only. The script checks and tells you if anything is missing:

```bash
pip install scrapling html2text
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
- Do not silently switch into platform scraping mode. Redirect YouTube or X/Twitter work
  to their dedicated skills instead.
