"""Default paths for X-daily helper scripts (overridable via env or CLI)."""

from __future__ import annotations

import os
from pathlib import Path


def x_daily_home() -> Path:
    return Path(os.environ.get("X_DAILY_HOME", "~/data/x-daily")).expanduser().resolve()


def reports_dir() -> Path:
    override = os.environ.get("X_DAILY_REPORTS_DIR")
    if override:
        return Path(override).expanduser().resolve()
    return x_daily_home() / "reports"


def credentials_path() -> Path:
    override = os.environ.get("X_DAILY_CREDENTIALS")
    if override:
        return Path(override).expanduser().resolve()
    return x_daily_home() / "email-conf" / "credentials.env"


def recipients_path() -> Path:
    override = os.environ.get("X_DAILY_RECIPIENTS")
    if override:
        return Path(override).expanduser().resolve()
    return x_daily_home() / "email-conf" / "recipients.txt"
