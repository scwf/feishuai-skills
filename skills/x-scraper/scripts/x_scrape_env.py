from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Dict, List, Tuple


logger = logging.getLogger("x_scraper")

ENV_KEYS: Tuple[str, ...] = ("X_AUTH_CREDENTIALS", "TWITTER_AUTH_TOKEN", "TWITTER_CT0", "XCSRF_TOKEN")


def parse_env_file(env_file: Path) -> Dict[str, str]:
    values: Dict[str, str] = {}
    if not env_file.exists():
        return values

    for line_number, raw_line in enumerate(env_file.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        if not sep:
            logger.warning("Ignoring malformed env line %s in %s", line_number, env_file)
            continue
        parsed_value = value.strip()
        if len(parsed_value) >= 2 and parsed_value[0] == parsed_value[-1] and parsed_value[0] in {"'", '"'}:
            parsed_value = parsed_value[1:-1]
        values[key.strip()] = parsed_value

    return values


def build_multi_account_credentials(values: Dict[str, str]) -> str:
    indexed_accounts: List[Tuple[int, str, str]] = []
    token_pattern = re.compile(r"^TWITTER_AUTH_TOKEN_(\d+)$")

    for key, token in values.items():
        match = token_pattern.match(key)
        if not match:
            continue
        index = int(match.group(1))
        ct0 = values.get(f"TWITTER_CT0_{index}", "").strip() or values.get(f"XCSRF_TOKEN_{index}", "").strip()
        token = token.strip()
        if not token or not ct0:
            continue
        indexed_accounts.append((index, token, ct0))

    if not indexed_accounts:
        return ""

    indexed_accounts.sort(key=lambda item: item[0])
    return "|".join(f"{token}:{ct0}" for _, token, ct0 in indexed_accounts)


def load_default_env(default_env_file: Path) -> Dict[str, str]:
    loaded_values: Dict[str, str] = {}
    if not default_env_file.exists():
        return loaded_values

    file_values = parse_env_file(default_env_file)
    if not file_values.get("X_AUTH_CREDENTIALS", "").strip():
        multi_account_value = build_multi_account_credentials(file_values)
        if multi_account_value:
            file_values["X_AUTH_CREDENTIALS"] = multi_account_value

    for key in ENV_KEYS:
        value = file_values.get(key, "").strip()
        if not value:
            continue
        os.environ[key] = value
        loaded_values[key] = value
    return loaded_values
