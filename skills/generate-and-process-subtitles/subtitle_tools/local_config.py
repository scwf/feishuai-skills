from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable


SKILL_ROOT = Path(__file__).resolve().parents[1]
LLM_CONFIG_PATH = SKILL_ROOT / "llm.env"
ALLOWED_LLM_KEYS = {
    "SUBTITLE_LLM_API_KEY",
    "SUBTITLE_LLM_BASE_URL",
    "SUBTITLE_LLM_MODEL",
}


def load_local_llm_config(path: Path = LLM_CONFIG_PATH) -> None:
    """Load skill-local LLM config without overriding the host environment."""
    if not path.exists():
        return

    for key, value in _read_env_lines(path.read_text(encoding="utf-8-sig").splitlines()):
        if key in ALLOWED_LLM_KEYS and not os.environ.get(key, "").strip():
            os.environ[key] = value


def _read_env_lines(lines: Iterable[str]) -> Iterable[tuple[str, str]]:
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().lstrip("\ufeff")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        yield key, value
