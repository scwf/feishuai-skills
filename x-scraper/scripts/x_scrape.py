#!/usr/bin/env python3
"""Standalone X scraper that outputs raw tweet content only."""

from __future__ import annotations

import argparse
import json
import logging
import os
import random
import re
import socket
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from json import JSONDecodeError
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from x_scrape_env import ENV_KEYS, load_default_env
from x_scrape_export import build_output_paths, build_run_metadata, render_markdown

logger = logging.getLogger("x_scraper")
MAX_CONSECUTIVE_NO_PROGRESS_PAGES = 3
RETRYABLE_BACKOFF_SECONDS = 1.0

WEB_BEARER_TOKEN = (
    "Bearer AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs"
    "%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA"
)

QUERY_IDS = {
    "UserByScreenName": "xmU6X_CKVnQ5lSrCbAmJsg",
    "UserTweets": "E3opETHurmVJflFsUBVuUQ",
}

DEFAULT_FEATURES = {
    "rweb_tipjar_consumption_enabled": True,
    "responsive_web_graphql_exclude_directive_enabled": True,
    "verified_phone_label_enabled": False,
    "creator_subscriptions_tweet_preview_api_enabled": True,
    "responsive_web_graphql_timeline_navigation_enabled": True,
    "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
    "communities_web_enable_tweet_community_results_fetch": True,
    "c9s_tweet_anatomy_moderator_badge_enabled": True,
    "articles_preview_enabled": True,
    "responsive_web_edit_tweet_api_enabled": True,
    "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
    "view_counts_everywhere_api_enabled": True,
    "longform_notetweets_consumption_enabled": True,
    "responsive_web_twitter_article_tweet_consumption_enabled": True,
    "tweet_awards_web_tipping_enabled": False,
    "creator_subscriptions_quote_tweet_preview_enabled": False,
    "freedom_of_speech_not_reach_fetch_enabled": True,
    "standardized_nudges_misinfo": True,
    "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
    "rweb_video_timestamps_enabled": True,
    "longform_notetweets_rich_text_read_enabled": True,
    "longform_notetweets_inline_media_enabled": True,
    "responsive_web_enhance_cards_enabled": False,
    "profile_label_improvements_pcf_label_in_post_enabled": False,
    "highlights_tweets_tab_ui_enabled": True,
    "subscriptions_verification_info_is_identity_verified_enabled": True,
    "subscriptions_verification_info_verified_since_enabled": True,
    "hidden_profile_subscriptions_enabled": True,
    "responsive_web_twitter_article_notes_tab_enabled": True,
    "subscriptions_feature_can_gift_premium": True,
}

DEFAULT_FIELD_TOGGLES = {"withArticlePlainText": False}

UA_PROFILES = [
    {
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "impersonate": "chrome131",
    },
    {
        "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "impersonate": "chrome131",
    },
]

TWITTER_DATE_FORMAT = "%a %b %d %H:%M:%S %z %Y"


@dataclass
class AccountState:
    auth_token: str
    ct0: str
    index: int
    request_count: int = 0
    cooldown_until: float = 0.0
    is_dead: bool = False

    @property
    def is_available(self) -> bool:
        return not self.is_dead and self.cooldown_until <= time.time()


class AccountPool:
    default_cooldown_seconds = 900

    def __init__(self, credentials: List[Tuple[str, str]]):
        if not credentials:
            raise ValueError("Missing X credentials.")
        self.accounts = [
            AccountState(auth_token=auth.strip(), ct0=ct0.strip(), index=index)
            for index, (auth, ct0) in enumerate(credentials)
        ]
        self._cursor = 0

    @classmethod
    def from_env(cls) -> "AccountPool":
        combo = os.getenv("X_AUTH_CREDENTIALS", "").strip()
        if combo:
            credentials: List[Tuple[str, str]] = []
            for pair in combo.split("|"):
                pair = pair.strip()
                if not pair:
                    continue
                auth_token, sep, ct0 = pair.partition(":")
                if not sep or not auth_token or not ct0:
                    raise ValueError("Invalid X_AUTH_CREDENTIALS format.")
                credentials.append((auth_token, ct0))
            return cls(credentials)

        auth_token = os.getenv("TWITTER_AUTH_TOKEN", "").strip()
        ct0 = os.getenv("TWITTER_CT0", "").strip() or os.getenv("XCSRF_TOKEN", "").strip()
        if auth_token and ct0:
            return cls([(auth_token, ct0)])

        raise ValueError(
            "Provide X credentials via X_AUTH_CREDENTIALS or TWITTER_AUTH_TOKEN + TWITTER_CT0."
        )

    def get_next(self) -> Optional[AccountState]:
        total = len(self.accounts)
        for _ in range(total):
            account = self.accounts[self._cursor]
            self._cursor = (self._cursor + 1) % total
            if account.is_available:
                account.request_count += 1
                return account
        return None

    def mark_rate_limited(self, account: AccountState, retry_after: int) -> None:
        account.cooldown_until = time.time() + max(retry_after, 1)

    def mark_dead(self, account: AccountState) -> None:
        account.is_dead = True

    def wait_for_available(self, timeout: int = 300) -> Optional[AccountState]:
        deadline = time.time() + timeout
        while time.time() < deadline:
            account = self.get_next()
            if account:
                return account
            if all(item.is_dead for item in self.accounts):
                return None
            time.sleep(3)
        return None


class XClientError(RuntimeError):
    pass


class RateLimitError(XClientError):
    def __init__(self, retry_after: int = 900):
        self.retry_after = retry_after
        super().__init__(f"Rate limited for {retry_after}s")


class AuthError(XClientError):
    pass


class ApiError(XClientError):
    pass


class NetworkError(XClientError):
    pass


class RequestTimeoutError(NetworkError):
    pass


@dataclass
class FetchRunResult:
    tweets: List["TweetRecord"]
    status: str
    pages_fetched: int = 0
    partial_failure_reason: Optional[str] = None


@dataclass
class ScrapeArtifacts:
    resolved_username: str
    resolved_alias: Optional[str]
    mode: str
    limit: Optional[int]
    max_fetch: Optional[int]
    since_date: Optional[str]
    run_result: FetchRunResult
    exports: List[Dict[str, Any]]
    json_path: Path
    md_path: Path


@dataclass
class TweetMedia:
    type: str = ""
    url: str = ""
    preview_url: str = ""
    alt_text: str = ""
    width: int = 0
    height: int = 0
    duration_ms: int = 0


@dataclass
class TweetRecord:
    id: str = ""
    text: str = ""
    created_at: Optional[datetime] = None
    username: str = ""
    display_name: str = ""
    lang: str = ""
    source: str = ""
    reply_count: int = 0
    retweet_count: int = 0
    like_count: int = 0
    view_count: int = 0
    bookmark_count: int = 0
    quote_count: int = 0
    urls: List[str] = field(default_factory=list)
    media: List[TweetMedia] = field(default_factory=list)
    is_retweet: bool = False
    retweeted_from_username: Optional[str] = None
    retweeted_from_display_name: Optional[str] = None
    retweeted_original_id: Optional[str] = None
    retweeted_original_url: Optional[str] = None
    retweeted_original_text: Optional[str] = None
    in_reply_to_id: Optional[str] = None
    in_reply_to_username: Optional[str] = None

    @property
    def permalink(self) -> str:
        return f"https://x.com/{self.username}/status/{self.id}"

    def to_export_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "url": self.permalink,
            "username": self.username,
            "display_name": self.display_name,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "lang": self.lang,
            "source": self.source,
            "metrics": {
                "reply_count": self.reply_count,
                "retweet_count": self.retweet_count,
                "like_count": self.like_count,
                "view_count": self.view_count,
                "bookmark_count": self.bookmark_count,
                "quote_count": self.quote_count,
            },
            "urls": list(self.urls),
            "media": [asdict(item) for item in self.media],
            "is_retweet": self.is_retweet,
            "retweeted_from_username": self.retweeted_from_username,
            "retweeted_from_display_name": self.retweeted_from_display_name,
            "retweeted_original_id": self.retweeted_original_id,
            "retweeted_original_url": self.retweeted_original_url,
            "retweeted_original_text": self.retweeted_original_text,
            "in_reply_to_id": self.in_reply_to_id,
            "in_reply_to_username": self.in_reply_to_username,
            "original_text": self.text,
        }


class TweetParser:
    @staticmethod
    def parse_user_id(response_json: Dict[str, Any]) -> Optional[str]:
        try:
            result = response_json["data"]["user"]["result"]
            if result.get("__typename") == "UserUnavailable":
                return None
            return result["rest_id"]
        except (KeyError, TypeError):
            return None

    def parse_timeline(self, response_json: Dict[str, Any]) -> Tuple[List[TweetRecord], Optional[str]]:
        tweets: List[TweetRecord] = []
        next_cursor = None
        seen_ids = set()

        instructions = (
            response_json.get("data", {})
            .get("user", {})
            .get("result", {})
            .get("timeline_v2", {})
            .get("timeline", {})
            .get("instructions", [])
        )

        for instruction in instructions:
            inst_type = instruction.get("type", "")
            if inst_type == "TimelineAddEntries":
                for entry in instruction.get("entries", []):
                    entry_id = entry.get("entryId", "")
                    if entry_id.startswith("tweet-"):
                        tweet = self._parse_tweet_entry(entry)
                        if tweet and tweet.id not in seen_ids:
                            seen_ids.add(tweet.id)
                            tweets.append(tweet)
                    elif entry_id.startswith("cursor-bottom-"):
                        cursor_value = entry.get("content", {}).get("value", "")
                        if cursor_value:
                            next_cursor = cursor_value
                    elif entry_id.startswith("profile-conversation-") or entry_id.startswith("homeConversation-"):
                        for tweet in self._parse_module_entry(entry):
                            if tweet.id not in seen_ids:
                                seen_ids.add(tweet.id)
                                tweets.append(tweet)
            elif inst_type == "TimelinePinEntry":
                tweet = self._parse_tweet_entry(instruction.get("entry", {}))
                if tweet and tweet.id not in seen_ids:
                    seen_ids.add(tweet.id)
                    tweets.append(tweet)

        return tweets, next_cursor

    def _parse_tweet_entry(self, entry: Dict[str, Any]) -> Optional[TweetRecord]:
        content = entry.get("content", {})
        item_content = content.get("itemContent", {})
        if item_content.get("promotedMetadata"):
            return None
        result = item_content.get("tweet_results", {}).get("result", {})
        return self._parse_tweet_result(result)

    def _parse_module_entry(self, entry: Dict[str, Any]) -> List[TweetRecord]:
        result: List[TweetRecord] = []
        for item in entry.get("content", {}).get("items", []):
            item_content = item.get("item", {}).get("itemContent", {})
            parsed = self._parse_tweet_result(item_content.get("tweet_results", {}).get("result", {}))
            if parsed:
                result.append(parsed)
        return result

    def _parse_tweet_result(self, result: Dict[str, Any]) -> Optional[TweetRecord]:
        if not result:
            return None

        typename = result.get("__typename", "")
        if typename == "TweetWithVisibilityResults":
            result = result.get("tweet", {})
            typename = result.get("__typename", "")
        if typename in ("TweetTombstone", "TweetUnavailable"):
            return None

        legacy = result.get("legacy", {})
        if not legacy:
            return None

        user_result = result.get("core", {}).get("user_results", {}).get("result", {})
        user_legacy = user_result.get("legacy", {})

        tweet = TweetRecord(
            id=legacy.get("id_str", result.get("rest_id", "")),
            text=self._extract_full_text(result, legacy),
            created_at=self._parse_date(legacy.get("created_at", "")),
            username=user_legacy.get("screen_name", ""),
            display_name=user_legacy.get("name", ""),
            lang=legacy.get("lang", ""),
            source=self._clean_source(result.get("source", "")),
            reply_count=legacy.get("reply_count", 0),
            retweet_count=legacy.get("retweet_count", 0),
            like_count=legacy.get("favorite_count", 0),
            quote_count=legacy.get("quote_count", 0),
            bookmark_count=legacy.get("bookmark_count", 0),
            urls=self._extract_urls(legacy),
            media=self._extract_media(legacy),
            in_reply_to_id=legacy.get("in_reply_to_status_id_str"),
            in_reply_to_username=legacy.get("in_reply_to_screen_name"),
        )

        views = result.get("views", {})
        if views.get("count"):
            try:
                tweet.view_count = int(views["count"])
            except (TypeError, ValueError):
                tweet.view_count = 0

        retweeted_status = legacy.get("retweeted_status_result", {}).get("result")
        if retweeted_status:
            tweet.is_retweet = True
            retweeted_tweet = self._parse_tweet_result(retweeted_status)
            if retweeted_tweet:
                tweet.retweeted_from_username = retweeted_tweet.username or None
                tweet.retweeted_from_display_name = retweeted_tweet.display_name or None
                tweet.retweeted_original_id = retweeted_tweet.id or None
                tweet.retweeted_original_url = retweeted_tweet.permalink if retweeted_tweet.id else None
                tweet.retweeted_original_text = retweeted_tweet.text or None

        return tweet

    def _extract_full_text(self, result: Dict[str, Any], legacy: Dict[str, Any]) -> str:
        note_tweet = (
            result.get("note_tweet", {})
            .get("note_tweet_results", {})
            .get("result", {})
        )
        note_text = note_tweet.get("text", "")
        return note_text or legacy.get("full_text", "")

    def _parse_date(self, date_str: str) -> Optional[datetime]:
        if not date_str:
            return None
        try:
            return datetime.strptime(date_str, TWITTER_DATE_FORMAT)
        except ValueError:
            return None

    def _clean_source(self, source_html: str) -> str:
        if not source_html:
            return ""
        match = re.search(r">(.+?)</a>", source_html)
        return match.group(1) if match else source_html

    def _extract_urls(self, legacy: Dict[str, Any]) -> List[str]:
        urls: List[str] = []
        for url_entity in legacy.get("entities", {}).get("urls", []):
            expanded = url_entity.get("expanded_url", "")
            if not expanded:
                continue
            if "/status/" in expanded and ("x.com" in expanded or "twitter.com" in expanded):
                current_id = legacy.get("id_str", "")
                if expanded.split("/status/")[-1].split("?")[0] == current_id:
                    continue
            urls.append(expanded)
        return urls

    def _extract_media(self, legacy: Dict[str, Any]) -> List[TweetMedia]:
        media_list: List[TweetMedia] = []
        for item in legacy.get("extended_entities", {}).get("media", []):
            media = TweetMedia(
                type=item.get("type", ""),
                alt_text=item.get("ext_alt_text", ""),
            )
            if media.type == "photo":
                media.url = item.get("media_url_https", "")
                media.preview_url = media.url
            elif media.type in {"video", "animated_gif"}:
                variants = item.get("video_info", {}).get("variants", [])
                mp4_variants = [entry for entry in variants if entry.get("content_type") == "video/mp4"]
                if mp4_variants:
                    best = max(mp4_variants, key=lambda entry: entry.get("bitrate", 0))
                    media.url = best.get("url", "")
                media.preview_url = item.get("media_url_https", "")
                media.duration_ms = item.get("video_info", {}).get("duration_millis", 0)
            original_info = item.get("original_info", {})
            media.width = original_info.get("width", 0)
            media.height = original_info.get("height", 0)
            media_list.append(media)
        return media_list


class XClient:
    graphql_base = "https://x.com/i/api/graphql"

    def __init__(self, account_pool: AccountPool, timeout: int = 30, max_retries: int = 3):
        self.account_pool = account_pool
        self.timeout = timeout
        self.max_retries = max_retries
        self.parser = TweetParser()
        self._user_id_cache: Dict[str, str] = {}
        self._use_curl_cffi = False
        try:
            from curl_cffi import requests as curl_requests  # type: ignore

            self._curl_requests = curl_requests
            self._use_curl_cffi = True
        except ImportError:
            self._curl_requests = None

    def _pick_profile(self) -> Dict[str, str]:
        return random.choice(UA_PROFILES)

    def _build_headers(self, account: AccountState, user_agent: str) -> Dict[str, str]:
        return {
            "authorization": WEB_BEARER_TOKEN,
            "x-csrf-token": account.ct0,
            "x-twitter-active-user": "yes",
            "x-twitter-auth-type": "OAuth2Session",
            "x-twitter-client-language": "en",
            "content-type": "application/json",
            "user-agent": user_agent,
            "accept": "*/*",
            "accept-language": "en-US,en;q=0.9",
            "referer": "https://x.com/",
            "origin": "https://x.com",
        }

    def _build_cookies(self, account: AccountState) -> Dict[str, str]:
        return {"auth_token": account.auth_token, "ct0": account.ct0}

    def _make_request(self, url: str, params: Dict[str, str], account: AccountState) -> Dict[str, Any]:
        started_at = time.monotonic()
        profile = self._pick_profile()
        headers = self._build_headers(account, profile["user_agent"])
        cookies = self._build_cookies(account)

        if self._use_curl_cffi:
            try:
                response = self._curl_requests.get(  # type: ignore[attr-defined]
                    url,
                    params=params,
                    headers=headers,
                    cookies=cookies,
                    impersonate=profile["impersonate"],
                    timeout=self.timeout,
                )
            except TimeoutError as exc:
                raise RequestTimeoutError(f"Request timed out after {self.timeout}s") from exc
            except Exception as exc:  # pragma: no cover - depends on optional curl_cffi internals
                lowered = str(exc).lower()
                if "timed out" in lowered or "timeout" in lowered:
                    raise RequestTimeoutError(f"Request timed out after {self.timeout}s") from exc
                raise NetworkError(f"Network error: {exc}") from exc
            status = response.status_code
            body_text = response.text
            response_headers = response.headers
            if status == 200:
                payload = response.json()
            else:
                payload = None
        else:
            query = urlencode(params)
            cookie_header = "; ".join(f"{k}={v}" for k, v in cookies.items())
            request = Request(f"{url}?{query}", headers={**headers, "cookie": cookie_header}, method="GET")
            try:
                with urlopen(request, timeout=self.timeout) as response:
                    status = response.getcode()
                    body_text = response.read().decode("utf-8", errors="replace")
                    response_headers = response.headers
            except HTTPError as exc:
                status = exc.code
                body_text = exc.read().decode("utf-8", errors="replace")
                response_headers = exc.headers
            except TimeoutError as exc:
                raise RequestTimeoutError(f"Request timed out after {self.timeout}s") from exc
            except socket.timeout as exc:
                raise RequestTimeoutError(f"Request timed out after {self.timeout}s") from exc
            except URLError as exc:
                reason = getattr(exc, "reason", exc)
                lowered = str(reason).lower()
                if "timed out" in lowered or "timeout" in lowered:
                    raise RequestTimeoutError(f"Request timed out after {self.timeout}s") from exc
                raise NetworkError(f"Network error: {exc}") from exc

            payload = json.loads(body_text) if status == 200 else None

        elapsed = time.monotonic() - started_at
        logger.info(
            "Request finished: endpoint=%s status=%s elapsed=%.1fs account=%s",
            url.rsplit("/", 1)[-1],
            status,
            elapsed,
            account.index,
        )

        if status == 200:
            errors = payload.get("errors") or []
            if errors and not payload.get("data"):
                first = errors[0] if isinstance(errors[0], dict) else {}
                error_code = first.get("code")
                error_msg = first.get("message", "")
                lowered = str(error_msg).lower()
                if error_code == 88 or "rate limit" in lowered:
                    raise RateLimitError(900)
                if error_code in {32, 64, 89} or any(k in lowered for k in ("unauthorized", "forbidden", "auth")):
                    raise AuthError(error_msg or "Authentication failed")
                if "not found" in lowered or "validation" in lowered or "query" in lowered:
                    raise ApiError(f"Twitter API might have updated, causing Query ID to expire. Please update QUERY_IDS in the script. Error details: {error_msg}")
                raise ApiError(error_msg or "GraphQL request failed")
            return payload

        if status == 429:
            retry_after = response_headers.get("retry-after", "900")
            try:
                parsed_retry = int(str(retry_after))
            except ValueError:
                parsed_retry = 900
            raise RateLimitError(parsed_retry)
        if status in {401, 403}:
            raise AuthError(f"HTTP {status}")
        if status == 400:
            raise ApiError(f"HTTP 400 (Bad Request): Request parameters or GraphQL Query ID might have expired. Please update QUERY_IDS. Response snippet: {body_text[:100]}")
        raise ApiError(f"HTTP {status}: {body_text[:200]}")

    def _request_with_retry(self, url: str, params: Dict[str, str]) -> Optional[Dict[str, Any]]:
        endpoint = url.rsplit("/", 1)[-1]
        retry_budget = max(0, self.max_retries)
        max_attempts = retry_budget + 1
        last_retryable_error: Optional[XClientError] = None
        account = self.account_pool.get_next()
        if not account:
            logger.error("No available scraping accounts. All configured accounts are rate-limited or unavailable.")
            raise XClientError("All scraping accounts are rate-limited or unavailable. Scraping is aborted.")

        for attempt in range(1, max_attempts + 1):
            logger.info(
                "Starting request: endpoint=%s account=%s timeout=%ss attempt=%s/%s",
                endpoint,
                account.index,
                self.timeout,
                attempt,
                max_attempts,
            )
            try:
                return self._make_request(url, params, account)
            except RateLimitError as exc:
                self.account_pool.mark_rate_limited(account, exc.retry_after)
                logger.warning(
                    "Fail-fast exit: error_type=rate_limit account=%s retry_after=%ss",
                    account.index,
                    exc.retry_after,
                )
                raise
            except AuthError as exc:
                self.account_pool.mark_dead(account)
                logger.warning("Fail-fast exit: error_type=auth_error account=%s detail=%s", account.index, exc)
                raise
            except ApiError as exc:
                logger.warning("Fail-fast exit: error_type=api_error account=%s detail=%s", account.index, exc)
                raise
            except RequestTimeoutError as exc:
                last_retryable_error = exc
                if attempt >= max_attempts:
                    logger.warning("Fail-fast exit: error_type=timeout account=%s detail=%s", account.index, exc)
                    raise
                logger.warning(
                    "Retrying request after timeout: endpoint=%s account=%s attempt=%s/%s sleep=%.1fs detail=%s",
                    endpoint,
                    account.index,
                    attempt,
                    max_attempts,
                    RETRYABLE_BACKOFF_SECONDS,
                    exc,
                )
                time.sleep(RETRYABLE_BACKOFF_SECONDS)
            except NetworkError as exc:
                last_retryable_error = exc
                if attempt >= max_attempts:
                    logger.warning("Fail-fast exit: error_type=network_error account=%s detail=%s", account.index, exc)
                    raise
                logger.warning(
                    "Retrying request after network error: endpoint=%s account=%s attempt=%s/%s sleep=%.1fs detail=%s",
                    endpoint,
                    account.index,
                    attempt,
                    max_attempts,
                    RETRYABLE_BACKOFF_SECONDS,
                    exc,
                )
                time.sleep(RETRYABLE_BACKOFF_SECONDS)
            except XClientError as exc:
                logger.warning("Fail-fast exit: error_type=client_error account=%s detail=%s", account.index, exc)
                raise

        if last_retryable_error:
            raise last_retryable_error
        raise XClientError("Request failed before a response was received.")

    def get_user_id(self, username: str) -> Optional[str]:
        if username in self._user_id_cache:
            return self._user_id_cache[username]

        url = f"{self.graphql_base}/{QUERY_IDS['UserByScreenName']}/UserByScreenName"
        params = {
            "variables": json.dumps(
                {"screen_name": username, "withSafetyModeUserFields": True},
                separators=(",", ":"),
            ),
            "features": json.dumps(DEFAULT_FEATURES, separators=(",", ":")),
            "fieldToggles": json.dumps(DEFAULT_FIELD_TOGGLES, separators=(",", ":")),
        }
        response = self._request_with_retry(url, params)
        if not response:
            return None
        user_id = self.parser.parse_user_id(response)
        if user_id:
            self._user_id_cache[username] = user_id
        return user_id

    def get_user_tweets(
        self,
        user_id: str,
        count: int,
        cursor: Optional[str],
        include_replies: bool,
    ) -> Tuple[List[TweetRecord], Optional[str]]:
        url = f"{self.graphql_base}/{QUERY_IDS['UserTweets']}/UserTweets"
        variables: Dict[str, Any] = {
            "userId": user_id,
            "count": min(count, 100),
            "includePromotedContent": False,
            "withQuickPromoteEligibilityTweetFields": True,
            "withVoice": True,
            "withV2Timeline": True,
        }
        if cursor:
            variables["cursor"] = cursor

        params = {
            "variables": json.dumps(variables, separators=(",", ":")),
            "features": json.dumps(DEFAULT_FEATURES, separators=(",", ":")),
            "fieldToggles": json.dumps(DEFAULT_FIELD_TOGGLES, separators=(",", ":")),
        }
        response = self._request_with_retry(url, params)
        if not response:
            return [], None
        tweets, next_cursor = self.parser.parse_timeline(response)
        if not include_replies:
            tweets = [
                tweet
                for tweet in tweets
                if tweet.in_reply_to_id is None or tweet.in_reply_to_username == tweet.username
            ]
        return tweets, next_cursor

    def get_user_tweets_all(
        self,
        user_id: str,
        max_fetch: int,
        since_date: Optional[str],
        include_replies: bool,
        retweet_mode: str,
        page_delay: Tuple[float, float],
    ) -> FetchRunResult:
        all_tweets: List[TweetRecord] = []
        seen_ids = set()
        seen_cursors = set()
        cursor = None
        cutoff = None
        pages_fetched = 0
        partial_failure_reason = None
        consecutive_no_progress_pages = 0

        if since_date:
            cutoff = datetime.strptime(since_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)

        while len(all_tweets) < max_fetch:
            page_number = pages_fetched + 1
            page_size = min(20, max_fetch - len(all_tweets))
            logger.info(
                "Fetching page: page=%s collected=%s max_fetch=%s page_size=%s cursor_present=%s",
                page_number,
                len(all_tweets),
                max_fetch,
                page_size,
                bool(cursor),
            )
            try:
                tweets, next_cursor = self.get_user_tweets(
                    user_id=user_id,
                    count=page_size,
                    cursor=cursor,
                    include_replies=include_replies,
                )
                pages_fetched += 1
            except XClientError as exc:
                logger.warning(
                    "Fetch aborted: page=%s collected=%s error=%s",
                    page_number,
                    len(all_tweets),
                    exc,
                )
                partial_failure_reason = str(exc)
                status = "partial_success" if all_tweets else "failed"
                return FetchRunResult(
                    tweets=all_tweets,
                    status=status,
                    pages_fetched=pages_fetched,
                    partial_failure_reason=partial_failure_reason,
                )

            if not tweets:
                logger.info(
                    "Stopping fetch: reason=empty_page page=%s collected=%s",
                    page_number,
                    len(all_tweets),
                )
                break

            logger.info(
                "Fetched page result: page=%s raw_tweets=%s next_cursor_present=%s",
                page_number,
                len(tweets),
                bool(next_cursor),
            )

            page_has_new_enough = False
            added_this_page = 0
            for tweet in tweets:
                in_range = True
                if cutoff and tweet.created_at and tweet.created_at < cutoff:
                    in_range = False
                if in_range:
                    page_has_new_enough = True
                if not in_range:
                    continue
                if retweet_mode == "exclude" and tweet.is_retweet:
                    continue
                if retweet_mode == "only" and not tweet.is_retweet:
                    continue
                if tweet.id in seen_ids:
                    continue
                seen_ids.add(tweet.id)
                all_tweets.append(tweet)
                added_this_page += 1
                if len(all_tweets) >= max_fetch:
                    break

            logger.info(
                "Page processed: page=%s kept=%s total_collected=%s",
                page_number,
                added_this_page,
                len(all_tweets),
            )
            if added_this_page == 0:
                consecutive_no_progress_pages += 1
                logger.info(
                    "No progress on page: page=%s consecutive_no_progress_pages=%s",
                    page_number,
                    consecutive_no_progress_pages,
                )
            else:
                consecutive_no_progress_pages = 0

            if cutoff and not page_has_new_enough:
                logger.info(
                    "Stopping fetch: reason=cutoff_reached page=%s collected=%s",
                    page_number,
                    len(all_tweets),
                )
                break
            if consecutive_no_progress_pages >= MAX_CONSECUTIVE_NO_PROGRESS_PAGES:
                logger.info(
                    "Stopping fetch: reason=no_progress page=%s collected=%s consecutive_no_progress_pages=%s",
                    page_number,
                    len(all_tweets),
                    consecutive_no_progress_pages,
                )
                break
            if not next_cursor or next_cursor == cursor or next_cursor in seen_cursors:
                stop_reason = "missing_cursor"
                if next_cursor == cursor:
                    stop_reason = "cursor_repeated"
                elif next_cursor in seen_cursors:
                    stop_reason = "cursor_seen"
                logger.info(
                    "Stopping fetch: reason=%s page=%s collected=%s",
                    stop_reason,
                    page_number,
                    len(all_tweets),
                )
                break
            seen_cursors.add(next_cursor)
            cursor = next_cursor
            sleep_seconds = random.uniform(*page_delay)
            logger.info(
                "Sleeping before next page: page=%s sleep=%.1fs",
                page_number,
                sleep_seconds,
            )
            time.sleep(sleep_seconds)

        logger.info("Fetch completed: status=success pages=%s collected=%s", pages_fetched, len(all_tweets))
        return FetchRunResult(
            tweets=all_tweets,
            status="success",
            pages_fetched=pages_fetched,
        )

def normalize_username(target: str) -> str:
    value = target.strip()
    if not value:
        raise ValueError("Target cannot be empty.")

    if value.startswith("http://") or value.startswith("https://"):
        match = re.search(r"(?:x|twitter)\.com/([^/?#]+)", value, flags=re.IGNORECASE)
        if not match:
            raise ValueError("Could not parse username from X profile URL.")
        value = match.group(1)

    return value.lstrip("@").strip()


def load_alias_map(alias_file: Path) -> Dict[str, str]:
    try:
        with alias_file.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError as exc:
        raise ValueError(f"Alias file not found: {alias_file}") from exc
    except JSONDecodeError as exc:
        raise ValueError(f"Alias file is not valid JSON: {alias_file}") from exc

    if not isinstance(data, dict):
        raise ValueError(f"Alias file must contain a JSON object: {alias_file}")
    return data


def resolve_target(target: str, alias_map: Dict[str, str]) -> Tuple[str, Optional[str]]:
    normalized = normalize_username(target)
    alias_lookup = {key.lower(): (key, value) for key, value in alias_map.items()}
    if normalized.lower() in alias_lookup:
        alias, username = alias_lookup[normalized.lower()]
        return username, alias

    return normalized, None


def parse_optional_date(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def compute_since_date(args: argparse.Namespace) -> Optional[str]:
    if args.since_date:
        return args.since_date
    if args.days_lookback is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=args.days_lookback)
        return cutoff.strftime("%Y-%m-%d")
    return None


def compute_mode(args: argparse.Namespace) -> str:
    if args.since_date or args.until_date or args.days_lookback is not None:
        return "time_range"
    return "count"


def compute_limit(args: argparse.Namespace, mode: str) -> Optional[int]:
    if args.limit is not None:
        return args.limit
    if mode == "count":
        return 20
    return None


def compute_max_fetch(args: argparse.Namespace, mode: str) -> Optional[int]:
    if mode == "time_range":
        return args.max_fetch
    return compute_limit(args, mode)


def validate_args(args: argparse.Namespace) -> None:
    if args.days_lookback is not None and args.since_date:
        raise SystemExit("Use either --days-lookback or --since-date, not both.")
    if args.limit is not None and args.limit <= 0:
        raise SystemExit("--limit must be > 0.")
    if args.max_fetch <= 0:
        raise SystemExit("--max-fetch must be > 0.")
    if args.days_lookback is not None and args.days_lookback < 0:
        raise SystemExit("--days-lookback must be >= 0.")
    if args.page_delay_min < 0 or args.page_delay_max < 0:
        raise SystemExit("--page-delay-min and --page-delay-max must be >= 0.")
    if args.page_delay_min > args.page_delay_max:
        raise SystemExit("--page-delay-min must be <= --page-delay-max.")

    since_dt = parse_optional_date(args.since_date)
    until_dt = parse_optional_date(args.until_date)
    if since_dt and until_dt and since_dt > until_dt:
        raise SystemExit("--since-date must be on or before --until-date.")


def filter_by_date(
    tweets: List[TweetRecord],
    since_date: Optional[str],
    until_date: Optional[str],
) -> List[TweetRecord]:
    since_dt = parse_optional_date(since_date)
    until_dt = parse_optional_date(until_date)
    if until_dt:
        until_dt = until_dt.replace(hour=23, minute=59, second=59)

    filtered: List[TweetRecord] = []
    for tweet in tweets:
        if not tweet.created_at:
            continue
        if since_dt and tweet.created_at < since_dt:
            continue
        if until_dt and tweet.created_at > until_dt:
            continue
        filtered.append(tweet)
    return filtered

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch X tweets for one target and output raw tweet content.",
        epilog=(
            "Defaults: count mode returns up to 20 tweets when no time range is given; "
            "time-range mode uses --max-fetch 500 unless overridden. "
            "Only pass non-default switches when they are required by the request."
        ),
    )
    parser.add_argument(
        "target",
        help="Required. One target only: exact username, @username, profile URL, or configured alias.",
    )
    parser.add_argument(
        "--alias-file",
        default=str(Path(__file__).resolve().parents[1] / "defaults" / "x_accounts.json"),
        help="Alias mapping JSON. Default: defaults/x_accounts.json.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help=(
            "Maximum number of final tweets to return. "
            "Default: 20 in count mode; no final limit in time-range mode unless explicitly set."
        ),
    )
    parser.add_argument(
        "--max-fetch",
        type=int,
        default=500,
        help="Maximum number of tweets to scan internally in time-range mode only. Default: 500.",
    )
    parser.add_argument("--days-lookback", type=int, help="Relative lookback window in days. Optional.")
    parser.add_argument("--since-date", help="Absolute range start in YYYY-MM-DD. Optional.")
    parser.add_argument("--until-date", help="Absolute range end in YYYY-MM-DD. Optional.")
    parser.add_argument(
        "--output-dir",
        default=".",
        help='Base output directory. Default: current directory ".".',
    )
    parser.add_argument(
        "--retweet-mode",
        choices=["exclude", "include", "only"],
        default="include",
        help="How to handle retweets. Default: include.",
    )
    parser.add_argument(
        "--include-replies",
        action="store_true",
        help="Include replies. Default: off.",
    )
    parser.add_argument(
        "--request-timeout",
        type=int,
        default=30,
        help="HTTP request timeout in seconds. Default: 30.",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=1,
        help="Extra retry attempts for timeout or network errors. Default: 1.",
    )
    parser.add_argument(
        "--page-delay-min",
        type=float,
        default=6.0,
        help="Minimum delay in seconds between pages for one target. Default: 6.",
    )
    parser.add_argument(
        "--page-delay-max",
        type=float,
        default=10.0,
        help="Maximum delay in seconds between pages for one target. Default: 10.",
    )
    return parser.parse_args()


def scrape_target_to_files(
    *,
    args: argparse.Namespace,
    client: XClient,
    alias_map: Dict[str, str],
    output_dir: Path,
    env_file_used: bool,
    path_builder=build_output_paths,
) -> ScrapeArtifacts:
    resolved_username, resolved_alias = resolve_target(args.target, alias_map)
    mode = compute_mode(args)
    limit = compute_limit(args, mode)
    max_fetch = compute_max_fetch(args, mode)
    since_date = compute_since_date(args)

    logger.info("Resolving @%s", resolved_username)
    try:
        user_id = client.get_user_id(resolved_username)
    except XClientError as exc:
        run_result = FetchRunResult(
            tweets=[],
            status="failed",
            pages_fetched=0,
            partial_failure_reason=f"Fatal error occurred while resolving account @{resolved_username}: {exc}",
        )
        exports: List[Dict[str, Any]] = []
        json_path, md_path = path_builder(output_dir, resolved_username)
        json_path.parent.mkdir(parents=True, exist_ok=True)
        run_metadata = build_run_metadata(
            args=args,
            resolved_username=resolved_username,
            resolved_alias=resolved_alias,
            mode=mode,
            limit=limit,
            max_fetch=max_fetch,
            since_date=since_date,
            run_result=run_result,
            exports=exports,
            env_file_used=env_file_used,
        )
        with json_path.open("w", encoding="utf-8") as handle:
            json.dump(run_metadata, handle, ensure_ascii=False, indent=2)
        markdown = render_markdown(
            items=exports,
            query_target=args.target,
            resolved_username=resolved_username,
            resolved_alias=resolved_alias,
            mode=mode,
            limit=limit,
            max_fetch=max_fetch,
            since_date=since_date,
            until_date=args.until_date,
            run_status=run_result.status,
            pages_fetched=run_result.pages_fetched,
            partial_failure_reason=run_result.partial_failure_reason,
        )
        with md_path.open("w", encoding="utf-8") as handle:
            handle.write(markdown)
        return ScrapeArtifacts(
            resolved_username=resolved_username,
            resolved_alias=resolved_alias,
            mode=mode,
            limit=limit,
            max_fetch=max_fetch,
            since_date=since_date,
            run_result=run_result,
            exports=exports,
            json_path=json_path,
            md_path=md_path,
        )

    if not user_id:
        raise SystemExit(f"Could not resolve user id for @{resolved_username}.")

    logger.info(
        "Fetching tweets for @%s mode=%s limit=%s max_fetch=%s",
        resolved_username,
        mode,
        limit,
        max_fetch,
    )
    run_result = client.get_user_tweets_all(
        user_id=user_id,
        max_fetch=max_fetch,
        since_date=since_date,
        include_replies=args.include_replies,
        retweet_mode=args.retweet_mode,
        page_delay=(args.page_delay_min, args.page_delay_max),
    )

    tweets = run_result.tweets
    tweets = filter_by_date(tweets, since_date=since_date, until_date=args.until_date)
    tweets.sort(key=lambda item: item.created_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    if limit is not None:
        tweets = tweets[:limit]

    exports = [tweet.to_export_dict() for tweet in tweets]
    json_path, md_path = path_builder(output_dir, resolved_username)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    run_metadata = build_run_metadata(
        args=args,
        resolved_username=resolved_username,
        resolved_alias=resolved_alias,
        mode=mode,
        limit=limit,
        max_fetch=max_fetch,
        since_date=since_date,
        run_result=run_result,
        exports=exports,
        env_file_used=env_file_used,
    )
    with json_path.open("w", encoding="utf-8") as handle:
        json.dump(run_metadata, handle, ensure_ascii=False, indent=2)

    markdown = render_markdown(
        items=exports,
        query_target=args.target,
        resolved_username=resolved_username,
        resolved_alias=resolved_alias,
        mode=mode,
        limit=limit,
        max_fetch=max_fetch,
        since_date=since_date,
        until_date=args.until_date,
        run_status=run_result.status,
        pages_fetched=run_result.pages_fetched,
        partial_failure_reason=run_result.partial_failure_reason,
    )
    with md_path.open("w", encoding="utf-8") as handle:
        handle.write(markdown)

    return ScrapeArtifacts(
        resolved_username=resolved_username,
        resolved_alias=resolved_alias,
        mode=mode,
        limit=limit,
        max_fetch=max_fetch,
        since_date=since_date,
        run_result=run_result,
        exports=exports,
        json_path=json_path,
        md_path=md_path,
    )

def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = parse_args()
    validate_args(args)

    alias_map = load_alias_map(Path(args.alias_file))
    output_dir = Path(args.output_dir)
    env_file_used = bool(load_default_env(Path(__file__).resolve().parents[1] / "defaults" / "x.env"))

    account_pool = AccountPool.from_env()
    logger.info(
        "Loaded scraping accounts: count=%s order=%s",
        len(account_pool.accounts),
        [account.index for account in account_pool.accounts],
    )
    client = XClient(
        account_pool=account_pool,
        timeout=args.request_timeout,
        max_retries=args.max_retries,
    )
    artifacts = scrape_target_to_files(
        args=args,
        client=client,
        alias_map=alias_map,
        output_dir=output_dir,
        env_file_used=env_file_used,
    )

    print(f"Resolved username: @{artifacts.resolved_username}")
    if artifacts.resolved_alias:
        print(f"Resolved alias: {artifacts.resolved_alias}")
    print(f"Run status: {artifacts.run_result.status}")
    if artifacts.run_result.partial_failure_reason:
        print(f"Partial failure reason: {artifacts.run_result.partial_failure_reason}")
    print(f"Saved JSON: {artifacts.json_path}")
    print(f"Saved Markdown: {artifacts.md_path}")
    print(f"Tweets saved: {len(artifacts.exports)}")
    return 0 if artifacts.run_result.status != "failed" else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
