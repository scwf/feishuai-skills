#!/usr/bin/env python3
"""Cross-platform subtitle generation and processing CLI."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import stat
import sys
import time
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, BinaryIO, Dict, Iterator, Optional
from urllib.parse import parse_qs, urlparse


SKILL_ROOT = Path(__file__).resolve().parents[1]
WORK_DIR_NAME = "_subtitle_work"
QC_REPORT_SUFFIX = ".semantic-orphan-qc.json"
MAX_QC_STEM_UTF8_BYTES = 180
ATOMIC_REPLACE_RETRIES = 8
ATOMIC_REPLACE_DELAY_SECONDS = 0.01
DEFAULT_MODEL_NAME = "large-v2"
DEFAULT_LLM_MODEL = "deepseek-v4-flash"
DEFAULT_LLM_BASE_URL = "https://api.deepseek.com/v1"
MIN_ASR_LANGUAGE_PROBABILITY = 0.5

if str(SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILL_ROOT))

from subtitle_tools import ApprovalValidationError, ASRData, inspect_subtitle_path, optimize_subtitle, process_media, split_subtitle, translate_subtitle, validate_asr_timeline  # noqa: E402
from subtitle_tools.qc import DEFAULT_MAX_DISPLAY_CHARS_ENGLISH, DEFAULT_MAX_WORD_COUNT_ENGLISH, inspect_asr_data, normalize_seam_times, parse_srt_strict  # noqa: E402
from subtitle_tools.split import DEFAULT_MAX_WORD_COUNT_CJK, SubtitleSplitValidationError  # noqa: E402
from subtitle_tools.config import DEFAULT_LLM_BASE_URL as CONFIG_DEFAULT_LLM_BASE_URL  # noqa: E402
from subtitle_tools.local_config import LLM_CONFIG_PATH, load_local_llm_config  # noqa: E402
from subtitle_tools.pathing import file_identity  # noqa: E402


class SubtitleSkillError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        action: str,
        step: str,
        error_type: str,
        suggested_fix: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.action = action
        self.step = step
        self.error_type = error_type
        self.suggested_fix = suggested_fix
        self.details = details or {}


def sanitize_filename(value: str, fallback: str = "subtitles") -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", value).strip().rstrip(". ")
    return cleaned or fallback


def positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive integer") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def is_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def is_youtube_url(value: str) -> bool:
    host = (urlparse(value).netloc or "").lower()
    return "youtube.com" in host or "youtu.be" in host


def output_paths(output_dir: Path, base_name: str) -> Dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    safe_base = component_safe_base_name(base_name)
    return {
        "srt": output_dir / f"{safe_base}.srt",
        "txt": output_dir / f"{safe_base}.txt",
    }


def get_work_dir(output_dir: Path) -> Path:
    work_dir = output_dir / WORK_DIR_NAME
    work_dir.mkdir(parents=True, exist_ok=True)
    return work_dir


def truncate_utf8(value: str, max_bytes: int) -> str:
    encoded = value.encode("utf-8")
    if len(encoded) <= max_bytes:
        return value
    return encoded[:max_bytes].decode("utf-8", errors="ignore").rstrip(". ")


def work_artifact_filename(input_stem: str, suffix: str) -> str:
    safe_stem = sanitize_filename(input_stem)
    digest = hashlib.sha256(input_stem.encode("utf-8")).hexdigest()[:10]
    prefix_budget = MAX_QC_STEM_UTF8_BYTES - len(digest) - 1
    prefix = truncate_utf8(safe_stem, prefix_budget) or "subtitles"
    safe_stem = f"{prefix}-{digest}"
    return f"{safe_stem}{suffix}"


def component_safe_base_name(value: str) -> str:
    safe_value = sanitize_filename(value)
    if len(safe_value.encode("utf-8")) <= MAX_QC_STEM_UTF8_BYTES:
        return safe_value
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:10]
    prefix_budget = MAX_QC_STEM_UTF8_BYTES - len(digest) - 1
    prefix = truncate_utf8(safe_value, prefix_budget) or "subtitles"
    return f"{prefix}-{digest}"


def unlink_with_retries(path: Path, *, suppress_errors: bool = False) -> None:
    for attempt in range(ATOMIC_REPLACE_RETRIES):
        try:
            path.unlink(missing_ok=True)
            return
        except PermissionError:
            if attempt + 1 == ATOMIC_REPLACE_RETRIES:
                if suppress_errors:
                    return
                raise
            time.sleep(ATOMIC_REPLACE_DELAY_SECONDS * (2**attempt))
        except OSError:
            if suppress_errors:
                return
            raise


def qc_report_filename(input_stem: str) -> str:
    return work_artifact_filename(input_stem, QC_REPORT_SUFFIX)


def default_qc_output_path(input_path: Path) -> Path:
    parent = input_path.parent
    work_dir = (
        parent
        if any(part.casefold() == WORK_DIR_NAME.casefold() for part in parent.parts)
        else parent / WORK_DIR_NAME
    )
    return work_dir / qc_report_filename(input_path.stem)


def write_json_atomic(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".json-{uuid.uuid4().hex}.tmp"
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        for attempt in range(ATOMIC_REPLACE_RETRIES):
            try:
                temporary.replace(path)
                break
            except PermissionError:
                if attempt + 1 == ATOMIC_REPLACE_RETRIES:
                    raise
                time.sleep(ATOMIC_REPLACE_DELAY_SECONDS * (2**attempt))
    finally:
        temporary.unlink(missing_ok=True)


def copy_file_atomic(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.parent / f".copy-{uuid.uuid4().hex}.tmp"
    try:
        shutil.copy2(source, temporary)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def write_bytes_atomic(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".bytes-{uuid.uuid4().hex}.tmp"
    try:
        temporary.write_bytes(payload)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def rollback_artifacts_on_error(
    paths: list[Path], action: str
) -> Iterator[None]:
    snapshots: Dict[Path, Optional[bytes]] = {}
    for path in paths:
        if path in snapshots:
            continue
        snapshots[path] = path.read_bytes() if path.is_file() else None
    try:
        yield
    except Exception as original_error:
        rollback_errors: list[str] = []
        for path, previous_bytes in snapshots.items():
            try:
                if previous_bytes is None:
                    unlink_with_retries(path)
                else:
                    write_bytes_atomic(path, previous_bytes)
            except OSError as exc:
                rollback_errors.append(f"{path}: {exc}")
        if rollback_errors:
            raise SubtitleSkillError(
                "Subtitle work-artifact rollback was incomplete: "
                + "; ".join(rollback_errors),
                action=action,
                step="rollback_work_artifacts",
                error_type="rollback_failure",
                suggested_fix="Preserve the reported paths and reconcile them before retrying.",
                details={"rollback_errors": rollback_errors},
            ) from original_error
        raise


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def serialized_srt_sha256(
    asr_data: ASRData,
    subtitle_format: str = "bilingual-trans-first",
) -> str:
    return sha256_bytes(asr_data.to_srt(subtitle_format=subtitle_format).encode("utf-8"))


def is_regular_output_target(path: Path) -> bool:
    try:
        target_stat = path.lstat()
    except FileNotFoundError:
        return True
    if path.is_symlink() or not stat.S_ISREG(target_stat.st_mode):
        return False
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    attributes = getattr(target_stat, "st_file_attributes", 0)
    return not bool(reparse_flag and attributes & reparse_flag)


def validate_output_pair_preflight(
    paths: Dict[str, Path],
    *,
    action: str,
    replace_existing: bool,
    protected_paths: tuple[Path, ...] = (),
) -> None:
    output_identities = {key: file_identity(path) for key, path in paths.items()}
    protected_identities = {file_identity(path) for path in protected_paths}
    if len(set(output_identities.values())) != len(output_identities) or any(
        identity in protected_identities for identity in output_identities.values()
    ):
        raise SubtitleSkillError(
            "SRT/TXT outputs must differ from each other and every input.",
            action=action,
            step="validate_output",
            error_type="path_collision",
            suggested_fix="Choose a distinct output directory or base filename.",
        )
    invalid_targets = [str(path) for path in paths.values() if not is_regular_output_target(path)]
    if invalid_targets:
        raise SubtitleSkillError(
            "Output targets must be ordinary files, not directories, symlinks, or reparse points.",
            action=action,
            step="validate_output",
            error_type="invalid_output_target",
            suggested_fix="Choose new ordinary-file output paths and preserve the existing target separately.",
            details={"invalid_output_targets": invalid_targets},
        )
    existing = [path for path in paths.values() if path.exists()]
    if existing and not replace_existing:
        raise SubtitleSkillError(
            "Output SRT/TXT already exists; existing files were not changed.",
            action=action,
            step="validate_output",
            error_type="output_exists",
            suggested_fix="Use a new output base, or pass --replace-existing to archive and replace the pair.",
            details={"existing_outputs": [str(path) for path in existing]},
        )


def _lock_handle(handle: BinaryIO) -> None:
    handle.seek(0)
    if not handle.read(1):
        handle.seek(0)
        handle.write(b"0")
        handle.flush()
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock_handle(handle: BinaryIO) -> None:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def output_pair_lock(paths: Dict[str, Path], action: str) -> Iterator[Path]:
    lock_key = "|".join(sorted(file_identity(path) for path in paths.values()))
    digest = hashlib.sha256(lock_key.encode("utf-8")).hexdigest()[:16]
    first_path = next(iter(paths.values()))
    lock_path = first_path.parent / f".subtitle-pair-{digest}.lock"
    handle = lock_path.open("a+b")
    try:
        try:
            _lock_handle(handle)
        except OSError as exc:
            raise SubtitleSkillError(
                "Another subtitle command is already publishing this SRT/TXT pair.",
                action=action,
                step="validate_output",
                error_type="output_locked",
                suggested_fix="Wait for the active publisher to finish, then retry.",
            ) from exc
        try:
            yield lock_path
        finally:
            try:
                _unlock_handle(handle)
            except OSError:
                # Closing the handle releases the OS lock; an explicit unlock
                # failure must not turn an already committed SRT into failure.
                pass
    finally:
        try:
            handle.close()
        except OSError:
            pass


def promote_temp_file(source: Path, target: Path) -> None:
    source.replace(target)


def _save_main_outputs_unlocked(
    asr_data: ASRData,
    output_dir: Path,
    base_name: str,
    *,
    subtitle_format: str = "bilingual-trans-first",
    action: str,
    replace_existing: bool = False,
    protected_paths: tuple[Path, ...] = (),
) -> Dict[str, Path]:
    paths = output_paths(output_dir, base_name)
    validate_output_pair_preflight(
        paths,
        action=action,
        replace_existing=replace_existing,
        protected_paths=protected_paths,
    )
    existing = [path for path in paths.values() if path.exists()]

    token = uuid.uuid4().hex
    temporary_paths = {
        key: output_dir / f".publish-{key}-{token}{path.suffix}"
        for key, path in paths.items()
    }
    archived: Dict[str, Path] = {}
    promoted: list[Path] = []
    try:
        asr_data.save(str(temporary_paths["srt"]), subtitle_format=subtitle_format)
        asr_data.save(str(temporary_paths["txt"]), subtitle_format=subtitle_format)
        validate_main_outputs(
            temporary_paths,
            action,
            expected_data=asr_data,
            subtitle_format=subtitle_format,
        )

        if existing:
            archive_dir = get_work_dir(output_dir) / "archive"
            archive_dir.mkdir(parents=True, exist_ok=True)
            stamp = f"{datetime.now():%Y%m%d-%H%M%S-%f}-{token}"
            for key, path in paths.items():
                if path.exists():
                    archive_base = component_safe_base_name(
                        f"{path.stem}.previous-{stamp}"
                    )
                    archive = archive_dir / f"{archive_base}{path.suffix}"
                    path.replace(archive)
                    archived[key] = archive

        for key in ("txt", "srt"):
            promote_temp_file(temporary_paths[key], paths[key])
            promoted.append(paths[key])
        result = dict(paths)
        result.update({f"archived_{key}": path for key, path in archived.items()})
        return result
    except Exception as publish_error:
        rollback_errors: list[str] = []
        for key, archive in archived.items():
            try:
                if archive.exists():
                    archive.replace(paths[key])
            except OSError as exc:
                rollback_errors.append(f"{key}: {exc}")
        for key, path in paths.items():
            if key in archived or path not in promoted:
                continue
            try:
                unlink_with_retries(path)
            except OSError as exc:
                rollback_errors.append(f"{key}: {exc}")
        if rollback_errors:
            raise SubtitleSkillError(
                "Output pair promotion failed and rollback was incomplete: "
                + "; ".join(rollback_errors),
                action=action,
                step="rollback_output",
                error_type="rollback_failure",
                suggested_fix="Recover the archived pair under _subtitle_work/archive before retrying.",
                details={
                    "archived_outputs": {key: str(path) for key, path in archived.items()},
                    "rollback_errors": rollback_errors,
                },
            ) from publish_error
        if isinstance(publish_error, SubtitleSkillError):
            raise
        raise SubtitleSkillError(
            f"Output pair publication failed: {publish_error}",
            action=action,
            step="publish_output",
            error_type="publish_failure",
            suggested_fix="Resolve the filesystem error; the command did not commit a complete SRT/TXT pair.",
            details={"archived_outputs": {key: str(path) for key, path in archived.items()}},
        ) from publish_error
    finally:
        for path in temporary_paths.values():
            unlink_with_retries(path, suppress_errors=True)


def save_main_outputs(
    asr_data: ASRData,
    output_dir: Path,
    base_name: str,
    *,
    subtitle_format: str = "bilingual-trans-first",
    action: str,
    replace_existing: bool = False,
    protected_paths: tuple[Path, ...] = (),
) -> Dict[str, Path]:
    paths = output_paths(output_dir, base_name)
    validate_output_pair_preflight(
        paths,
        action=action,
        replace_existing=replace_existing,
        protected_paths=protected_paths,
    )
    with output_pair_lock(paths, action):
        return _save_main_outputs_unlocked(
            asr_data,
            output_dir,
            base_name,
            subtitle_format=subtitle_format,
            action=action,
            replace_existing=replace_existing,
            protected_paths=protected_paths,
        )


def _save_repair_outputs_unlocked(
    asr_data: ASRData,
    output_dir: Path,
    base_name: str,
    *,
    subtitle_format: str = "bilingual-trans-first",
) -> Dict[str, Path]:
    paths = output_paths(output_dir, base_name)
    existing = [str(path) for path in paths.values() if path.exists()]
    if existing:
        raise SubtitleSkillError(
            "Targeted repair outputs already exist; existing files were not changed.",
            action="transcribe",
            step="validate_output",
            error_type="output_exists",
            suggested_fix="Use a different repair directory or a different interval.",
        )

    token = uuid.uuid4().hex
    temporary_paths = {
        key: output_dir / f".repair-{key}-{token}{path.suffix}"
        for key, path in paths.items()
    }
    promoted: list[Path] = []
    try:
        asr_data.save(str(temporary_paths["srt"]), subtitle_format=subtitle_format)
        asr_data.save(str(temporary_paths["txt"]), subtitle_format=subtitle_format)
        validate_main_outputs(
            temporary_paths,
            "transcribe",
            expected_data=asr_data,
            subtitle_format=subtitle_format,
        )
        for key in ("txt", "srt"):
            promote_temp_file(temporary_paths[key], paths[key])
            promoted.append(paths[key])
        return paths
    except Exception as publish_error:
        rollback_errors: list[str] = []
        for path in reversed(promoted):
            try:
                unlink_with_retries(path)
            except OSError as exc:
                rollback_errors.append(f"{path}: {exc}")
        if rollback_errors:
            raise SubtitleSkillError(
                "Targeted repair promotion failed and rollback was incomplete: "
                + "; ".join(rollback_errors),
                action="transcribe",
                step="rollback_output",
                error_type="rollback_failure",
                suggested_fix="Remove the incomplete repair output after releasing its file lock, then retry.",
                details={"rollback_errors": rollback_errors},
            ) from publish_error
        if isinstance(publish_error, SubtitleSkillError):
            raise
        raise SubtitleSkillError(
            f"Targeted repair publication failed: {publish_error}",
            action="transcribe",
            step="publish_output",
            error_type="publish_failure",
            suggested_fix="Resolve the filesystem error and retry the isolated repair.",
        ) from publish_error
    finally:
        for path in temporary_paths.values():
            unlink_with_retries(path, suppress_errors=True)


def save_repair_outputs(
    asr_data: ASRData,
    output_dir: Path,
    base_name: str,
    *,
    subtitle_format: str = "bilingual-trans-first",
) -> Dict[str, Path]:
    paths = output_paths(output_dir, base_name)
    validate_output_pair_preflight(
        paths,
        action="transcribe",
        replace_existing=False,
    )
    with output_pair_lock(paths, "transcribe"):
        return _save_repair_outputs_unlocked(
            asr_data,
            output_dir,
            base_name,
            subtitle_format=subtitle_format,
        )


def work_json_output_path(
    asr_data: ASRData, work_dir: Path, base_name: str, suffix: str
) -> Path:
    payload = asr_data.to_json(include_words=True)
    digest = sha256_bytes(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    )[:12]
    return work_dir / work_artifact_filename(
        f"{base_name}-{digest}", f".{suffix}.json"
    )


def save_work_json(asr_data: ASRData, work_dir: Path, base_name: str, suffix: str) -> Path:
    payload = asr_data.to_json(include_words=True)
    path = work_json_output_path(asr_data, work_dir, base_name, suffix)
    write_json_atomic(path, payload)
    return path


def nested_qc_output_paths(
    asr_data: ASRData,
    work_dir: Path,
    base_name: str,
    *,
    include_seams: bool,
) -> list[Path]:
    artifact_base_name = f"{base_name}-{serialized_srt_sha256(asr_data)[:12]}"
    paths = [work_dir / qc_report_filename(artifact_base_name)]
    if include_seams:
        paths.append(
            work_dir / work_artifact_filename(
                artifact_base_name, ".chunk-seams.json"
            )
        )
    return paths


def metadata_output_path(work_dir: Path, base_name: str, source_srt_hash: str) -> Path:
    return work_dir / work_artifact_filename(
        f"{base_name}-{source_srt_hash[:12]}", ".metadata.json"
    )


def require_valid_asr_timeline(asr_data: ASRData, action: str) -> None:
    try:
        validate_asr_timeline(asr_data.segments)
    except ValueError as exc:
        raise SubtitleSkillError(
            f"Invalid subtitle timeline: {exc}",
            action=action,
            step="validate_output",
            error_type="invalid_srt",
            suggested_fix="Repair zero-duration or overlapping cues before treating the run as complete.",
        ) from exc


def require_valid_srt_roundtrip(asr_data: ASRData, action: str) -> None:
    try:
        parse_srt_strict(asr_data.to_srt())
    except (UnicodeError, ValueError) as exc:
        raise SubtitleSkillError(
            f"Serialized SRT is not strictly parseable: {exc}",
            action=action,
            step="validate_output",
            error_type="invalid_srt",
            suggested_fix="Repair blank lines or malformed cue text before writing final SRT.",
        ) from exc


def wrap_split_validation_error(exc: Exception, action: str) -> SubtitleSkillError:
    return SubtitleSkillError(
        f"Invalid subtitle timeline: {exc}",
        action=action,
        step="validate_output",
        error_type="invalid_srt",
        suggested_fix="Repair reverse-timeline, zero-duration, or overlapping cues before treating the run as complete.",
    )


def validate_main_outputs(
    paths: Dict[str, Path],
    action: str,
    *,
    expected_data: Optional[ASRData] = None,
    subtitle_format: str = "bilingual-trans-first",
) -> None:
    for key in ("srt", "txt"):
        path = paths[key]
        if not path.exists() or path.stat().st_size <= 0:
            raise SubtitleSkillError(
                f"Expected {key.upper()} output was not created: {path}",
                action=action,
                step="validate_output",
                error_type="missing_output",
            )
    try:
        parsed = parse_srt_strict(paths["srt"].read_text(encoding="utf-8-sig"))
    except (UnicodeError, ValueError) as exc:
        raise SubtitleSkillError(
            f"Output is not a strict valid SRT: {paths['srt']}: {exc}",
            action=action,
            step="validate_output",
            error_type="invalid_srt",
        ) from exc
    if (
        expected_data is not None
        and hasattr(expected_data, "to_srt")
        and hasattr(expected_data, "to_txt")
    ):
        require_valid_asr_timeline(parsed, action)
        expected_srt = expected_data.to_srt(subtitle_format=subtitle_format)
        expected_txt = expected_data.to_txt(subtitle_format=subtitle_format)
        actual_srt = paths["srt"].read_text(encoding="utf-8")
        actual_txt = paths["txt"].read_text(encoding="utf-8")
        if actual_srt != expected_srt or actual_txt != expected_txt:
            raise SubtitleSkillError(
                "Published SRT/TXT bytes do not match the same subtitle data.",
                action=action,
                step="validate_output",
                error_type="output_pair_mismatch",
                suggested_fix="Retry after removing the incomplete temporary outputs.",
            )


def require_strict_srt_input(input_path: Path, action: str) -> ASRData:
    try:
        return parse_srt_strict(input_path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise SubtitleSkillError(
            f"Invalid SRT input: {exc}",
            action=action,
            step="parse_input",
            error_type="invalid_srt",
            suggested_fix="Repair malformed, non-sequential, zero-duration, or overlapping cues before processing.",
        ) from exc


def silence_stdout() -> None:
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


def print_result(payload: Dict[str, Any]) -> None:
    text = json.dumps(payload, ensure_ascii=True, indent=2)
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


def console_result(payload: Dict[str, Any]) -> Dict[str, Any]:
    action = payload.get("action")
    if action in {"transcribe", "split"} and isinstance(payload.get("qc"), dict):
        result = dict(payload)
        qc = result.pop("qc")
        result["qc_summary"] = {
            "status": qc.get("status"),
            "exit_code": qc.get("exit_code"),
            "cue_count": qc.get("cue_count"),
            "high_risk_count": qc.get("high_risk_count"),
            "ok_short_count": qc.get("ok_short_count"),
            "approved_short_count": qc.get("approved_short_count"),
            "seam_repair_failure_count": len(qc.get("seam_repair_failures") or []),
        }
        return result
    if action == "qc":
        return {
            "ok": payload.get("ok"),
            "action": action,
            "status": payload.get("status"),
            "exit_code": payload.get("exit_code"),
            "source_path": payload.get("source_path"),
            "cue_count": payload.get("cue_count"),
            "high_risk_count": payload.get("high_risk_count"),
            "ok_short_count": payload.get("ok_short_count"),
            "approved_short_count": payload.get("approved_short_count"),
            "qc_path": payload.get("qc_path"),
        }
    return payload


def require_llm_api_key(args: argparse.Namespace, action: str) -> str:
    api_key = (
        getattr(args, "api_key", None)
        or os.getenv("SUBTITLE_LLM_API_KEY", "").strip()
    )
    if not api_key:
        raise SubtitleSkillError(
            "Missing LLM API key.",
            action=action,
            step="validate_runtime",
            error_type="missing_api_key",
            suggested_fix=f"Set SUBTITLE_LLM_API_KEY, pass --api-key, or create {LLM_CONFIG_PATH.name}.",
        )
    return api_key


def llm_base_url(args: argparse.Namespace) -> str:
    return (
        getattr(args, "base_url", None)
        or os.getenv("SUBTITLE_LLM_BASE_URL", "").strip()
        or CONFIG_DEFAULT_LLM_BASE_URL
    )


def llm_model(args: argparse.Namespace) -> str:
    return getattr(args, "model", None) or os.getenv("SUBTITLE_LLM_MODEL", "").strip() or DEFAULT_LLM_MODEL


def fetch_video_metadata(url: str) -> Dict[str, Any]:
    try:
        import yt_dlp
    except ImportError as exc:
        raise SubtitleSkillError(
            "Missing dependency `yt-dlp`.",
            action="transcribe",
            step="validate_runtime",
            error_type="missing_dependency",
            suggested_fix="Install requirements.txt for this skill.",
        ) from exc

    opts = {"quiet": True, "no_warnings": True, "skip_download": True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    return {
        "id": info.get("id"),
        "title": info.get("title"),
        "channel": info.get("channel") or info.get("uploader") or "",
        "webpage_url": info.get("webpage_url") or url,
        "description": info.get("description") or "",
        "subtitles": info.get("subtitles") or {},
        "automatic_captions": info.get("automatic_captions") or {},
    }


def write_youtube_context(work_dir: Path, metadata: Optional[Dict[str, Any]]) -> Optional[Path]:
    context_path = work_dir / "context.txt"
    if context_path.exists():
        context_path.unlink()

    if not metadata or not (metadata.get("description") or "").strip():
        return None

    parts = [
        f"Title: {metadata.get('title') or ''}".rstrip(),
        f"Channel: {metadata.get('channel') or ''}".rstrip(),
        "Description:",
        metadata.get("description", "").strip(),
    ]
    context_path.write_text("\n".join(parts).strip() + "\n", encoding="utf-8")
    return context_path


def pick_subtitle_language(subtitles: Dict[str, Any], requested_language: Optional[str]) -> Optional[str]:
    if not subtitles:
        return None
    available = sorted(subtitles.keys())
    if requested_language:
        requested = requested_language.lower()
        for candidate in available:
            lowered = candidate.lower()
            if lowered == requested or lowered.startswith(f"{requested}-") or requested.startswith(f"{lowered}-"):
                return candidate
        return None
    for preferred in ("en", "zh-Hans", "zh-CN", "zh", "ja"):
        for candidate in available:
            lowered = candidate.lower()
            if lowered == preferred.lower() or lowered.startswith(f"{preferred.lower()}-"):
                return candidate
    return available[0]


def language_matches(actual: Optional[str], expected: Optional[str]) -> bool:
    if not actual or not expected:
        return False
    actual_normalized = actual.lower().replace("_", "-")
    expected_normalized = expected.lower().replace("_", "-")
    return (
        actual_normalized == expected_normalized
        or actual_normalized.startswith(f"{expected_normalized}-")
        or expected_normalized.startswith(f"{actual_normalized}-")
    )


def download_manual_subtitles(
    url: str,
    work_dir: Path,
    requested_language: Optional[str],
    metadata: Optional[Dict[str, Any]] = None,
) -> tuple[Optional[Path], Optional[Dict[str, Any]], Optional[str]]:
    if not is_youtube_url(url):
        return None, None, None

    metadata = metadata or fetch_video_metadata(url)
    selected_language = pick_subtitle_language(metadata.get("subtitles") or {}, requested_language)
    if not selected_language:
        return None, metadata, None

    import yt_dlp

    temp_prefix = "manual_subtitle"
    for candidate in work_dir.glob(f"{temp_prefix}*"):
        if candidate.is_file():
            candidate.unlink()

    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "writesubtitles": True,
        "writeautomaticsub": False,
        "subtitleslangs": [selected_language],
        "subtitlesformat": "srt",
        "outtmpl": str(work_dir / f"{temp_prefix}.%(ext)s"),
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url])

    candidates = sorted(work_dir.glob(f"{temp_prefix}*.srt"))
    if not candidates:
        return None, metadata, selected_language
    return candidates[0], metadata, selected_language


def resolve_clip_timestamps(args: argparse.Namespace) -> Optional[list[float]]:
    start = args.start_seconds
    end = args.end_seconds
    if (start is None) != (end is None):
        raise SubtitleSkillError(
            "--start-seconds and --end-seconds must be supplied together.",
            action="transcribe",
            step="validate_input",
            error_type="invalid_clip_interval",
            suggested_fix="Pass both bounds, for example --start-seconds 120 --end-seconds 128.",
        )
    if start is None:
        if args.no_vad:
            raise SubtitleSkillError(
                "--no-vad is only allowed with a targeted clip interval.",
                action="transcribe",
                step="validate_input",
                error_type="invalid_repair_controls",
                suggested_fix="Pass --start-seconds, --end-seconds, --language, and --no-vad together.",
            )
        return None
    if start < 0 or end <= start:
        raise SubtitleSkillError(
            "The clip interval must satisfy 0 <= start-seconds < end-seconds.",
            action="transcribe",
            step="validate_input",
            error_type="invalid_clip_interval",
            suggested_fix="Use non-negative seconds and make end-seconds greater than start-seconds.",
        )
    if not args.no_vad or not args.language:
        raise SubtitleSkillError(
            "Targeted repair requires a fixed language and --no-vad.",
            action="transcribe",
            step="validate_input",
            error_type="invalid_repair_controls",
            suggested_fix="Pass --start-seconds, --end-seconds, --language, and --no-vad together.",
        )
    return [float(start), float(end)]


def targeted_repair_base_name(
    base_name: str, clip_timestamps: list[float]
) -> str:
    start_ms = round(clip_timestamps[0] * 1000)
    end_ms = round(clip_timestamps[1] * 1000)
    return component_safe_base_name(
        f"{base_name}.repair-{start_ms:010d}-{end_ms:010d}"
    )


def run_transcribe(args: argparse.Namespace) -> Dict[str, Any]:
    output_dir = Path(args.output_dir).resolve()
    input_path = Path(args.input)
    input_is_file = input_path.exists()
    input_is_url = is_url(args.input)

    if not input_is_file and not input_is_url:
        raise SubtitleSkillError(
            f"Input is neither an existing local file nor an http(s) URL: {args.input}",
            action="transcribe",
            step="validate_input",
            error_type="invalid_input",
            suggested_fix="Pass an existing audio/video file path or an http(s) video URL.",
        )
    if (
        args.language
        and args.require_language
        and not language_matches(args.language, args.require_language)
    ):
        raise SubtitleSkillError(
            "--language and --require-language must identify the same language when both are supplied.",
            action="transcribe",
            step="validate_input",
            error_type="conflicting_language_controls",
            suggested_fix="Remove --language to use detection, or make both language codes match.",
        )

    clip_timestamps = resolve_clip_timestamps(args)
    effective_vad_filter = clip_timestamps is None
    if (
        is_youtube_url(args.input)
        and not args.force_asr
        and (clip_timestamps is not None or args.no_vad)
    ):
        raise SubtitleSkillError(
            "Targeted interval and VAD controls require ASR for YouTube inputs.",
            action="transcribe",
            step="validate_input",
            error_type="asr_control_requires_force_asr",
            suggested_fix="Add --force-asr, or run the targeted repair against the downloaded local media file.",
        )

    work_dir = get_work_dir(output_dir)
    video_metadata = fetch_video_metadata(args.input) if is_youtube_url(args.input) else None
    context_path = write_youtube_context(work_dir, video_metadata)

    metadata: Dict[str, Any] = {
        "input": args.input,
        "model": args.model,
        "device": args.device,
        "compute_type": args.compute_type,
        "requested_vad_filter": not args.no_vad,
        "effective_vad_filter": effective_vad_filter,
        "clip_timestamps": clip_timestamps,
        "semantic_split": bool(args.semantic_split),
        "used_manual_subtitles": False,
    }
    if video_metadata is not None:
        metadata["video_metadata"] = video_metadata
    if context_path is not None:
        metadata["context_file"] = str(context_path)

    if not args.force_asr and not args.semantic_split and is_youtube_url(args.input):
        required_language = args.require_language
        manual_srt, video_metadata, selected_language = download_manual_subtitles(
            args.input,
            work_dir,
            required_language or args.language,
            video_metadata,
        )
        metadata["manual_subtitle_language"] = selected_language
        if manual_srt is not None:
            asr_data = require_strict_srt_input(manual_srt, "transcribe")
            base_name = sanitize_filename((video_metadata or {}).get("title") or manual_srt.stem)
            intended_paths = output_paths(output_dir, base_name)
            validate_output_pair_preflight(
                intended_paths,
                action="transcribe",
                replace_existing=args.replace_existing,
                protected_paths=(manual_srt,),
            )
            with output_pair_lock(intended_paths, "transcribe"):
                work_json = work_json_output_path(
                    asr_data, work_dir, base_name, "manual-subtitles"
                )
                metadata.update(
                    {
                        "used_manual_subtitles": True,
                        "source_language": selected_language,
                        "source_language_origin": "manual_subtitle_track",
                        "required_source_language": required_language,
                        "source_srt_hash_algorithm": "sha256",
                        "source_srt_sha256": serialized_srt_sha256(asr_data),
                        "source_srt_path": str(intended_paths["srt"]),
                        "work_json": str(work_json),
                    }
                )
                metadata_path = metadata_output_path(
                    work_dir,
                    base_name,
                    str(metadata["source_srt_sha256"]),
                )
                with rollback_artifacts_on_error(
                    [work_json, metadata_path], "transcribe"
                ):
                    save_work_json(
                        asr_data, work_dir, base_name, "manual-subtitles"
                    )
                    write_json_atomic(metadata_path, metadata)
                    outputs = _save_main_outputs_unlocked(
                        asr_data,
                        output_dir,
                        base_name,
                        action="transcribe",
                        replace_existing=args.replace_existing,
                        protected_paths=(manual_srt,),
                    )
            return {
                "ok": True,
                "action": "transcribe",
                "outputs": {key: str(value) for key, value in outputs.items()},
                "work_dir": str(work_dir),
                "metadata": str(metadata_path),
            }

    if input_is_file:
        base_name = input_path.stem
    elif input_is_url:
        parsed = urlparse(args.input)
        base_name = parse_qs(parsed.query).get("v", [""])[0] or Path(parsed.path).stem or "subtitles"
    if clip_timestamps is not None:
        base_name = targeted_repair_base_name(base_name, clip_timestamps)
        repair_paths = output_paths(output_dir, base_name)
        if any(path.exists() for path in repair_paths.values()):
            raise SubtitleSkillError(
                "Targeted repair outputs already exist; existing files were not changed.",
                action="transcribe",
                step="validate_output",
                error_type="output_exists",
                suggested_fix="Use a different repair directory or a different interval.",
            )

    protected = (input_path.resolve(),) if input_is_file else ()
    intended_paths = output_paths(output_dir, base_name)
    validate_output_pair_preflight(
        intended_paths,
        action="transcribe",
        replace_existing=False if clip_timestamps is not None else args.replace_existing,
        protected_paths=protected,
    )

    split_api_key = require_llm_api_key(args, "transcribe") if args.semantic_split else None
    split_base_url = llm_base_url(args) if args.semantic_split else None
    seam_times_ms: list[int] = []
    seam_repair_failures: list[Dict[str, Any]] = []

    asr_metadata: Dict[str, Any] = {}
    try:
        asr_data = process_media(
            args.input,
            str(work_dir),
            model_name=args.model,
            device=args.device,
            compute_type=args.compute_type,
            language=args.language,
            vad_filter=effective_vad_filter,
            clip_timestamps=clip_timestamps,
            split_enabled=args.semantic_split,
            split_model=args.split_model,
            split_max_chars_cjk=args.split_max_chars_cjk,
            split_max_words_en=args.split_max_words_en,
            split_max_chars_en=args.split_max_chars_en,
            split_chunk_word_limit=args.split_chunk_word_limit,
            split_max_retries=args.split_max_retries,
            api_key=split_api_key,
            base_url=split_base_url,
            seam_times_out=seam_times_ms if args.semantic_split else None,
            seam_failures_out=seam_repair_failures if args.semantic_split else None,
            asr_metadata_out=asr_metadata,
        )
    except SubtitleSplitValidationError as exc:
        raise wrap_split_validation_error(exc, "transcribe") from exc
    require_valid_asr_timeline(asr_data, "transcribe")
    require_valid_srt_roundtrip(asr_data, "transcribe")
    detected_language = asr_metadata.get("language") or args.language
    if args.require_language and not language_matches(detected_language, args.require_language):
        raise SubtitleSkillError(
            f"Required source language {args.require_language!r}, but ASR detected {detected_language!r}.",
            action="transcribe",
            step="validate_source_language",
            error_type="source_language_mismatch",
            suggested_fix="Use verified English source media/subtitles or add an explicit source-to-English stage before translation.",
        )
    language_probability = asr_metadata.get("language_probability")
    if (
        args.require_language
        and asr_metadata.get("language")
        and (
            not isinstance(language_probability, (int, float))
            or isinstance(language_probability, bool)
            or not math.isfinite(float(language_probability))
            or float(language_probability) < MIN_ASR_LANGUAGE_PROBABILITY
        )
    ):
        raise SubtitleSkillError(
            f"ASR source-language confidence is below {MIN_ASR_LANGUAGE_PROBABILITY}: {language_probability!r}.",
            action="transcribe",
            step="validate_source_language",
            error_type="source_language_unreliable",
            suggested_fix="Provide verified English manual subtitles, or rerun ASR with an explicit matching --language.",
        )
    with output_pair_lock(intended_paths, "transcribe"):
        work_json = work_json_output_path(
            asr_data, work_dir, base_name, "transcription"
        )
        metadata.update(
            {
                "work_json": str(work_json),
                "source_language": detected_language,
                "source_language_origin": "asr_detection" if asr_metadata.get("language") else "fixed_asr_language",
                "source_language_probability": language_probability,
                "required_source_language": args.require_language,
                "source_srt_hash_algorithm": "sha256",
                "source_srt_sha256": serialized_srt_sha256(asr_data),
                "source_srt_path": str(intended_paths["srt"]),
            }
        )
        metadata_path = metadata_output_path(
            work_dir,
            base_name,
            str(metadata["source_srt_sha256"]),
        )
        qc_fields: Optional[Dict[str, Any]] = None
        artifact_paths = [work_json, metadata_path]
        if args.semantic_split:
            artifact_paths.extend(
                nested_qc_output_paths(
                    asr_data, work_dir, base_name, include_seams=True
                )
            )
        with rollback_artifacts_on_error(artifact_paths, "transcribe"):
            save_work_json(asr_data, work_dir, base_name, "transcription")
            write_json_atomic(metadata_path, metadata)
            if args.semantic_split:
                intended_srt = intended_paths["srt"]
                qc_fields = write_qc_report(
                    None,
                    work_dir,
                    base_name,
                    bilingual=False,
                    asr_data=asr_data,
                    source_path=str(intended_srt),
                    seam_times_ms=seam_times_ms,
                    seam_repair_failures=seam_repair_failures,
                    max_word_count_english=args.split_max_words_en,
                    max_display_chars_english=args.split_max_chars_en,
                )
            if clip_timestamps is not None:
                outputs = _save_repair_outputs_unlocked(
                    asr_data, output_dir, base_name
                )
            else:
                outputs = _save_main_outputs_unlocked(
                    asr_data,
                    output_dir,
                    base_name,
                    action="transcribe",
                    replace_existing=args.replace_existing,
                    protected_paths=protected,
                )
    payload = {
        "ok": True,
        "action": "transcribe",
        "outputs": {key: str(value) for key, value in outputs.items()},
        "work_dir": str(work_dir),
        "metadata": str(metadata_path),
    }
    if qc_fields is not None:
        payload.update(qc_fields)
    return payload


def run_split(args: argparse.Namespace) -> Dict[str, Any]:
    output_dir = Path(args.output_dir).resolve()
    input_path = Path(args.input).resolve()
    if not input_path.exists():
        raise SubtitleSkillError(f"Input JSON not found: {input_path}", action="split", step="validate_input", error_type="missing_input")

    try:
        asr_data = ASRData.from_whisper_json(
            json.loads(input_path.read_text(encoding="utf-8"))
        )
    except (RuntimeError, ValueError) as exc:
        raise wrap_split_validation_error(exc, "split") from exc
    work_dir = get_work_dir(output_dir)
    base_name = args.output_base or input_path.stem
    validate_output_pair_preflight(
        output_paths(output_dir, base_name),
        action="split",
        replace_existing=args.replace_existing,
        protected_paths=(input_path,),
    )
    api_key = require_llm_api_key(args, "split")
    seam_times_ms: list[int] = []
    seam_repair_failures: list[Dict[str, Any]] = []
    try:
        split_data = split_subtitle(
            asr_data,
            model=args.split_model,
            api_key=api_key,
            base_url=llm_base_url(args),
            max_word_count_cjk=args.split_max_chars_cjk,
            max_word_count_english=args.split_max_words_en,
            max_display_chars_english=args.split_max_chars_en,
            chunk_word_limit=args.split_chunk_word_limit,
            max_retries=args.split_max_retries,
            seam_times_out=seam_times_ms,
            seam_failures_out=seam_repair_failures,
        )
    except SubtitleSplitValidationError as exc:
        raise wrap_split_validation_error(exc, "split") from exc
    require_valid_asr_timeline(split_data, "split")
    require_valid_srt_roundtrip(split_data, "split")
    intended_paths = output_paths(output_dir, base_name)
    with output_pair_lock(intended_paths, "split"):
        work_json = work_json_output_path(
            split_data, work_dir, base_name, "semantic-split"
        )
        artifact_paths = [work_json] + nested_qc_output_paths(
            split_data, work_dir, base_name, include_seams=True
        )
        with rollback_artifacts_on_error(artifact_paths, "split"):
            save_work_json(split_data, work_dir, base_name, "semantic-split")
            qc_fields = write_qc_report(
                None,
                work_dir,
                base_name,
                bilingual=False,
                asr_data=split_data,
                source_path=str(intended_paths["srt"]),
                seam_times_ms=seam_times_ms,
                seam_repair_failures=seam_repair_failures,
                max_word_count_english=args.split_max_words_en,
                max_display_chars_english=args.split_max_chars_en,
            )
            outputs = _save_main_outputs_unlocked(
                split_data,
                output_dir,
                base_name,
                action="split",
                replace_existing=args.replace_existing,
                protected_paths=(input_path,),
            )
    payload = {
        "ok": True,
        "action": "split",
        "outputs": {key: str(value) for key, value in outputs.items()},
        "work_dir": str(work_dir),
        "work_json": str(work_json),
    }
    payload.update(qc_fields)
    return payload


def write_qc_report(
    srt_path: Optional[Path],
    work_dir: Path,
    base_name: str,
    *,
    bilingual: bool,
    asr_data: Optional[ASRData] = None,
    source_path: Optional[str] = None,
    seam_times_ms: Optional[list[int]] = None,
    seam_repair_failures: Optional[list[Dict[str, Any]]] = None,
    max_word_count_english: int = DEFAULT_MAX_WORD_COUNT_ENGLISH,
    max_display_chars_english: int = DEFAULT_MAX_DISPLAY_CHARS_ENGLISH,
) -> Dict[str, Any]:
    if seam_times_ms is not None:
        try:
            seam_times_ms = normalize_seam_times(seam_times_ms)
        except ValueError as exc:
            raise SubtitleSkillError(
                f"Invalid seam times: {exc}",
                action="qc",
                step="validate_output",
                error_type="invalid_input",
                suggested_fix="Regenerate semantic split so seam times are non-negative integers.",
            ) from exc
    try:
        if asr_data is not None:
            report = inspect_asr_data(
                asr_data,
                bilingual=bilingual,
                seam_times_ms=seam_times_ms,
                source_path=source_path,
                max_word_count_english=max_word_count_english,
                max_display_chars_english=max_display_chars_english,
            )
        elif srt_path is not None:
            report = inspect_subtitle_path(
                srt_path,
                bilingual=bilingual,
                seam_times_ms=seam_times_ms,
                max_word_count_english=max_word_count_english,
                max_display_chars_english=max_display_chars_english,
            )
        else:
            raise ValueError("write_qc_report requires srt_path or asr_data")
    except (UnicodeError, ValueError) as exc:
        raise SubtitleSkillError(
            f"Invalid SRT input: {exc}",
            action="qc",
            step="parse_input",
            error_type="invalid_srt",
            suggested_fix="Repair the malformed SRT block before treating nested QC as complete.",
        ) from exc
    artifact_base_name = (
        f"{base_name}-{serialized_srt_sha256(asr_data)[:12]}"
        if asr_data is not None
        else base_name
    )
    qc_path = work_dir / qc_report_filename(artifact_base_name)
    failures = list(seam_repair_failures or [])
    add_seam_failures_to_report(report, failures)
    fields: Dict[str, Any] = {"qc": report, "qc_path": str(qc_path)}
    if seam_times_ms is not None:
        seams_path = work_dir / work_artifact_filename(
            artifact_base_name, ".chunk-seams.json"
        )
        write_json_atomic(
            seams_path,
            {
                "seam_times_ms": list(seam_times_ms),
                "seam_repair_failures": failures,
            },
        )
        fields["seam_times_path"] = str(seams_path)
    try:
        write_json_atomic(qc_path, report)
    except (OSError, UnicodeError, ValueError) as exc:
        raise SubtitleSkillError(
            f"Could not write QC report: {exc}",
            action="qc",
            step="write_report",
            error_type="report_write_failure",
            suggested_fix="Choose a writable JSON output path whose parent is a directory.",
            details={"output_path": str(qc_path)},
        ) from exc
    fields["status"] = report.get("status", "ok")
    fields["exit_code"] = int(report.get("exit_code", 0))
    return fields


def add_seam_failures_to_report(
    report: Dict[str, Any],
    failures: list[Dict[str, Any]],
) -> None:
    if not failures:
        return
    failure_findings = [
        {
            "cue": None,
            "start_ms": failure.get("seam_time_ms"),
            "end_ms": failure.get("seam_time_ms"),
            "duration_ms": 0,
            "text": f"{failure.get('left_text', '')} | {failure.get('right_text', '')}",
            "word_count": 0,
            "severity": "high_risk",
            "reasons": ["seam_repair_failed"],
            "seam_failure": failure,
        }
        for failure in failures
    ]
    report["findings"].extend(failure_findings)
    report["review_items"].extend(failure_findings)
    report["high_risk_count"] += len(failure_findings)
    report["status"] = "review_required"
    report["exit_code"] = 2
    report["seam_repair_failures"] = failures


def load_seam_artifact(path: Path) -> Dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SubtitleSkillError(
            f"Could not parse seam-times JSON: {path}",
            action="qc",
            step="validate_input",
            error_type="invalid_input",
            suggested_fix="Regenerate the chunk-seams file or provide valid JSON.",
        ) from exc
    if not isinstance(payload, dict) or "seam_times_ms" not in payload:
        raise SubtitleSkillError(
            f"Seam-times file must be a JSON object with seam_times_ms: {path}",
            action="qc",
            step="validate_input",
            error_type="invalid_input",
        )
    values = payload["seam_times_ms"]
    if not isinstance(values, list):
        raise SubtitleSkillError(
            f"Seam-times JSON field must be a list: {path}",
            action="qc",
            step="validate_input",
            error_type="invalid_input",
        )
    if any(
        isinstance(value, bool) or not isinstance(value, int) or value < 0
        for value in values
    ):
        raise SubtitleSkillError(
            f"Seam-times file must contain non-negative integer milliseconds: {path}",
            action="qc",
            step="validate_input",
            error_type="invalid_input",
        )
    if values != sorted(values):
        raise SubtitleSkillError(
            f"Seam-times file must be sorted in ascending order: {path}",
            action="qc",
            step="validate_input",
            error_type="invalid_input",
        )
    failures = payload.get("seam_repair_failures", [])
    if not isinstance(failures, list):
        raise SubtitleSkillError(
            f"seam_repair_failures must be a list: {path}",
            action="qc",
            step="validate_input",
            error_type="invalid_input",
        )
    normalized_failures: list[Dict[str, Any]] = []
    for position, failure in enumerate(failures, start=1):
        if not isinstance(failure, dict):
            raise SubtitleSkillError(
                f"Seam failure entry {position} must be an object.",
                action="qc",
                step="validate_input",
                error_type="invalid_input",
            )
        seam_index = failure.get("seam_index")
        seam_time_ms = failure.get("seam_time_ms")
        reason = failure.get("reason")
        if (
            isinstance(seam_index, bool)
            or not isinstance(seam_index, int)
            or seam_index <= 0
            or isinstance(seam_time_ms, bool)
            or not isinstance(seam_time_ms, int)
            or seam_time_ms < 0
            or not isinstance(reason, str)
            or not reason.strip()
        ):
            raise SubtitleSkillError(
                f"Seam failure entry {position} requires a positive seam_index, "
                "non-negative seam_time_ms, and reason.",
                action="qc",
                step="validate_input",
                error_type="invalid_input",
            )
        normalized_failures.append(dict(failure))
    return {
        "seam_times_ms": list(values),
        "seam_repair_failures": normalized_failures,
    }


def load_seam_times_file(path: Path) -> list[int]:
    return load_seam_artifact(path)["seam_times_ms"]


def load_resolved_seams_file(path: Path) -> Dict[tuple[int, int], str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SubtitleSkillError(
            f"Could not parse resolved-seams JSON: {path}",
            action="qc",
            step="validate_input",
            error_type="invalid_input",
            suggested_fix="Provide valid JSON with a resolved_seams list.",
        ) from exc
    entries = payload.get("resolved_seams") if isinstance(payload, dict) else None
    if not isinstance(entries, list):
        raise SubtitleSkillError(
            "Resolved-seams JSON must contain a resolved_seams list.",
            action="qc",
            step="validate_input",
            error_type="invalid_input",
        )
    resolutions: Dict[tuple[int, int], str] = {}
    for position, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            raise SubtitleSkillError(
                f"Resolved seam entry {position} must be an object.",
                action="qc",
                step="validate_input",
                error_type="invalid_input",
            )
        seam_index = entry.get("seam_index")
        seam_time_ms = entry.get("seam_time_ms")
        reason = entry.get("reason")
        key = (seam_index, seam_time_ms)
        if (
            isinstance(seam_index, bool)
            or not isinstance(seam_index, int)
            or seam_index <= 0
            or isinstance(seam_time_ms, bool)
            or not isinstance(seam_time_ms, int)
            or seam_time_ms < 0
            or not isinstance(reason, str)
            or not reason.strip()
            or key in resolutions
        ):
            raise SubtitleSkillError(
                f"Resolved seam entry {position} requires a unique positive seam_index, "
                "non-negative seam_time_ms, and review reason.",
                action="qc",
                step="validate_input",
                error_type="invalid_input",
            )
        resolutions[key] = reason.strip()
    return resolutions


def load_approved_cues_file(path: Path) -> Dict[int, Dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SubtitleSkillError(
            f"Could not parse approved-cues JSON: {path}",
            action="qc",
            step="validate_input",
            error_type="invalid_input",
            suggested_fix="Provide valid JSON with an approved_cues list.",
        ) from exc
    entries = payload.get("approved_cues") if isinstance(payload, dict) else None
    if not isinstance(entries, list):
        raise SubtitleSkillError(
            "Approved-cues JSON must contain an approved_cues list.",
            action="qc",
            step="validate_input",
            error_type="invalid_input",
        )

    approvals: Dict[int, Dict[str, Any]] = {}
    for position, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            raise SubtitleSkillError(
                f"Approved cue entry {position} must be an object.",
                action="qc",
                step="validate_input",
                error_type="invalid_input",
            )
        cue = entry.get("cue")
        text = entry.get("text")
        reason = entry.get("reason")
        if (
            isinstance(cue, bool)
            or not isinstance(cue, int)
            or cue <= 0
            or not isinstance(text, str)
            or not text
            or not isinstance(reason, str)
            or not reason.strip()
            or cue in approvals
        ):
            raise SubtitleSkillError(
                f"Approved cue entry {position} requires a unique positive cue, exact text, and reason.",
                action="qc",
                step="validate_input",
                error_type="invalid_input",
            )
        approvals[cue] = {"text": text, "reason": reason.strip()}
    return approvals


def run_qc(args: argparse.Namespace) -> Dict[str, Any]:
    input_path = Path(args.input).resolve()
    if not input_path.exists():
        raise SubtitleSkillError(
            f"Input SRT not found: {input_path}",
            action="qc",
            step="validate_input",
            error_type="missing_input",
        )
    output_path = (
        Path(args.output).resolve()
        if args.output
        else default_qc_output_path(input_path)
    ).resolve()
    if file_identity(output_path) == file_identity(input_path):
        raise SubtitleSkillError(
            "QC report output must differ from the input SRT.",
            action="qc",
            step="validate_output",
            error_type="path_collision",
            suggested_fix="Choose a distinct JSON report path.",
        )
    approved_cues: Optional[Dict[int, Dict[str, Any]]] = None
    approved_path: Optional[Path] = None
    if args.approved_cues_file:
        approved_path = Path(args.approved_cues_file).resolve()
        if not approved_path.exists():
            raise SubtitleSkillError(
                f"Approved-cues file not found: {approved_path}",
                action="qc",
                step="validate_input",
                error_type="missing_input",
            )
        if file_identity(output_path) == file_identity(approved_path):
            raise SubtitleSkillError(
                "QC report output must differ from the approved-cues input.",
                action="qc",
                step="validate_output",
                error_type="path_collision",
                suggested_fix="Choose a distinct JSON report path.",
            )
        approved_cues = load_approved_cues_file(approved_path)
    seam_times_ms = None
    seam_repair_failures: list[Dict[str, Any]] = []
    seam_path: Optional[Path] = None
    if args.seam_times_file:
        seam_path = Path(args.seam_times_file).resolve()
        if not seam_path.exists():
            raise SubtitleSkillError(
                f"Seam-times file not found: {seam_path}",
                action="qc",
                step="validate_input",
                error_type="missing_input",
            )
        if file_identity(output_path) == file_identity(seam_path):
            raise SubtitleSkillError(
                "QC report output must differ from the seam-times input.",
                action="qc",
                step="validate_output",
                error_type="path_collision",
                suggested_fix="Choose a distinct JSON report path.",
            )
        seam_artifact = load_seam_artifact(seam_path)
        seam_times_ms = seam_artifact["seam_times_ms"]
        seam_repair_failures = seam_artifact["seam_repair_failures"]

    resolved_seams: Dict[tuple[int, int], str] = {}
    resolved_path: Optional[Path] = None
    if getattr(args, "resolved_seams_file", None):
        resolved_path = Path(args.resolved_seams_file).resolve()
        if seam_path is None:
            raise SubtitleSkillError(
                "--resolved-seams-file requires --seam-times-file.",
                action="qc",
                step="validate_input",
                error_type="invalid_input",
            )
        if not resolved_path.exists():
            raise SubtitleSkillError(
                f"Resolved-seams file not found: {resolved_path}",
                action="qc",
                step="validate_input",
                error_type="missing_input",
            )
        if file_identity(output_path) == file_identity(resolved_path):
            raise SubtitleSkillError(
                "QC report output must differ from the resolved-seams input.",
                action="qc",
                step="validate_output",
                error_type="path_collision",
                suggested_fix="Choose a distinct JSON report path.",
            )
        resolved_seams = load_resolved_seams_file(resolved_path)
        failure_keys = {
            (failure["seam_index"], failure["seam_time_ms"])
            for failure in seam_repair_failures
        }
        unknown = set(resolved_seams) - failure_keys
        if unknown:
            raise SubtitleSkillError(
                f"Resolved-seams file references unknown seam failures: {sorted(unknown)}",
                action="qc",
                step="validate_input",
                error_type="invalid_input",
            )
    try:
        report = inspect_subtitle_path(
            input_path,
            bilingual=args.bilingual,
            english_line=args.english_line,
            seam_times_ms=seam_times_ms,
            approved_cues=approved_cues,
            max_word_count_english=args.max_words_en,
            max_display_chars_english=args.max_display_chars_en,
        )
    except ApprovalValidationError as exc:
        raise SubtitleSkillError(
            str(exc),
            action="qc",
            step="validate_input",
            error_type="invalid_approval",
            suggested_fix=(
                "Remove stale approvals or update every cue/text entry to exactly match "
                "a currently approvable short-fragment finding."
            ),
        ) from exc
    except (UnicodeError, ValueError) as exc:
        raise SubtitleSkillError(
            f"Invalid SRT input: {exc}",
            action="qc",
            step="parse_input",
            error_type="invalid_srt",
            suggested_fix="Repair the malformed SRT block before running semantic-orphan QC.",
        ) from exc
    unresolved_failures = [
        failure
        for failure in seam_repair_failures
        if (failure["seam_index"], failure["seam_time_ms"]) not in resolved_seams
    ]
    add_seam_failures_to_report(report, unresolved_failures)
    if resolved_seams:
        report["resolved_seam_failures"] = [
            {
                "seam_index": seam_index,
                "seam_time_ms": seam_time_ms,
                "reason": reason,
            }
            for (seam_index, seam_time_ms), reason in sorted(resolved_seams.items())
        ]
    try:
        write_json_atomic(output_path, report)
    except (OSError, UnicodeError, ValueError) as exc:
        raise SubtitleSkillError(
            f"Could not write QC report: {exc}",
            action="qc",
            step="write_report",
            error_type="report_write_failure",
            suggested_fix="Choose a writable JSON output path whose parent is a directory.",
            details={"output_path": str(output_path)},
        ) from exc
    report["qc_path"] = str(output_path)
    return report


def read_text_inputs(args: argparse.Namespace, inline_attr: str, file_attr: str) -> str:
    parts = []
    inline_value = getattr(args, inline_attr, None)
    file_value = getattr(args, file_attr, None)
    if inline_value:
        parts.append(inline_value)
    if file_value:
        parts.append(Path(file_value).read_text(encoding="utf-8"))
    return "\n\n".join(part.strip() for part in parts if part and part.strip())


def run_optimize(args: argparse.Namespace) -> Dict[str, Any]:
    output_dir = Path(args.output_dir).resolve()
    input_path = Path(args.input).resolve()
    if not input_path.exists():
        raise SubtitleSkillError(f"Input SRT not found: {input_path}", action="optimize", step="validate_input", error_type="missing_input")

    work_dir = get_work_dir(output_dir)
    require_strict_srt_input(input_path, "optimize")
    base_name = args.output_base or f"{input_path.stem}_optimized"
    validate_output_pair_preflight(
        output_paths(output_dir, base_name),
        action="optimize",
        replace_existing=args.replace_existing,
        protected_paths=(input_path,),
    )
    optimized = optimize_subtitle(
        str(input_path),
        model=llm_model(args),
        custom_prompt=read_text_inputs(args, "reference", "reference_file"),
        api_key=require_llm_api_key(args, "optimize"),
        base_url=llm_base_url(args),
        thread_num=args.threads,
        batch_num=args.batch_size,
    )
    require_valid_asr_timeline(optimized, "optimize")
    require_valid_srt_roundtrip(optimized, "optimize")
    intended_paths = output_paths(output_dir, base_name)
    with output_pair_lock(intended_paths, "optimize"):
        work_json = work_json_output_path(
            optimized, work_dir, base_name, "optimize"
        )
        with rollback_artifacts_on_error([work_json], "optimize"):
            save_work_json(optimized, work_dir, base_name, "optimize")
            outputs = _save_main_outputs_unlocked(
                optimized,
                output_dir,
                base_name,
                action="optimize",
                replace_existing=args.replace_existing,
                protected_paths=(input_path,),
            )
    return {
        "ok": True,
        "action": "optimize",
        "outputs": {key: str(value) for key, value in outputs.items()},
        "work_dir": str(work_dir),
        "work_json": str(work_json),
    }


def run_translate(args: argparse.Namespace) -> Dict[str, Any]:
    output_dir = Path(args.output_dir).resolve()
    input_path = Path(args.input).resolve()
    if not input_path.exists():
        raise SubtitleSkillError(f"Input SRT not found: {input_path}", action="translate", step="validate_input", error_type="missing_input")

    work_dir = get_work_dir(output_dir)
    require_strict_srt_input(input_path, "translate")
    base_name = args.output_base or f"{input_path.stem}_{sanitize_filename(args.target_language)}"
    validate_output_pair_preflight(
        output_paths(output_dir, base_name),
        action="translate",
        replace_existing=args.replace_existing,
        protected_paths=(input_path,),
    )
    translated = translate_subtitle(
        str(input_path),
        target_language=args.target_language,
        is_reflect=args.reflect,
        model=llm_model(args),
        custom_prompt=read_text_inputs(args, "description", "description_file"),
        api_key=require_llm_api_key(args, "translate"),
        base_url=llm_base_url(args),
        thread_num=args.threads,
        batch_num=args.batch_size,
    )
    require_valid_asr_timeline(translated, "translate")
    require_valid_srt_roundtrip(translated, "translate")
    intended_paths = output_paths(output_dir, base_name)
    with output_pair_lock(intended_paths, "translate"):
        work_json = work_json_output_path(
            translated, work_dir, base_name, "translate"
        )
        with rollback_artifacts_on_error([work_json], "translate"):
            save_work_json(translated, work_dir, base_name, "translate")
            outputs = _save_main_outputs_unlocked(
                translated,
                output_dir,
                base_name,
                subtitle_format=args.subtitle_format,
                action="translate",
                replace_existing=args.replace_existing,
                protected_paths=(input_path,),
            )
    return {
        "ok": True,
        "action": "translate",
        "outputs": {key: str(value) for key, value in outputs.items()},
        "work_dir": str(work_dir),
        "work_json": str(work_json),
    }


def run_normalize(args: argparse.Namespace) -> Dict[str, Any]:
    output_dir = Path(args.output_dir).resolve()
    input_path = Path(args.input).resolve()
    if not input_path.exists():
        raise SubtitleSkillError(f"Input SRT not found: {input_path}", action="normalize", step="validate_input", error_type="missing_input")

    work_dir = get_work_dir(output_dir)
    asr_data = require_strict_srt_input(input_path, "normalize")
    base_name = args.output_base or input_path.stem
    validate_output_pair_preflight(
        output_paths(output_dir, base_name),
        action="normalize",
        replace_existing=args.replace_existing,
        protected_paths=(input_path,),
    )
    intended_paths = output_paths(output_dir, base_name)
    with output_pair_lock(intended_paths, "normalize"):
        source_copy = work_dir / work_artifact_filename(
            f"{input_path.stem}-{sha256_bytes(input_path.read_bytes())[:12]}",
            ".source.srt",
        )
        work_json = work_json_output_path(
            asr_data, work_dir, base_name, "normalize"
        )
        with rollback_artifacts_on_error(
            [source_copy, work_json], "normalize"
        ):
            copy_file_atomic(input_path, source_copy)
            save_work_json(asr_data, work_dir, base_name, "normalize")
            outputs = _save_main_outputs_unlocked(
                asr_data,
                output_dir,
                base_name,
                action="normalize",
                replace_existing=args.replace_existing,
                protected_paths=(input_path,),
            )
    return {
        "ok": True,
        "action": "normalize",
        "outputs": {key: str(value) for key, value in outputs.items()},
        "work_dir": str(work_dir),
        "work_json": str(work_json),
    }


class StructuredArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        action = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else "unknown"
        print_result(
            {
                "ok": False,
                "action": action,
                "step": "parse_arguments",
                "error_type": "invalid_arguments",
                "message": message,
                "suggested_fix": f"Run '{self.prog} --help' for usage.",
            }
        )
        raise SystemExit(1)


def build_parser() -> argparse.ArgumentParser:
    parser = StructuredArgumentParser(description="Generate and process subtitles with standard SRT/TXT outputs.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    transcribe = subparsers.add_parser("transcribe", help="Generate SRT/TXT from a local media file or video URL.")
    transcribe.add_argument("input", help="Local audio/video path or video URL.")
    transcribe.add_argument("--output-dir", "-o", default="subtitles", help="Directory for final SRT/TXT outputs.")
    transcribe.add_argument("--model", default=os.getenv("SUBTITLE_WHISPER_MODEL", DEFAULT_MODEL_NAME), help="faster-whisper model name or local model path.")
    transcribe.add_argument("--device", default=os.getenv("SUBTITLE_WHISPER_DEVICE", "auto"), help="faster-whisper device: auto, cuda, cpu.")
    transcribe.add_argument("--compute-type", default=os.getenv("SUBTITLE_WHISPER_COMPUTE_TYPE", "auto"), help="faster-whisper compute type: auto, float16, int8, etc.")
    transcribe.add_argument("--language", "-l", default=None, help="Optional language hint such as en, zh, ja.")
    transcribe.add_argument("--require-language", help="Reject reusable subtitles or ASR results that do not match this source language, such as en.")
    transcribe.add_argument("--force-asr", action="store_true", help="Ignore reusable YouTube manual subtitles and run ASR.")
    transcribe.add_argument("--replace-existing", action="store_true", help="Archive and replace an existing SRT/TXT output pair.")
    transcribe.add_argument("--start-seconds", type=float, help="Start of a targeted ASR interval; requires --end-seconds.")
    transcribe.add_argument("--end-seconds", type=float, help="End of a targeted ASR interval; requires --start-seconds.")
    transcribe.add_argument("--no-vad", action="store_true", help="Disable VAD for a targeted interval; not allowed for full-media transcription.")
    transcribe.add_argument("--semantic-split", action="store_true", help="Run LLM semantic subtitle segmentation after ASR. Default is off.")
    transcribe.add_argument("--split-model", default=os.getenv("SUBTITLE_LLM_MODEL", DEFAULT_LLM_MODEL), help="LLM model for semantic splitting.")
    transcribe.add_argument("--split-max-chars-cjk", type=positive_int, default=DEFAULT_MAX_WORD_COUNT_CJK)
    transcribe.add_argument("--split-max-words-en", type=positive_int, default=DEFAULT_MAX_WORD_COUNT_ENGLISH)
    transcribe.add_argument(
        "--split-max-chars-en",
        type=positive_int,
        default=DEFAULT_MAX_DISPLAY_CHARS_ENGLISH,
        help="English on-screen character budget at 1080p FontSize 16. 80 characters already wrap.",
    )
    transcribe.add_argument("--split-chunk-word-limit", type=positive_int, default=350)
    transcribe.add_argument("--split-max-retries", type=positive_int, default=2)
    transcribe.add_argument("--api-key", help="LLM API key for semantic split when enabled.")
    transcribe.add_argument("--base-url", help="LLM API base URL for semantic split when enabled.")
    transcribe.set_defaults(func=run_transcribe)

    split = subparsers.add_parser("split", help="Apply LLM semantic segmentation to raw Whisper JSON.")
    split.add_argument("input", help="Raw Whisper JSON with word timestamps.")
    split.add_argument("--output-dir", "-o", default="subtitles")
    split.add_argument("--output-base", help="Base filename for final SRT/TXT outputs.")
    split.add_argument("--replace-existing", action="store_true", help="Archive and replace an existing SRT/TXT output pair.")
    split.add_argument("--split-model", default=os.getenv("SUBTITLE_LLM_MODEL", DEFAULT_LLM_MODEL))
    split.add_argument("--split-max-chars-cjk", type=positive_int, default=DEFAULT_MAX_WORD_COUNT_CJK)
    split.add_argument("--split-max-words-en", type=positive_int, default=DEFAULT_MAX_WORD_COUNT_ENGLISH)
    split.add_argument(
        "--split-max-chars-en",
        type=positive_int,
        default=DEFAULT_MAX_DISPLAY_CHARS_ENGLISH,
        help="English on-screen character budget at 1080p FontSize 16. 80 characters already wrap.",
    )
    split.add_argument("--split-chunk-word-limit", type=positive_int, default=350)
    split.add_argument("--split-max-retries", type=positive_int, default=2)
    split.add_argument("--api-key", help="LLM API key.")
    split.add_argument("--base-url", help="LLM API base URL.")
    split.set_defaults(func=run_split)

    normalize = subparsers.add_parser("normalize", help="Normalize an existing SRT and export standard SRT/TXT.")
    normalize.add_argument("input", help="Input SRT file.")
    normalize.add_argument("--output-dir", "-o", default="subtitles")
    normalize.add_argument("--output-base", help="Base filename for final SRT/TXT outputs.")
    normalize.add_argument("--replace-existing", action="store_true", help="Archive and replace an existing SRT/TXT output pair.")
    normalize.set_defaults(func=run_normalize)

    optimize = subparsers.add_parser("optimize", help="Correct recognition errors in an existing SRT using an LLM.")
    optimize.add_argument("input", help="Input SRT file.")
    optimize.add_argument("--output-dir", "-o", default="subtitles")
    optimize.add_argument("--output-base", help="Base filename for final SRT/TXT outputs.")
    optimize.add_argument("--replace-existing", action="store_true", help="Archive and replace an existing SRT/TXT output pair.")
    optimize.add_argument("--reference", help="Inline reference evidence such as terminology, source notes, title, channel, or raw video description. Not task or style instructions.")
    optimize.add_argument("--reference-file", help="Text file with reference evidence such as terminology, source notes, title, channel, or raw video description. Not task or style instructions.")
    optimize.add_argument("--model", help="LLM model.")
    optimize.add_argument("--api-key", help="LLM API key.")
    optimize.add_argument("--base-url", help="LLM API base URL.")
    optimize.add_argument("--threads", type=int, default=5)
    optimize.add_argument("--batch-size", type=int, default=10)
    optimize.set_defaults(func=run_optimize)

    translate = subparsers.add_parser("translate", help="Translate an existing SRT using an LLM.")
    translate.add_argument("input", help="Input SRT file.")
    translate.add_argument("--target-language", required=True, help="Target language, such as zh-Hans, ja, en.")
    translate.add_argument("--output-dir", "-o", default="subtitles")
    translate.add_argument("--output-base", help="Base filename for final SRT/TXT outputs.")
    translate.add_argument("--replace-existing", action="store_true", help="Archive and replace an existing SRT/TXT output pair.")
    translate.add_argument("--description", help="Inline reference information, terminology, translation requirements, or style guidance.")
    translate.add_argument("--description-file", help="Text file with reference information, terminology, translation requirements, or style guidance.")
    translate.add_argument("--reflect", action="store_true", help="Use reflective two-step translation.")
    translate.add_argument("--subtitle-format", choices=["bilingual-trans-first", "bilingual-source-first", "translation-only"], default="bilingual-trans-first")
    translate.add_argument("--model", help="LLM model.")
    translate.add_argument("--api-key", help="LLM API key.")
    translate.add_argument("--base-url", help="LLM API base URL.")
    translate.add_argument("--threads", type=int, default=5)
    translate.add_argument("--batch-size", type=int, default=10)
    translate.set_defaults(func=run_translate)

    qc = subparsers.add_parser(
        "qc",
        help="Flag semantic orphan cues for review without merging them.",
    )
    qc.add_argument("input", help="Input SRT file.")
    qc.add_argument(
        "--output",
        "-o",
        help=(
            "Write the JSON report here. Defaults to "
            "<input-dir>/_subtitle_work/<input-stem>-<stable-digest>"
            ".semantic-orphan-qc.json, or beside the input when it is already "
            "inside _subtitle_work."
        ),
    )
    qc.add_argument(
        "--bilingual",
        action="store_true",
        help="Inspect the English line of a Chinese-English cue. Default English line is last.",
    )
    qc.add_argument(
        "--english-line",
        choices=["last", "first"],
        default="last",
        help="Which side of a bilingual cue contains the English source lines.",
    )
    qc.add_argument(
        "--seam-times-file",
        help="JSON file with seam_times_ms from semantic split, used to flag chunk-seam fragments.",
    )
    qc.add_argument(
        "--approved-cues-file",
        help=(
            "Reviewed JSON with exact cue/text/reason entries for complete short utterances "
            "or ambiguous dependent attachments. "
            "Every entry must match a current approvable cue; stale entries are rejected. "
            "Approvals cannot waive mechanically proven dependent tails, hanging words, "
            "lowercase continuations, or overlong display lines."
        ),
    )
    qc.add_argument(
        "--resolved-seams-file",
        help=(
            "Reviewed JSON with seam_index, seam_time_ms, and reason entries that explicitly "
            "resolve failures inherited from --seam-times-file."
        ),
    )
    qc.add_argument(
        "--max-words-en",
        type=positive_int,
        default=DEFAULT_MAX_WORD_COUNT_ENGLISH,
        help="English word budget used to recognize length wraps. Default matches semantic split.",
    )
    qc.add_argument(
        "--max-display-chars-en",
        type=positive_int,
        default=DEFAULT_MAX_DISPLAY_CHARS_ENGLISH,
        help="English on-screen character budget at 1080p FontSize 16. Longer lines wrap and cannot pass QC.",
    )
    qc.set_defaults(func=run_qc)

    return parser


def main() -> None:
    load_local_llm_config()
    parser = build_parser()
    args = parser.parse_args()
    try:
        result = args.func(args)
        print_result(console_result(result))
        raise SystemExit(int(result.get("exit_code", 0)))
    except SubtitleSkillError as exc:
        payload = {
            "ok": False,
            "action": exc.action,
            "step": exc.step,
            "error_type": exc.error_type,
            "message": str(exc),
            "suggested_fix": exc.suggested_fix,
        }
        payload.update(exc.details)
        print_result(payload)
        raise SystemExit(1) from exc
    except Exception as exc:
        print_result(
            {
                "ok": False,
                "action": getattr(args, "command", "unknown"),
                "step": "execute",
                "error_type": "unexpected_error",
                "message": str(exc),
            }
        )
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
