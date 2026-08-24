from __future__ import annotations

import os
from pathlib import Path


def file_identity(path: Path) -> str:
    """Return a stable identity for collision checks, including Windows aliases."""
    raw = str(path.resolve())
    if os.name != "nt":
        return os.path.normcase(os.path.normpath(raw))

    raw = raw.replace("/", "\\")
    if raw.startswith("\\\\?\\UNC\\"):
        raw = "\\\\" + raw[8:]
    elif raw.startswith("\\\\?\\"):
        raw = raw[4:]
    drive, tail = os.path.splitdrive(raw)
    components = tail.split("\\")
    normalized_components = [
        part.rstrip(" .") if part not in {"", ".", ".."} else part
        for part in components
    ]
    normalized = drive + "\\".join(normalized_components)
    return os.path.normcase(os.path.normpath(normalized))
