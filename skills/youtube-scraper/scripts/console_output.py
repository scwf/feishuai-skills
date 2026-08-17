"""Safe console JSON for Windows consoles that cannot encode source text."""

from __future__ import annotations

import json
import os
import sys
from typing import Any


def silence_stdout() -> None:
    """Redirect stdout to the null device so interpreter shutdown cannot fail."""
    try:
        stdout_fd = sys.stdout.fileno()
        null_fd = os.open(os.devnull, os.O_WRONLY)
        try:
            os.dup2(null_fd, stdout_fd)
        finally:
            os.close(null_fd)
        return
    except Exception:
        pass
    try:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    except Exception:
        return


def emit_stdout_json(payload: Any) -> None:
    """Write ASCII JSON to stdout. Never raise after a successful disk write."""
    text = json.dumps(payload, ensure_ascii=True)
    try:
        print(text, flush=True)
        return
    except UnicodeEncodeError:
        pass
    except (BrokenPipeError, OSError, ValueError):
        silence_stdout()
        return
    try:
        encoding = getattr(sys.stdout, "encoding", None) or "ascii"
        buffer = getattr(sys.stdout, "buffer", None)
        if buffer is not None:
            buffer.write((text + "\n").encode(encoding, errors="replace"))
            buffer.flush()
    except (BrokenPipeError, OSError, ValueError):
        silence_stdout()
        return
    except Exception:
        return
