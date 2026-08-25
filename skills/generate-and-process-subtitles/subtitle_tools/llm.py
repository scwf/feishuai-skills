"""OpenAI-compatible LLM client for subtitle processing."""

import os
from typing import Any, List, Optional
from urllib.parse import urlparse, urlunparse

from openai import OpenAI
from .local_config import load_local_llm_config
from .utils import setup_logger


logger = setup_logger("llm_client")


def normalize_base_url(base_url: str) -> str:
    url = base_url.strip()
    parsed = urlparse(url)
    path = parsed.path.rstrip("/")

    if not path:
        path = "/v1"

    normalized = urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            path,
            parsed.params,
            parsed.query,
            parsed.fragment,
        )
    )

    return normalized


_client = None


def get_llm_client(api_key: Optional[str] = None, base_url: Optional[str] = None) -> OpenAI:
    global _client

    load_local_llm_config()
    if api_key or base_url or _client is None:
        final_api_key = api_key or os.getenv("SUBTITLE_LLM_API_KEY", "").strip()
        final_base_url = base_url or os.getenv("SUBTITLE_LLM_BASE_URL", "").strip()

        if final_base_url:
            final_base_url = normalize_base_url(final_base_url)

        if not final_api_key:
            logger.warning("SUBTITLE_LLM_API_KEY is not set.")

        _client = OpenAI(
            base_url=final_base_url if final_base_url else None,
            api_key=final_api_key,
        )

    return _client


def call_llm(
    messages: List[dict],
    model: str,
    temperature: float = 0.2,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    timeout_seconds: Optional[float] = None,
    **kwargs: Any,
) -> Any:
    client = get_llm_client(api_key, base_url)

    try:
        request_client = client
        if timeout_seconds is not None:
            request_client = client.with_options(
                timeout=timeout_seconds,
                max_retries=0,
            )
        response = request_client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            **kwargs,
        )
        return response
    except Exception as e:
        logger.error(f"LLM call failed: {e}")
        raise
