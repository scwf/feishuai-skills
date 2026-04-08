#!/usr/bin/env python3
"""
Universal web content extractor.
Returns clean Markdown and structured metadata for article-like pages.
"""

from enum import Enum
from dataclasses import dataclass, asdict, field
from urllib.parse import urljoin, urlparse, parse_qs, unquote
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from pathlib import Path
import sys
import re
import os
import json
import logging
import mimetypes


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
    try:
        import bs4  # noqa: F401
    except ImportError:
        missing.append("beautifulsoup4")

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
class AssetRef:
    kind: str
    index: int
    url: str | None
    normalized_url: str | None
    position: int
    alt: str = ""
    caption: str = ""
    source_attr: str = ""
    placeholder: bool = False
    downloadable: bool = False
    downloaded: bool = False
    local_path: str | None = None
    poster_url: str | None = None
    embed_url: str | None = None
    author: str | None = None
    duration_text: str | None = None
    notes: list[str] = field(default_factory=list)


@dataclass
class FidelityReport:
    dom_image_count: int
    effective_image_count: int
    markdown_image_count: int
    dom_video_count: int
    markdown_video_count: int
    downloaded_asset_count: int
    missing_images: int
    missing_videos: int
    issues: list[str]


@dataclass
class FetchResult:
    url: str
    mode: str
    selector: str
    title: str
    content_length: int
    content: str
    html_fragment: str
    warnings: list[str]
    assets: dict
    asset_count_summary: dict
    fidelity_report: dict
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

CONTENT_SELECTORS = [
    "article",
    "main",
    ".post-content",
    ".entry-content",
    ".article-content",
    ".article-body",
    ".article-detail",
    ".article-holder",
    ".post_body",
    ".markdown-body",
    ".Post-RichText",
    "#article_content",
    ".article-area",
    ".ssa-article",
    '[role="article"]',
    '[itemprop="articleBody"]',
]

WECHAT_SELECTORS = [
    "div#js_content",
    "div.rich_media_content",
]

WECHAT_TITLE_SELECTORS = [
    "h1#activity-name",
    ".rich_media_title",
    "title",
    "h1",
]

WECHAT_IMAGE_ATTRS = [
    "data-src",
    "data-backsrc",
    "src",
]

WECHAT_VIDEO_ATTRS = [
    "data-mpvid",
    "data-vid",
    "data-videoid",
    "vid",
]

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

VIDEO_TOKEN_PATTERN = re.compile(r"\[\[\[VIDEO_(\d+)\]\]\]")


def html_to_markdown(html_raw, max_chars=50000):
    """Convert raw HTML to clean Markdown."""
    import html2text

    h = html2text.HTML2Text()
    h.ignore_links = False
    h.ignore_images = False
    h.body_width = 0
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


def normalize_url(base_url, raw_url):
    if not raw_url:
        return None
    raw_url = raw_url.strip()
    if not raw_url:
        return None
    if raw_url.startswith("data:"):
        return raw_url
    if "%3A%2F%2F" in raw_url or "%3a%2f%2f" in raw_url:
        raw_url = unquote(raw_url)
    return urljoin(base_url, raw_url)


def clean_text(value):
    return re.sub(r"\s+", " ", value or "").strip()


def get_candidate_attr(tag, attr_names):
    for attr in attr_names:
        value = tag.get(attr)
        if value and clean_text(value):
            return clean_text(value), attr
    return None, ""


def get_title(page, url):
    selectors = WECHAT_TITLE_SELECTORS if "mp.weixin.qq.com" in url else ["h1", "title"]
    for selector in selectors:
        els = page.css(selector)
        if els:
            text = clean_text(getattr(els[0], "text", "") or "")
            if text:
                return text
    return ""


def sanitize_filename_fragment(text, fallback):
    text = clean_text(text).lower()
    text = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "_", text).strip("_")
    return text[:40] or fallback


def guess_extension_from_url(url, default=".bin"):
    if not url:
        return default
    parsed = urlparse(url)
    path = parsed.path or ""
    _, ext = os.path.splitext(path)
    if ext and len(ext) <= 6:
        return ext.lower()
    query = parsed.query or ""
    match = re.search(r"(?:wx_fmt|format|fmt)=([a-zA-Z0-9]+)", query)
    if match:
        return f".{match.group(1).lower()}"
    return default


def looks_like_image(content_type, data):
    content_type = (content_type or "").split(";", 1)[0].strip().lower()
    if content_type.startswith("image/"):
        return True
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return True
    if data.startswith(b"\xff\xd8\xff"):
        return True
    if data.startswith((b"GIF87a", b"GIF89a")):
        return True
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return True
    return False


def looks_like_video(content_type, data):
    content_type = (content_type or "").split(";", 1)[0].strip().lower()
    if content_type.startswith("video/"):
        return True
    if len(data) >= 12 and data[4:8] == b"ftyp":
        return True
    return False


def is_probable_tracking_pixel(tag, normalized_url):
    if not normalized_url:
        return True
    if normalized_url.startswith("data:"):
        width = clean_text(tag.get("width"))
        height = clean_text(tag.get("height"))
        if width in {"1", "0"} or height in {"1", "0"}:
            return True
        style = clean_text(tag.get("style"))
        if "width: 1px" in style or "height: 1px" in style:
            return True
    classes = " ".join(tag.get("class", []))
    if "qqmusic" in classes.lower():
        return True
    return False


def count_markdown_images(markdown):
    return len(re.findall(r"!\[[^\]]*\]\([^)]+\)", markdown))


def count_markdown_videos(markdown):
    return markdown.count("> 视频")


def build_video_placeholder(asset, rewritten_url_map):
    poster = asset.poster_url
    if poster and poster in rewritten_url_map:
        poster = rewritten_url_map[poster]
    details = []
    if asset.caption:
        details.append(asset.caption)
    if asset.author:
        details.append(f"作者：{asset.author}")
    if asset.duration_text:
        details.append(f"时长：{asset.duration_text}")
    if poster:
        details.append(f"封面：{poster}")
    if asset.local_path:
        details.append(f"本地文件：{asset.local_path}")
    if asset.embed_url:
        details.append(f"嵌入：{asset.embed_url}")
    if asset.url and asset.url != asset.embed_url:
        details.append(f"直链：{asset.url}")
    if not details:
        details.append("未拿到可直接下载的视频地址")
    body = "；".join(details)
    return f"> 视频 {asset.index}\n>\n> {body}"


def rewrite_markdown_asset_urls(markdown, rewritten_url_map):
    updated = markdown
    for original, rewritten in sorted(rewritten_url_map.items(), key=lambda item: len(item[0]), reverse=True):
        updated = updated.replace(original, rewritten)
    return updated


def extract_content_html(page, url):
    is_wechat = "mp.weixin.qq.com" in url
    selectors = (WECHAT_SELECTORS + CONTENT_SELECTORS) if is_wechat else CONTENT_SELECTORS
    for selector in selectors:
        els = page.css(selector)
        if els:
            html_fragment = els[0].html_content
            text_length = len(clean_text(getattr(els[0], "text", "") or ""))
            html_length = len(clean_text(html_fragment))
            if is_wechat and html_length >= MIN_CONTENT_LENGTH:
                return html_fragment, selector
            if text_length >= MIN_CONTENT_LENGTH or html_length >= MIN_CONTENT_LENGTH:
                return html_fragment, selector

    return page.html_content, "body(fallback)"


def extract_generic_assets(html_fragment, base_url):
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html_fragment, "html.parser")
    images = []
    videos = []

    for idx, tag in enumerate(soup.find_all("img"), start=1):
        raw_url, source_attr = get_candidate_attr(tag, ["src", "data-src", "data-original"])
        normalized_url = normalize_url(base_url, raw_url)
        placeholder = is_probable_tracking_pixel(tag, normalized_url)
        asset = AssetRef(
            kind="image",
            index=idx,
            url=raw_url,
            normalized_url=normalized_url,
            position=idx,
            alt=clean_text(tag.get("alt")),
            caption="",
            source_attr=source_attr,
            placeholder=placeholder,
            downloadable=bool(normalized_url and not normalized_url.startswith("data:")),
        )
        images.append(asset)

    return soup, images, videos


def find_nearest_caption(tag):
    candidates = []
    for relation in [tag.previous_sibling, tag.next_sibling]:
        if getattr(relation, "get_text", None):
            candidates.append(relation)
    if getattr(tag.parent, "find", None):
        for selector in ["figcaption", ".img_desc", ".image_desc", ".pic_desc"]:
            if selector.startswith("."):
                found = tag.parent.find(class_=selector[1:])
            else:
                found = tag.parent.find(selector)
            if found:
                candidates.append(found)
    for candidate in candidates:
        text = clean_text(candidate.get_text(" ", strip=True))
        if 0 < len(text) <= 120:
            return text
    return ""


def find_video_nodes(soup):
    seen_keys = set()
    nodes = []
    for tag in soup.find_all(True):
        classes = " ".join(tag.get("class", []))
        looks_like_video = (
            (tag.name == "span" and "video_iframe" in classes and tag.get("data-mpvid"))
            or tag.name == "mp-common-videosnap"
            or (tag.name == "video" and tag.get("src"))
            or (tag.name == "iframe" and any(
                token in clean_text(tag.get("src"))
                for token in ["video", "v.qq.com", "mp.weixin.qq.com/mp/readtemplate"]
            ))
        )
        if not looks_like_video:
            continue
        src_value = clean_text(tag.get("src") or tag.get("data-src"))
        parsed = urlparse(src_value) if src_value else None
        query_vid = ""
        if parsed:
            query_vid = clean_text(parse_qs(parsed.query).get("vid", [""])[0])
        video_key = clean_text(tag.get("data-mpvid")) or clean_text(tag.get("vid")) or query_vid or src_value or str(id(tag))
        if video_key in seen_keys:
            continue
        seen_keys.add(video_key)
        nodes.append(tag)
    return nodes


def get_first_attr(tag, candidate_attrs):
    for attr in candidate_attrs:
        value = clean_text(tag.get(attr))
        if value:
            return value
    return ""


def normalize_duration_text(value):
    value = clean_text(value)
    if not value:
        return ""
    if re.fullmatch(r"\d+", value):
        total_seconds = int(value)
        minutes, seconds = divmod(total_seconds, 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return f"{hours}:{minutes:02d}:{seconds:02d}"
        return f"{minutes}:{seconds:02d}"
    return value


def resolve_wechat_video_from_full_html(full_soup, base_url, tag, raw_url, embed_url):
    if full_soup is None:
        return None, None

    candidates = []
    vid = clean_text(tag.get("data-mpvid") or tag.get("data-vid") or tag.get("data-videoid") or tag.get("vid"))
    if not vid and embed_url:
        parsed = urlparse(embed_url)
        vid = clean_text(parse_qs(parsed.query).get("vid", [""])[0]) or (embed_url if embed_url.startswith("wxv_") else "")

    if vid:
        candidates.extend(full_soup.find_all("video", src=re.compile(re.escape(vid))))
    if raw_url:
        normalized_raw = normalize_url(base_url, raw_url)
        if normalized_raw:
            candidates.extend(full_soup.find_all("video", src=re.compile(re.escape(normalized_raw))))
    if embed_url and embed_url.startswith(("http://", "https://")):
        candidates.extend(full_soup.find_all("video", src=re.compile(re.escape(embed_url))))

    seen = set()
    for candidate in candidates:
        src = clean_text(candidate.get("src"))
        if not src or src in seen:
            continue
        seen.add(src)
        normalized_src = normalize_url(base_url, src)
        if normalized_src and ".mp4" in normalized_src:
            poster = clean_text(candidate.get("poster"))
            return normalized_src, normalize_url(base_url, poster)

    return None, None


def extract_wechat_assets(html_fragment, base_url, full_html=None):
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html_fragment, "html.parser")
    full_soup = BeautifulSoup(full_html, "html.parser") if full_html else None
    for noisy in soup.find_all(["script", "style"]):
        noisy.decompose()

    images = []
    effective_image_index = 0
    for position, tag in enumerate(soup.find_all("img"), start=1):
        raw_url, source_attr = get_candidate_attr(tag, WECHAT_IMAGE_ATTRS)
        normalized_url = normalize_url(base_url, raw_url)
        placeholder = is_probable_tracking_pixel(tag, normalized_url)
        caption = find_nearest_caption(tag)
        alt = clean_text(tag.get("alt")) or caption or f"Image {position}"
        if normalized_url and not normalized_url.startswith("data:"):
            tag["src"] = normalized_url
        if alt:
            tag["alt"] = alt
        asset = AssetRef(
            kind="image",
            index=position,
            url=raw_url,
            normalized_url=normalized_url,
            position=position,
            alt=alt,
            caption=caption,
            source_attr=source_attr,
            placeholder=placeholder,
            downloadable=bool(normalized_url and not normalized_url.startswith("data:")),
        )
        images.append(asset)
        if not placeholder and normalized_url and not normalized_url.startswith("data:"):
            effective_image_index += 1

    videos = []
    for index, tag in enumerate(find_video_nodes(soup), start=1):
        raw_url, source_attr = get_candidate_attr(tag, ["src", "data-src"])
        poster_url, _ = get_candidate_attr(tag, ["data-cover", "data-poster", "poster"])
        author = get_first_attr(tag, [
            "data-nickname",
            "data-author",
            "data-username",
            "nickname",
            "author",
        ])
        duration_text = normalize_duration_text(get_first_attr(tag, [
            "data-duration",
            "data-time",
            "data-play-length",
            "data-playtime",
            "duration",
        ]))
        embed_url = normalize_url(base_url, raw_url)
        for attr in WECHAT_VIDEO_ATTRS:
            value = clean_text(tag.get(attr))
            if value:
                embed_url = embed_url or value
                break
        normalized_url = normalize_url(base_url, raw_url)
        if not normalized_url and embed_url:
            video_match = soup.find("video", src=re.compile(re.escape(clean_text(embed_url))))
            if video_match:
                raw_url = clean_text(video_match.get("src"))
                source_attr = "src"
                normalized_url = normalize_url(base_url, raw_url)
                poster_url = poster_url or clean_text(video_match.get("poster"))
        if not normalized_url and embed_url and embed_url.startswith("wxv_"):
            video_match = soup.find("video", src=re.compile(re.escape(embed_url)))
            if video_match:
                raw_url = clean_text(video_match.get("src"))
                source_attr = "src"
                normalized_url = normalize_url(base_url, raw_url)
                poster_url = poster_url or clean_text(video_match.get("poster"))
        resolved_url, resolved_poster = resolve_wechat_video_from_full_html(full_soup, base_url, tag, raw_url, embed_url)
        if resolved_url:
            normalized_url = resolved_url
            if source_attr != "src":
                source_attr = "resolved_full_html"
            poster_url = poster_url or resolved_poster
        normalized_poster = normalize_url(base_url, poster_url)
        caption = clean_text(tag.get("data-title") or tag.get("data-desc") or tag.get("aria-label") or "")
        if not caption:
            caption = find_nearest_caption(tag)
        asset = AssetRef(
            kind="video",
            index=index,
            url=normalized_url,
            normalized_url=normalized_url,
            position=index,
            alt="",
            caption=caption,
            source_attr=source_attr,
            placeholder=False,
            downloadable=bool(normalized_url and normalized_url.startswith(("http://", "https://"))),
            poster_url=normalized_poster,
            embed_url=embed_url,
            author=author or None,
            duration_text=duration_text or None,
            notes=[] if normalized_url else ["No direct video URL extracted"],
        )
        if tag.name == "mp-common-videosnap" and not normalized_url:
            asset.notes.append("Finder/视频号卡片未暴露可直接下载的视频流，已保留封面和卡片元数据占位")
        token = f"[[[VIDEO_{index}]]]"
        replacement = soup.new_tag("p")
        replacement.string = token
        tag.replace_with(replacement)
        videos.append(asset)

    return soup, images, videos


def materialize_markdown(html_fragment, url, max_chars, full_html=None):
    if "mp.weixin.qq.com" in url:
        soup, images, videos = extract_wechat_assets(html_fragment, url, full_html=full_html)
    else:
        soup, images, videos = extract_generic_assets(html_fragment, url)

    html_for_markdown = str(soup)
    markdown = html_to_markdown(html_for_markdown, max_chars * 2)
    for asset in videos:
        markdown = markdown.replace(f"[[[VIDEO_{asset.index}]]]", build_video_placeholder(asset, {}))
    markdown = re.sub(r"\n{3,}", "\n\n", markdown).strip()
    return html_for_markdown, markdown[:max_chars], images, videos


def compute_asset_summary(images, videos):
    effective_images = [
        asset for asset in images
        if asset.normalized_url and not asset.normalized_url.startswith("data:") and not asset.placeholder
    ]
    downloadable_videos = [
        asset for asset in videos
        if asset.normalized_url and asset.normalized_url.startswith(("http://", "https://"))
    ]
    return {
        "images_total": len(images),
        "images_effective": len(effective_images),
        "images_placeholders": len(images) - len(effective_images),
        "videos_total": len(videos),
        "videos_downloadable": len(downloadable_videos),
    }


def compute_fidelity(images, videos, markdown):
    effective_image_count = len([
        asset for asset in images
        if asset.normalized_url and not asset.normalized_url.startswith("data:") and not asset.placeholder
    ])
    markdown_image_count = count_markdown_images(markdown)
    markdown_video_count = count_markdown_videos(markdown)
    issues = []
    if markdown_image_count < effective_image_count:
        issues.append(
            f"Markdown contains {markdown_image_count} image references but DOM had {effective_image_count} effective images."
        )
    if markdown_video_count < len(videos):
        issues.append(
            f"Markdown contains {markdown_video_count} video placeholders but DOM had {len(videos)} video nodes."
        )

    return FidelityReport(
        dom_image_count=len(images),
        effective_image_count=effective_image_count,
        markdown_image_count=markdown_image_count,
        dom_video_count=len(videos),
        markdown_video_count=markdown_video_count,
        downloaded_asset_count=0,
        missing_images=max(effective_image_count - markdown_image_count, 0),
        missing_videos=max(len(videos) - markdown_video_count, 0),
        issues=issues,
    )


def download_binary(url, destination):
    request = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://mp.weixin.qq.com/",
        },
    )
    with urlopen(request, timeout=30) as response:
        data = response.read()
        content_type = response.headers.get("Content-Type", "")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data)
    return content_type, data


def localize_assets(result, asset_dir):
    asset_root = Path(asset_dir)
    images_dir = asset_root / "images"
    videos_dir = asset_root / "videos"
    rewritten_url_map = {}
    downloaded_count = 0
    warnings = list(result.warnings)

    for asset in result.assets["images"]:
        normalized_url = asset["normalized_url"]
        if not normalized_url or normalized_url.startswith("data:") or asset["placeholder"]:
            continue
        ext = guess_extension_from_url(normalized_url, default=".img")
        filename = f"{asset['index']:02d}_{sanitize_filename_fragment(asset['alt'], 'image')}{ext}"
        destination = images_dir / filename
        try:
            content_type, data = download_binary(normalized_url, destination)
            if not looks_like_image(content_type, data):
                destination.unlink(missing_ok=True)
                raise ValueError(f"downloaded content was not an image (content-type: {content_type or 'unknown'})")
            if destination.suffix in {"", ".img", ".bin"} and content_type:
                guessed = mimetypes.guess_extension(content_type.split(";")[0].strip()) or destination.suffix
                if guessed and guessed != destination.suffix:
                    new_destination = destination.with_suffix(guessed)
                    destination.rename(new_destination)
                    destination = new_destination
            asset["downloaded"] = True
            asset["local_path"] = destination.as_posix()
            rewritten_url_map[normalized_url] = f"./{asset_root.name}/images/{destination.name}"
            downloaded_count += 1
        except (HTTPError, URLError, OSError, ValueError) as exc:
            warnings.append(f"failed to download image {asset['index']}: {type(exc).__name__}: {exc}")

    for asset in result.assets["videos"]:
        poster_url = asset.get("poster_url")
        if poster_url and poster_url.startswith(("http://", "https://")):
            ext = guess_extension_from_url(poster_url, default=".jpg")
            filename = f"{asset['index']:02d}_video_poster{ext}"
            destination = videos_dir / filename
            try:
                content_type, data = download_binary(poster_url, destination)
                if not looks_like_image(content_type, data):
                    destination.unlink(missing_ok=True)
                    raise ValueError(f"downloaded content was not an image (content-type: {content_type or 'unknown'})")
                rewritten_url_map[poster_url] = f"./{asset_root.name}/videos/{destination.name}"
                asset.setdefault("notes", []).append(f"Poster localized to {destination.as_posix()}")
            except (HTTPError, URLError, OSError, ValueError) as exc:
                warnings.append(f"failed to download video poster {asset['index']}: {type(exc).__name__}: {exc}")

        normalized_url = asset.get("normalized_url")
        if normalized_url and normalized_url.startswith(("http://", "https://")):
            ext = guess_extension_from_url(normalized_url, default=".mp4")
            filename = f"{asset['index']:02d}_video{ext}"
            destination = videos_dir / filename
            try:
                content_type, data = download_binary(normalized_url, destination)
                if not looks_like_video(content_type, data):
                    destination.unlink(missing_ok=True)
                    raise ValueError(f"downloaded content was not a video (content-type: {content_type or 'unknown'})")
                asset["downloaded"] = True
                asset["local_path"] = destination.as_posix()
                rewritten_url_map[normalized_url] = f"./{asset_root.name}/videos/{destination.name}"
                downloaded_count += 1
            except (HTTPError, URLError, OSError, ValueError) as exc:
                warnings.append(f"failed to download video {asset['index']}: {type(exc).__name__}: {exc}")

    updated_markdown = rewrite_markdown_asset_urls(result.content, rewritten_url_map)
    for asset in result.assets["videos"]:
        updated_markdown = updated_markdown.replace(
            build_video_placeholder(AssetRef(**asset), {}),
            build_video_placeholder(AssetRef(**asset), rewritten_url_map),
        )

    fidelity = dict(result.fidelity_report)
    fidelity["downloaded_asset_count"] = downloaded_count

    return FetchResult(
        url=result.url,
        mode=result.mode,
        selector=result.selector,
        title=result.title,
        content_length=len(updated_markdown),
        content=updated_markdown,
        html_fragment=result.html_fragment,
        warnings=warnings,
        assets=result.assets,
        asset_count_summary=result.asset_count_summary,
        fidelity_report=fidelity,
        poison_pill=result.poison_pill,
    )


def build_result(url, html_fragment, markdown, selector, mode, warnings, title, images, videos):
    fidelity = compute_fidelity(images, videos, markdown)
    poison_pill = detect_poison_pill(url, markdown)
    warnings = list(warnings)
    if poison_pill.detected:
        warnings.append(f"blocking page detected: {poison_pill.type}")
    if len(markdown) < MIN_CONTENT_LENGTH:
        warnings.append("content is very short; extraction may be incomplete")
    if fidelity.issues:
        warnings.extend(f"fidelity warning: {issue}" for issue in fidelity.issues)

    return FetchResult(
        url=url,
        mode=mode,
        selector=selector,
        title=title,
        content_length=len(markdown),
        content=markdown,
        html_fragment=html_fragment,
        warnings=warnings,
        assets={
            "images": [asdict(asset) for asset in images],
            "videos": [asdict(asset) for asset in videos],
        },
        asset_count_summary=compute_asset_summary(images, videos),
        fidelity_report=asdict(fidelity),
        poison_pill=asdict(poison_pill),
    )


def _suppress_scrapling_logs():
    """Scrapling's logger is noisy (deprecation warnings, fetch info). Silence it."""
    logging.getLogger("scrapling").setLevel(logging.CRITICAL)


def fetch_fast(url, max_chars=50000, timeout=15):
    from scrapling.fetchers import Fetcher

    _suppress_scrapling_logs()
    page = Fetcher().get(url, timeout=timeout, stealthy_headers=True)
    html_fragment, selector = extract_content_html(page, url)
    html_fragment, markdown, images, videos = materialize_markdown(
        html_fragment,
        url,
        max_chars,
        full_html=page.html_content,
    )
    return html_fragment, markdown, selector, get_title(page, url), images, videos


def fetch_stealth(url, max_chars=50000, timeout=30000):
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
    html_fragment, selector = extract_content_html(page, url)
    html_fragment, markdown, images, videos = materialize_markdown(
        html_fragment,
        url,
        max_chars,
        full_html=page.html_content,
    )
    return html_fragment, markdown, selector, get_title(page, url), images, videos


def fetch_jina(url, max_chars=50000, timeout=20):
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

    markdown = content[:max_chars]
    fidelity = FidelityReport(
        dom_image_count=0,
        effective_image_count=0,
        markdown_image_count=count_markdown_images(markdown),
        dom_video_count=0,
        markdown_video_count=count_markdown_videos(markdown),
        downloaded_asset_count=0,
        missing_images=0,
        missing_videos=0,
        issues=["Jina fallback does not provide DOM-level fidelity guarantees."],
    )
    return FetchResult(
        url=url,
        mode="jina",
        selector="jina(markdown)",
        title="",
        content_length=len(markdown),
        content=markdown,
        html_fragment="",
        warnings=["fidelity warning: Jina fallback does not provide DOM-level fidelity guarantees."],
        assets={"images": [], "videos": []},
        asset_count_summary={
            "images_total": 0,
            "images_effective": 0,
            "images_placeholders": 0,
            "videos_total": 0,
            "videos_downloadable": 0,
        },
        fidelity_report=asdict(fidelity),
        poison_pill=asdict(detect_poison_pill(url, markdown)),
    )


def choose_auto_sequence(url):
    domain = get_domain(url)
    if domain in STEALTH_FIRST_DOMAINS:
        return ["stealth", "fast", "jina"]
    return ["fast", "stealth", "jina"]


def run_strategy(strategy, url, max_chars):
    if strategy == "fast":
        html_fragment, markdown, selector, title, images, videos = fetch_fast(url, max_chars)
        return build_result(url, html_fragment, markdown, selector, "fast", [], title, images, videos)
    if strategy == "stealth":
        html_fragment, markdown, selector, title, images, videos = fetch_stealth(url, max_chars)
        return build_result(url, html_fragment, markdown, selector, "stealth", [], title, images, videos)
    if strategy == "jina":
        return fetch_jina(url, max_chars)
    raise ValueError(f"Unknown strategy: {strategy}")


def fetch(url, max_chars=50000, strategy="auto", download_assets_dir=None):
    """
    Fetch URL and return a FetchResult.
    Auto mode chooses a bounded fallback chain and records warnings.
    """
    check_scope(url)
    warnings = []

    if strategy != "auto":
        result = run_strategy(strategy, url, max_chars)
        result.warnings = list(dict.fromkeys(warnings + result.warnings))
        if download_assets_dir:
            result = localize_assets(result, download_assets_dir)
        return result

    last_result = None
    for current_strategy in choose_auto_sequence(url):
        try:
            result = run_strategy(current_strategy, url, max_chars)
            result.warnings = list(dict.fromkeys(warnings + result.warnings))
            last_result = result

            poison_pill = result.poison_pill or {}
            if result.content_length >= MIN_GOOD_CONTENT_LENGTH and not poison_pill.get("detected"):
                if download_assets_dir:
                    result = localize_assets(result, download_assets_dir)
                return result
        except Exception as exc:
            warnings.append(f"{current_strategy} failed: {type(exc).__name__}: {exc}")

    if last_result is not None:
        if download_assets_dir:
            last_result = localize_assets(last_result, download_assets_dir)
        last_result.warnings = list(dict.fromkeys(warnings + last_result.warnings))
        return last_result

    raise RuntimeError("All fetch strategies failed")


def main():
    help_text = (
        "Usage: python3 fetch.py <url> [max_chars] [options]\n"
        "\n"
        "Arguments:\n"
        "  <url>               Required. Target page URL to fetch.\n"
        "  [max_chars]         Optional. Maximum Markdown characters to keep.\n"
        "                      Default: 50000.\n"
        "\n"
        "Options:\n"
        "  --strategy VALUE    Fetch strategy to use.\n"
        "                      Allowed: auto, fast, stealth, jina.\n"
        "                      Default: auto.\n"
        "                      Use stealth first for JS-heavy pages such as WeChat.\n"
        "  --stealth           Shortcut for --strategy stealth.\n"
        "                      Default: off.\n"
        "  --json              Return structured JSON metadata instead of plain Markdown.\n"
        "                      Default: off.\n"
        "  --include-content   Include full Markdown content in JSON output.\n"
        "                      Only applies when --json is set.\n"
        "                      Default: off.\n"
        "  --include-html      Include extracted HTML fragment in JSON output.\n"
        "                      Only applies when --json is set.\n"
        "                      Default: off.\n"
        "  --download-assets DIR\n"
        "                      Download localizable images/videos into DIR and rewrite\n"
        "                      Markdown asset links to local relative paths.\n"
        "                      Default: off.\n"
        "  -h, --help          Show this help message and exit.\n"
        "\n"
        "Behavior notes:\n"
        "  - Plain output mode prints Markdown to stdout.\n"
        "  - JSON mode is lightweight by default; content/html are omitted unless\n"
        "    explicitly requested.\n"
        "  - For WeChat articles, recommended first pass is:\n"
        "      fetch.py <url> --strategy stealth --json\n"
    )

    if any(arg in {"-h", "--help"} for arg in sys.argv[1:]):
        print(help_text)
        sys.exit(0)

    if len(sys.argv) < 2:
        print(
            help_text,
            file=sys.stderr,
        )
        sys.exit(1)

    url = sys.argv[1]
    args = sys.argv[2:]

    json_output = "--json" in args
    strategy = "auto"
    download_assets_dir = None
    include_content = "--include-content" in args
    include_html = "--include-html" in args

    if "--strategy" in args:
        idx = args.index("--strategy")
        try:
            strategy = args[idx + 1]
        except IndexError:
            print("Error: --strategy requires a value", file=sys.stderr)
            sys.exit(1)
        del args[idx:idx + 2]
    if "--download-assets" in args:
        idx = args.index("--download-assets")
        try:
            download_assets_dir = args[idx + 1]
        except IndexError:
            print("Error: --download-assets requires a directory", file=sys.stderr)
            sys.exit(1)
        del args[idx:idx + 2]
    if "--stealth" in args:
        strategy = "stealth"
        args.remove("--stealth")

    args = [a for a in args if a not in {"--json", "--include-content", "--include-html"}]
    max_chars = int(args[0]) if args else 50000

    try:
        result = fetch(url, max_chars, strategy=strategy, download_assets_dir=download_assets_dir)

        if json_output:
            payload = asdict(result)
            if not include_content:
                payload["content"] = ""
            if not include_html:
                payload["html_fragment"] = ""
            print(json.dumps(payload, ensure_ascii=False, indent=2))
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
