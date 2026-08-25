"""Shared OpenAI-compatible LLM runtime settings for CLI commands."""

from __future__ import annotations

import argparse
import os

from .config import DEFAULT_LLM_BASE_URL
from .local_config import LLM_CONFIG_PATH
from .publishing import SubtitleSkillError

DEFAULT_LLM_MODEL = "deepseek-v4-flash"


def require_llm_api_key(args: argparse.Namespace, action: str) -> str:
    api_key = getattr(args, "api_key", None) or os.getenv(
        "SUBTITLE_LLM_API_KEY", ""
    ).strip()
    if not api_key:
        raise SubtitleSkillError(
            "Missing LLM API key.",
            action=action,
            step="validate_runtime",
            error_type="missing_api_key",
            suggested_fix=(
                f"Set SUBTITLE_LLM_API_KEY, pass --api-key, or create "
                f"{LLM_CONFIG_PATH.name}."
            ),
        )
    return api_key


def llm_base_url(args: argparse.Namespace) -> str:
    return (
        getattr(args, "base_url", None)
        or os.getenv("SUBTITLE_LLM_BASE_URL", "").strip()
        or DEFAULT_LLM_BASE_URL
    )


def llm_model(args: argparse.Namespace) -> str:
    return (
        getattr(args, "model", None)
        or os.getenv("SUBTITLE_LLM_MODEL", "").strip()
        or DEFAULT_LLM_MODEL
    )
