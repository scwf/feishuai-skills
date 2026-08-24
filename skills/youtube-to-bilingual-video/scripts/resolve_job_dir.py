#!/usr/bin/env python3
"""Resolve and persist the deterministic default job directory for one video ID."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import time
import unicodedata
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO, Iterator

INVALID_COMPONENT_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')
RESERVED_WINDOWS_NAMES = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}
MAX_SAFE_TITLE_BYTES = 120
MANIFEST_NAME = ".bilingual-video-job.json"
MANIFEST_VERSION = 1
LOCK_WAIT_SECONDS = 2.0
LOCK_RETRY_SECONDS = 0.05


class JobResolverError(ValueError):
    def __init__(self, message: str, *, reason: str, retryable: bool = False) -> None:
        super().__init__(message)
        self.reason = reason
        self.retryable = retryable


def truncate_utf8(value: str, max_bytes: int) -> str:
    return value.encode("utf-8")[:max_bytes].decode("utf-8", errors="ignore").rstrip(". ")


def safe_title(title: str) -> str:
    normalized = unicodedata.normalize("NFKC", title or "").strip()
    cleaned = INVALID_COMPONENT_RE.sub("_", normalized)
    cleaned = re.sub(r"\s+", " ", cleaned).strip().rstrip(". ")
    if not cleaned or cleaned.casefold() in RESERVED_WINDOWS_NAMES:
        cleaned = "video"
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:8]
    prefix = truncate_utf8(cleaned, MAX_SAFE_TITLE_BYTES - len(digest) - 1) or "video"
    return f"{prefix}-{digest}"


def normalized_video_id(value: str) -> str:
    video_id = value.strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{6,64}", video_id):
        raise ValueError("video ID must contain 6-64 ASCII letters, digits, '_' or '-'")
    return video_id


def deterministic_directory_name(safe_name: str, video_id: str) -> str:
    id_digest = hashlib.sha256(video_id.encode("ascii")).hexdigest()[:8]
    return f"{safe_name}-{video_id}-{id_digest}"


def read_manifest(path: Path, *, directory_name: str) -> dict[str, object] | None:
    try:
        target_stat = path.lstat()
    except FileNotFoundError:
        return None
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    attributes = getattr(target_stat, "st_file_attributes", 0)
    if (
        path.is_symlink()
        or not stat.S_ISREG(target_stat.st_mode)
        or bool(reparse_flag and attributes & reparse_flag)
    ):
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, ValueError):
        return None
    if not isinstance(payload, dict) or set(payload) != {
        "schema_version",
        "video_id",
        "original_title",
        "safe_title",
        "directory_name",
    }:
        return None
    if (
        not isinstance(payload.get("schema_version"), int)
        or isinstance(payload.get("schema_version"), bool)
        or payload.get("schema_version") != MANIFEST_VERSION
    ):
        return None
    if not all(
        isinstance(payload.get(key), str)
        for key in ("video_id", "original_title", "safe_title", "directory_name")
    ):
        return None
    try:
        manifest_video_id = str(payload["video_id"])
        if normalized_video_id(manifest_video_id) != manifest_video_id:
            return None
    except ValueError:
        return None
    if payload["safe_title"] != safe_title(str(payload["original_title"])):
        return None
    if payload["directory_name"] != directory_name:
        return None
    if payload["directory_name"] != deterministic_directory_name(
        str(payload["safe_title"]), str(payload["video_id"])
    ):
        return None
    return payload


def is_safe_direct_child_directory(root: Path, candidate: Path) -> bool:
    try:
        target_stat = candidate.lstat()
    except FileNotFoundError:
        return False
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    attributes = getattr(target_stat, "st_file_attributes", 0)
    if (
        candidate.is_symlink()
        or not stat.S_ISDIR(target_stat.st_mode)
        or bool(reparse_flag and attributes & reparse_flag)
    ):
        return False
    resolved_root = root.resolve()
    resolved_candidate = candidate.resolve()
    return resolved_candidate.parent == resolved_root


def lock_handle(handle: BinaryIO) -> None:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def unlock_handle(handle: BinaryIO) -> None:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def job_lock(root: Path, video_id: str) -> Iterator[None]:
    digest = hashlib.sha256(video_id.encode("ascii")).hexdigest()[:16]
    lock_path = root / f".bilingual-job-{digest}.lock"
    created = False
    flags = os.O_RDWR | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    try:
        descriptor = os.open(lock_path, flags, 0o600)
        created = True
    except FileExistsError:
        before = lock_path.lstat()
        reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        attributes = getattr(before, "st_file_attributes", 0)
        if (
            lock_path.is_symlink()
            or not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or bool(reparse_flag and attributes & reparse_flag)
        ):
            raise JobResolverError(
                "job lock path is not a safe single-link regular file",
                reason="unsafe_lock_path",
            )
        open_flags = os.O_RDWR
        if hasattr(os, "O_BINARY"):
            open_flags |= os.O_BINARY
        if hasattr(os, "O_NOFOLLOW"):
            open_flags |= os.O_NOFOLLOW
        descriptor = os.open(lock_path, open_flags)
        after = os.fstat(descriptor)
        current = lock_path.lstat()
        if (
            not stat.S_ISREG(after.st_mode)
            or after.st_nlink != 1
            or (after.st_dev, after.st_ino) != (current.st_dev, current.st_ino)
        ):
            os.close(descriptor)
            raise JobResolverError(
                "job lock path changed or is not a safe single-link regular file",
                reason="unsafe_lock_path",
            )
    handle = os.fdopen(descriptor, "r+b", buffering=0)
    try:
        if created:
            handle.write(b"0")
            handle.flush()
            os.fsync(handle.fileno())
        elif os.fstat(handle.fileno()).st_size < 1:
            handle.write(b"0")
            handle.flush()
            os.fsync(handle.fileno())
        deadline = time.monotonic() + LOCK_WAIT_SECONDS
        while True:
            try:
                lock_handle(handle)
                break
            except OSError as exc:
                if time.monotonic() >= deadline:
                    raise JobResolverError(
                        "another resolver is still creating this video job directory",
                        reason="output_locked",
                        retryable=True,
                    ) from exc
                time.sleep(LOCK_RETRY_SECONDS)
        try:
            yield
        finally:
            try:
                unlock_handle(handle)
            except OSError:
                pass
    finally:
        try:
            handle.close()
        except OSError:
            pass


def write_manifest(path: Path, payload: dict[str, object]) -> None:
    temporary = path.parent.parent / f".job-manifest-{uuid.uuid4().hex}.tmp"
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def resolve_job_dir(root: Path, title: str, video_id: str) -> tuple[Path, bool]:
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    with job_lock(root, video_id):
        matches: list[Path] = []
        for candidate in sorted(root.iterdir(), key=lambda path: path.name.casefold()):
            if not is_safe_direct_child_directory(root, candidate):
                continue
            manifest = read_manifest(
                candidate / MANIFEST_NAME,
                directory_name=candidate.name,
            )
            if manifest and manifest.get("video_id") == video_id:
                matches.append(candidate.resolve())
        if len(matches) > 1:
            raise JobResolverError(
                "multiple valid job directories claim the same video ID: "
                + ", ".join(str(path) for path in matches),
                reason="duplicate_video_job",
            )
        if matches:
            return matches[0], True

        safe_name = safe_title(title)
        candidate = root / deterministic_directory_name(safe_name, video_id)
        if candidate.exists() or candidate.is_symlink():
            if not is_safe_direct_child_directory(root, candidate):
                raise ValueError("default job path exists but is not a safe direct directory")
            manifest = read_manifest(
                candidate / MANIFEST_NAME,
                directory_name=candidate.name,
            )
            if manifest and manifest.get("video_id") == video_id:
                return candidate.resolve(), True
            if any(candidate.iterdir()):
                raise ValueError(
                    "default job directory already exists without a valid matching manifest"
                )
        else:
            candidate.mkdir(parents=False, exist_ok=False)
        write_manifest(
            candidate / MANIFEST_NAME,
            {
                "schema_version": MANIFEST_VERSION,
                "video_id": video_id,
                "original_title": title,
                "safe_title": safe_name,
                "directory_name": candidate.name,
            },
        )
        return candidate.resolve(), False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--title", required=True)
    parser.add_argument("--video-id", required=True)
    args = parser.parse_args()
    try:
        video_id = normalized_video_id(args.video_id)
        job_dir, reused = resolve_job_dir(args.root.resolve(), args.title, video_id)
        print(
            json.dumps(
                {"status": "ok", "job_dir": str(job_dir), "reused": reused},
                ensure_ascii=True,
            )
        )
        return 0
    except (OSError, UnicodeError, ValueError) as exc:
        reason = (
            exc.reason
            if isinstance(exc, JobResolverError)
            else "job_dir_resolution_failure"
        )
        print(
            json.dumps(
                {
                    "status": "error",
                    "reason": reason,
                    "retryable": bool(
                        isinstance(exc, JobResolverError) and exc.retryable
                    ),
                    "message": str(exc),
                },
                ensure_ascii=True,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
