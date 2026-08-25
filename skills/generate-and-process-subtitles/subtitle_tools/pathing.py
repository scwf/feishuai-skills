from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import BinaryIO


class UnsafeLockPathError(OSError):
    """Raised when a predictable lock path is not a private regular file."""


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


def open_safe_lock_file(path: Path) -> BinaryIO:
    """Open a lock file without following links or accepting shared inodes."""
    flags = os.O_RDWR | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    created = False
    try:
        descriptor = os.open(path, flags, 0o600)
        created = True
    except FileExistsError:
        before = path.lstat()
        if not _is_safe_lock_stat(path, before):
            raise UnsafeLockPathError(f"unsafe lock path: {path}")
        open_flags = os.O_RDWR
        if hasattr(os, "O_BINARY"):
            open_flags |= os.O_BINARY
        if hasattr(os, "O_NOFOLLOW"):
            open_flags |= os.O_NOFOLLOW
        descriptor = os.open(path, open_flags)

    try:
        opened = os.fstat(descriptor)
        current = path.lstat()
        if (
            not _is_safe_lock_stat(path, current)
            or not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino)
        ):
            raise UnsafeLockPathError(f"lock path changed or is unsafe: {path}")
        handle = os.fdopen(descriptor, "r+b", buffering=0)
        descriptor = -1
        if created or opened.st_size < 1:
            handle.write(b"0")
            handle.flush()
            os.fsync(handle.fileno())
        return handle
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _is_safe_lock_stat(path: Path, target_stat: os.stat_result) -> bool:
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    attributes = getattr(target_stat, "st_file_attributes", 0)
    return (
        not path.is_symlink()
        and stat.S_ISREG(target_stat.st_mode)
        and target_stat.st_nlink == 1
        and not bool(reparse_flag and attributes & reparse_flag)
    )
