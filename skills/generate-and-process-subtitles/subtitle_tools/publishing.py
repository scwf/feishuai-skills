"""Transactional subtitle artifact paths, validation, locking, and publication."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import time
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, BinaryIO, Dict, Iterator, Optional

from .data import ASRData
from .pathing import UnsafeLockPathError, file_identity, open_safe_lock_file
from .qc import parse_srt_strict, validate_asr_timeline

WORK_DIR_NAME = "_subtitle_work"
QC_REPORT_SUFFIX = ".semantic-orphan-qc.json"
MAX_QC_STEM_UTF8_BYTES = 180
ATOMIC_REPLACE_RETRIES = 8
ATOMIC_REPLACE_DELAY_SECONDS = 0.01


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


def json_payload_bytes(payload: Dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")


def write_immutable_json_atomic(
    path: Path, payload: Dict[str, Any], *, action: str
) -> None:
    expected = json_payload_bytes(payload)
    if path.exists():
        if not path.is_file() or path.read_bytes() != expected:
            raise SubtitleSkillError(
                f"Immutable JSON evidence conflicts with existing content: {path}",
                action=action,
                step="write_evidence",
                error_type="evidence_collision",
                suggested_fix="Preserve the conflicting evidence and use a distinct output directory.",
            )
        return
    write_bytes_atomic(path, expected)


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
    try:
        handle = open_safe_lock_file(lock_path)
    except (OSError, UnsafeLockPathError) as exc:
        raise SubtitleSkillError(
            "The subtitle output lock path is not a safe single-link regular file.",
            action=action,
            step="validate_output",
            error_type="unsafe_lock_path",
            suggested_fix="Remove or quarantine the unsafe lock path, then retry.",
            details={"lock_path": str(lock_path)},
        ) from exc
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
            except Exception:
                # Closing the handle releases the OS lock; an explicit unlock
                # failure must not turn an already committed SRT into failure.
                pass
    finally:
        try:
            handle.close()
        except Exception:
            pass


def promote_temp_file(source: Path, target: Path) -> None:
    source.replace(target)


def restore_archived_pair_member(
    archive: Path, target: Path, expected_hash: str
) -> None:
    if not archive.exists():
        raise FileNotFoundError(f"expected archive is missing: {archive}")
    temporary = target.parent / f".restore-{target.name}-{uuid.uuid4().hex}.tmp"
    try:
        shutil.copy2(archive, temporary)
        candidate_hash = sha256_bytes(temporary.read_bytes())
        if candidate_hash != expected_hash:
            raise OSError(
                f"archive digest mismatch before restore: {archive}; "
                f"expected {expected_hash}, got {candidate_hash}"
            )
        temporary.replace(target)
        if not target.is_file():
            raise OSError(f"restored canonical output is missing: {target}")
        restored_hash = sha256_bytes(target.read_bytes())
        if restored_hash != expected_hash:
            raise OSError(
                f"restored output digest mismatch: {target}; "
                f"expected {expected_hash}, got {restored_hash}"
            )
    finally:
        temporary.unlink(missing_ok=True)


def archive_evidence_paths(archived: Dict[str, Path]) -> Dict[str, Optional[str]]:
    return {
        key: (
            str(path.resolve())
            if path.exists() and is_regular_output_target(path)
            else None
        )
        for key, path in archived.items()
    }


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
    archived_hashes: Dict[str, str] = {}
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
                    previous_hash = sha256_bytes(path.read_bytes())
                    archive_base = component_safe_base_name(
                        f"{path.stem}.previous-{stamp}"
                    )
                    archive = archive_dir / f"{archive_base}{path.suffix}"
                    path.replace(archive)
                    archived[key] = archive
                    archived_hashes[key] = previous_hash

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
                restore_archived_pair_member(
                    archive, paths[key], archived_hashes[key]
                )
            except (OSError, ValueError) as exc:
                rollback_errors.append(f"{key}: {exc}")
        for key, path in paths.items():
            if key in archived or path not in promoted:
                continue
            try:
                unlink_with_retries(path)
            except OSError as exc:
                rollback_errors.append(f"{key}: {exc}")
        if rollback_errors:
            archive_evidence = archive_evidence_paths(archived)
            raise SubtitleSkillError(
                "Output pair promotion failed and rollback was incomplete: "
                + "; ".join(rollback_errors),
                action=action,
                step="rollback_output",
                error_type="rollback_failure",
                suggested_fix="Recover the archived pair under _subtitle_work/archive before retrying.",
                details={
                    "archived_outputs": archive_evidence,
                    "unavailable_archives": sorted(
                        key for key, path in archive_evidence.items() if path is None
                    ),
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
            details={"archived_outputs": archive_evidence_paths(archived)},
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


def metadata_output_path(
    work_dir: Path,
    base_name: str,
    source_srt_hash: str,
    evidence_hash: Optional[str] = None,
) -> Path:
    evidence_suffix = f"-{evidence_hash[:12]}" if evidence_hash else ""
    return work_dir / work_artifact_filename(
        f"{base_name}-{source_srt_hash[:12]}{evidence_suffix}", ".metadata.json"
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
