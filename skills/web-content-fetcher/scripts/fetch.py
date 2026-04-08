#!/usr/bin/env python3
"""
Universal web content extractor.
Returns clean Markdown and structured metadata for article-like pages.
"""

from enum import Enum
from dataclasses import dataclass, asdict
from urllib.parse import urlparse, quote
from urllib.request import Request, urlopen
import sys
import re
import json
import logging


def configure_stdio():
    """Prefer UTF-8 stdio so Windows consoles don't choke on non-GBK output."""
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")


def check_dependencies():
    """Check if required packages are installed and provide install instructions."""
    missing = []
    try:
        import scrapling  # noqa: F401
    except ImportError:
        missing.append("scrapling")
    try:
        import html2text  # noqa: F401
    except ImportError:
        missing.append("html2text")

    if missing:
        print(
            f"Error: missing dependencies: {', '.join(missing)}\n"
            f"Install with:\n"
            f"  pip install {' '.join(missing)}",
            file=sys.stderr,
        )
        sys.exit(1)


class PoisonPillType(str, Enum):
    PAYWALL = "paywall"
    CAPTCHA = "captcha"
    RATE_LIMIT = "rate_limit"
    CLOUDFLARE = "cloudflare"
    LOGIN_REQUIRED = "login_required"
    NOT_FOUND = "not_found"
    NONE = "none"


@dataclass
class PoisonPillResult:
    detected: bool
    type: str
    confidence: float
    details: str


@dataclass
class FetchResult:
    url: str
    mode: str
    selector: str
    content_length: int
    content: str
    warnings: list[str]
    poison_pill: dict | None = None


POISON_PILL_PATTERNS = {
    PoisonPillType.PAYWALL: [
        r"subscribe to continue",
        r"subscription required",
        r"become a member",
        r"sign up to read",
        r"you've reached your limit",
        r"article limit reached",
    ],
    PoisonPillType.CAPTCHA: [
        r"verify you are human",
        r"captcha",
        r"robot verification",
        r"prove you're not a robot",
    ],
    PoisonPillType.RATE_LIMIT: [
        r"too many requests",
        r"rate limit exceeded",
        r"slow down",
    ],
    PoisonPillType.CLOUDFLARE: [
        r"checking your browser",
        r"cloudflare",
        r"ddos protection",
        r"please wait while we verify",
    ],
    PoisonPillType.LOGIN_REQUIRED: [
        r"sign in to continue",
        r"log in required",
        r"create an account",
        r"login required",
    ],
}

KNOWN_PAYWALL_DOMAINS = {
    "nytimes.com",
    "wsj.com",
    "washingtonpost.com",
    "ft.com",
    "bloomberg.com",
}


def fix_lazy_images(html_raw):
    """
    Promote data-src to src for lazy-loaded images (WeChat, Zhihu, etc.).
    Many Chinese platforms use data-src for the real image URL while src
    holds a tiny placeholder. html2text only reads src, so we swap them.
    """
    return re.sub(
        r'<img([^>]*?)\sdata-src="([^"]+)"([^>]*?)>',
        lambda m: f'<img{m.group(1)} src="{m.group(2)}"{m.group(3)}>',
        html_raw,
    )


# CSS selectors in priority order — the first match with enough content wins.
# Covers most blog/article platforms without needing per-site customization.
CONTENT_SELECTORS = [
    "article",
    "main",
    ".post-content",
    ".entry-content",
    ".article-content",
    ".article-body",
    ".article-detail",         # 36kr
    ".article-holder",         # InfoQ
    ".post_body",              # 163.com (NetEase)
    ".markdown-body",          # GitHub
    ".Post-RichText",          # Zhihu
    "#article_content",        # CSDN
    ".article-area",           # Juejin
    ".ssa-article",            # Toutiao
    '[role="article"]',
    '[itemprop="articleBody"]',
]

# WeChat has a unique DOM structure — try these first for mp.weixin.qq.com
WECHAT_SELECTORS = [
    "div#js_content",
    "div.rich_media_content",
]

# Minimum characters for a selector match to be considered "real content"
MIN_CONTENT_LENGTH = 200
MIN_GOOD_CONTENT_LENGTH = 500
STEALTH_FIRST_DOMAINS = {
    "mp.weixin.qq.com",
    "zhuanlan.zhihu.com",
    "www.zhihu.com",
    "juejin.cn",
}
EXCLUDED_DOMAINS = {
    "x.com": "Use the dedicated X/Twitter skill for platform scraping.",
    "twitter.com": "Use the dedicated X/Twitter skill for platform scraping.",
    "youtube.com": "Use the dedicated YouTube skill for video/channel scraping.",
    "www.youtube.com": "Use the dedicated YouTube skill for video/channel scraping.",
    "youtu.be": "Use the dedicated YouTube skill for video/channel scraping.",
}


def html_to_markdown(html_raw, max_chars=30000):
    """Convert raw HTML to clean Markdown."""
    import html2text

    html_raw = fix_lazy_images(html_raw)

    h = html2text.HTML2Text()
    h.ignore_links = False
    h.ignore_images = False
    h.body_width = 0       # No line wrapping
    h.skip_internal_links = True
    h.ignore_emphasis = False

    md = h.handle(html_raw)
    md = re.sub(r"\n{3,}", "\n\n", md).strip()
    return md[:max_chars]


def detect_poison_pill(url, content):
    domain = urlparse(url).netloc.lower().replace("www.", "")
    content_lower = content.lower()

    if domain in KNOWN_PAYWALL_DOMAINS and len(content) < MIN_GOOD_CONTENT_LENGTH:
        return PoisonPillResult(True, PoisonPillType.PAYWALL.value, 0.9, f"Short content from {domain}")

    for pill_type, patterns in POISON_PILL_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, content_lower):
                return PoisonPillResult(True, pill_type.value, 0.7, f"Pattern match: {pattern}")

    return PoisonPillResult(False, PoisonPillType.NONE.value, 0.0, "")


def get_domain(url):
    return urlparse(url).netloc.lower()


def check_scope(url):
    domain = get_domain(url)
    if domain in EXCLUDED_DOMAINS:
        raise ValueError(EXCLUDED_DOMAINS[domain])


def extract_content(page, url, max_chars=30000):
    """
    Try content selectors to find the article body.
    Returns (markdown_text, matched_selector).
    """
    is_wechat = "mp.weixin.qq.com" in url
    selectors = (WECHAT_SELECTORS + CONTENT_SELECTORS) if is_wechat else CONTENT_SELECTORS

    for selector in selectors:
        els = page.css(selector)
        if els:
            md = html_to_markdown(els[0].html_content, max_chars)
            if len(md) >= MIN_CONTENT_LENGTH:
                return md, selector

    # Fallback: convert the entire page
    md = html_to_markdown(page.html_content, max_chars)
    return md, "body(fallback)"


def _suppress_scrapling_logs():
    """Scrapling's logger is noisy (deprecation warnings, fetch info). Silence it."""
    logging.getLogger("scrapling").setLevel(logging.CRITICAL)


def fetch_fast(url, max_chars=30000, timeout=15):
    """
    Fast HTTP fetch — no JavaScript execution.
    Works for most blogs and static sites.
    """
    from scrapling.fetchers import Fetcher
    _suppress_scrapling_logs()

    page = Fetcher().get(url, timeout=timeout, stealthy_headers=True)
    return extract_content(page, url, max_chars)


def fetch_stealth(url, max_chars=30000, timeout=30000):
    """
    Headless browser fetch — executes JavaScript, bypasses anti-scraping.
    Required for: WeChat articles, Zhihu, Juejin, and other JS-rendered pages.
    Slower (~5-15s) but more reliable for protected content.
    """
    try:
        from scrapling.fetchers import StealthyFetcher
    except ModuleNotFoundError as exc:
        if exc.name == "patchright":
            raise RuntimeError(
                "Stealth mode requires patchright/browser extras for Scrapling. "
                "Install the needed browser dependency and retry."
            ) from exc
        raise
    _suppress_scrapling_logs()

    page = StealthyFetcher().fetch(
        url,
        headless=True,
        network_idle=True,
        timeout=timeout,
    )
    return extract_content(page, url, max_chars)


def fetch_jina(url, max_chars=30000, timeout=20):
    target = f"https://r.jina.ai/http://{url}" if "://" not in url else f"https://r.jina.ai/http://{url.split('://', 1)[1]}"
    request = Request(
        target,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "text/plain, text/markdown;q=0.9, */*;q=0.8",
        },
    )
    with urlopen(request, timeout=timeout) as response:
        content = response.read().decode("utf-8", errors="replace").strip()
    return content[:max_chars], "jina(markdown)"


def choose_auto_sequence(url):
    domain = get_domain(url)
    if domain in STEALTH_FIRST_DOMAINS:
        return ["stealth", "fast", "jina"]
    return ["fast", "stealth", "jina"]


def build_result(url, md, selector, mode, warnings):
    poison_pill = detect_poison_pill(url, md)
    if poison_pill.detected:
        warnings.append(f"blocking page detected: {poison_pill.type}")
    if len(md) < MIN_CONTENT_LENGTH:
        warnings.append("content is very short; extraction may be incomplete")
    return FetchResult(
        url=url,
        mode=mode,
        selector=selector,
        content_length=len(md),
        content=md,
        warnings=warnings,
        poison_pill=asdict(poison_pill),
    )


def run_strategy(strategy, url, max_chars):
    if strategy == "fast":
        md, selector = fetch_fast(url, max_chars)
        return md, selector, "fast"
    if strategy == "stealth":
        md, selector = fetch_stealth(url, max_chars)
        return md, selector, "stealth"
    if strategy == "jina":
        md, selector = fetch_jina(url, max_chars)
        return md, selector, "jina"
    raise ValueError(f"Unknown strategy: {strategy}")


def fetch(url, max_chars=30000, strategy="auto"):
    """
    Fetch URL and return a FetchResult.
    Auto mode chooses a bounded fallback chain and records warnings.
    """
    check_scope(url)
    warnings = []

    if strategy != "auto":
        md, selector, mode = run_strategy(strategy, url, max_chars)
        return build_result(url, md, selector, mode, warnings)

    last_result = None
    for current_strategy in choose_auto_sequence(url):
        try:
            md, selector, mode = run_strategy(current_strategy, url, max_chars)
            result = build_result(url, md, selector, mode, warnings.copy())
            last_result = result

            poison_pill = result.poison_pill or {}
            if result.content_length >= MIN_GOOD_CONTENT_LENGTH and not poison_pill.get("detected"):
                return result
        except Exception as exc:
            warnings.append(f"{current_strategy} failed: {type(exc).__name__}: {exc}")

    if last_result is not None:
        return last_result

    raise RuntimeError("All fetch strategies failed")


def main():
    if len(sys.argv) < 2:
        print(
            "Usage: python3 fetch.py <url> [max_chars] [--strategy auto|fast|stealth|jina]\n"
            "\n"
            "Options:\n"
            "  max_chars   Maximum output characters (default: 30000)\n"
            "  --strategy  Fetch strategy (default: auto)\n"
            "  --json      Output as JSON with metadata\n",
            file=sys.stderr,
        )
        sys.exit(1)

    url = sys.argv[1]
    args = sys.argv[2:]

    json_output = "--json" in args
    strategy = "auto"
    if "--strategy" in args:
        idx = args.index("--strategy")
        try:
            strategy = args[idx + 1]
        except IndexError:
            print("Error: --strategy requires a value", file=sys.stderr)
            sys.exit(1)
        del args[idx:idx + 2]
    if "--stealth" in args:
        strategy = "stealth"
        args.remove("--stealth")
    args = [a for a in args if a != "--json"]
    max_chars = int(args[0]) if args else 30000

    try:
        result = fetch(url, max_chars, strategy=strategy)

        if json_output:
            print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
        else:
            print(result.content)

    except Exception as e:
        error_msg = f"Error fetching {url}: {type(e).__name__}: {e}"
        if json_output:
            print(json.dumps({"url": url, "error": error_msg}, ensure_ascii=False))
        else:
            print(error_msg, file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    configure_stdio()
    check_dependencies()
    main()
