"""CLI orchestration for viewer-facing subtitle QC reports and review inputs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Optional

from .data import ASRData
from .pathing import file_identity
from .publishing import (
    SubtitleSkillError,
    default_qc_output_path,
    qc_report_filename,
    serialized_srt_sha256,
    work_artifact_filename,
    write_json_atomic,
)
from .qc import (
    ApprovalValidationError,
    DEFAULT_MAX_DISPLAY_CHARS_ENGLISH,
    DEFAULT_MAX_WORD_COUNT_ENGLISH,
    inspect_asr_data,
    inspect_subtitle_path,
    normalize_seam_times,
)


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


