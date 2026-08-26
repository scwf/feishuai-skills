"""Transcription source selection, language gates, and bounded repair orchestration."""

from __future__ import annotations

import argparse
import math
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import parse_qs, urlparse

from .asr.faster_whisper import TimestampRepairLimitError
from .config import (
    DEFAULT_MAX_PACKED_CLUSTER_SIZE,
    DEFAULT_MAX_PACKED_WORD_REPAIRS_PER_10K,
)
from .core import process_media
from .llm_runtime import llm_base_url, require_llm_api_key
from .publishing import (
    SubtitleSkillError,
    _save_main_outputs_unlocked,
    _save_repair_outputs_unlocked,
    component_safe_base_name,
    get_work_dir,
    json_payload_bytes,
    metadata_output_path,
    nested_qc_output_paths,
    output_pair_lock,
    output_paths,
    require_strict_srt_input,
    require_valid_asr_timeline,
    require_valid_srt_roundtrip,
    rollback_artifacts_on_error,
    sanitize_filename,
    save_work_json,
    serialized_srt_sha256,
    sha256_bytes,
    validate_output_pair_preflight,
    work_json_output_path,
    wrap_split_validation_error,
    write_bytes_atomic,
    write_immutable_json_atomic,
)
from .qc_command import write_qc_report
from .split import SubtitleSplitValidationError

MIN_ASR_LANGUAGE_PROBABILITY = 0.5


def is_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def is_youtube_url(value: str) -> bool:
    host = (urlparse(value).netloc or "").lower()
    return "youtube.com" in host or "youtu.be" in host


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
    if not metadata or not (metadata.get("description") or "").strip():
        return None

    parts = [
        f"Title: {metadata.get('title') or ''}".rstrip(),
        f"Channel: {metadata.get('channel') or ''}".rstrip(),
        "Description:",
        metadata.get("description", "").strip(),
    ]
    context_bytes = ("\n".join(parts).strip() + "\n").encode("utf-8")
    context_digest = sha256_bytes(context_bytes)
    video_id = sanitize_filename(str(metadata.get("id") or "video"), "video")
    context_base = component_safe_base_name(f"context-{video_id}-{context_digest[:16]}")
    context_path = work_dir / f"{context_base}.txt"
    if context_path.exists():
        if not context_path.is_file() or context_path.read_bytes() != context_bytes:
            raise SubtitleSkillError(
                f"Immutable YouTube context path does not match its content digest: {context_path}",
                action="transcribe",
                step="write_context",
                error_type="context_evidence_mismatch",
                suggested_fix="Preserve the conflicting context file and use a clean output directory.",
            )
    else:
        write_bytes_atomic(context_path, context_bytes)
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


def validate_transcribe_request(
    args: argparse.Namespace,
    input_path: Path,
    input_is_file: bool,
    input_is_url: bool,
) -> tuple[Optional[list[float]], bool]:
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
    return clip_timestamps, effective_vad_filter


def initial_transcribe_metadata(
    args: argparse.Namespace,
    *,
    effective_vad_filter: bool,
    clip_timestamps: Optional[list[float]],
    video_metadata: Optional[Dict[str, Any]],
    context_path: Optional[Path],
) -> Dict[str, Any]:
    metadata: Dict[str, Any] = {
        "input": args.input,
        "model": args.model,
        "device": args.device,
        "compute_type": args.compute_type,
        "requested_vad_filter": not args.no_vad,
        "effective_vad_filter": effective_vad_filter,
        "clip_timestamps": clip_timestamps,
        "max_packed_word_repairs_per_10k": getattr(
            args,
            "max_packed_word_repairs_per_10k",
            DEFAULT_MAX_PACKED_WORD_REPAIRS_PER_10K,
        ),
        "max_packed_cluster_size": getattr(
            args, "max_packed_cluster_size", DEFAULT_MAX_PACKED_CLUSTER_SIZE
        ),
        "semantic_split": bool(args.semantic_split),
        "used_manual_subtitles": False,
    }
    if video_metadata is not None:
        metadata["video_metadata"] = video_metadata
    if context_path is not None:
        metadata["context_file"] = str(context_path)
        metadata["context_sha256"] = sha256_bytes(context_path.read_bytes())
    return metadata


def try_manual_subtitles(
    args: argparse.Namespace,
    *,
    output_dir: Path,
    work_dir: Path,
    video_metadata: Optional[Dict[str, Any]],
    metadata: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    if args.force_asr or args.semantic_split or not is_youtube_url(args.input):
        return None

    required_language = args.require_language
    manual_srt, video_metadata, selected_language = download_manual_subtitles(
        args.input,
        work_dir,
        required_language or args.language,
        video_metadata,
    )
    metadata["manual_subtitle_language"] = selected_language
    if manual_srt is None:
        return None

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
        work_json = work_json_output_path(asr_data, work_dir, base_name, "manual-subtitles")
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
            sha256_bytes(json_payload_bytes(metadata)),
        )
        with rollback_artifacts_on_error([work_json, metadata_path], "transcribe"):
            save_work_json(asr_data, work_dir, base_name, "manual-subtitles")
            write_immutable_json_atomic(metadata_path, metadata, action="transcribe")
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


def transcribe_base_name(
    args: argparse.Namespace,
    input_path: Path,
    input_is_file: bool,
    clip_timestamps: Optional[list[float]],
) -> str:
    if input_is_file:
        base_name = input_path.stem
    else:
        parsed = urlparse(args.input)
        base_name = parse_qs(parsed.query).get("v", [""])[0] or Path(parsed.path).stem or "subtitles"
    if clip_timestamps is not None:
        return targeted_repair_base_name(base_name, clip_timestamps)
    return base_name


def run_asr(
    args: argparse.Namespace,
    *,
    work_dir: Path,
    effective_vad_filter: bool,
    clip_timestamps: Optional[list[float]],
) -> tuple[ASRData, Dict[str, Any], list[int], list[Dict[str, Any]]]:
    split_api_key = require_llm_api_key(args, "transcribe") if args.semantic_split else None
    split_base_url = llm_base_url(args) if args.semantic_split else None
    seam_times_ms: list[int] = []
    seam_repair_failures: list[Dict[str, Any]] = []
    asr_metadata: Dict[str, Any] = {}
    split_progress: Dict[str, Any] = {}
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
            max_packed_word_repairs_per_10k=getattr(
                args,
                "max_packed_word_repairs_per_10k",
                DEFAULT_MAX_PACKED_WORD_REPAIRS_PER_10K,
            ),
            max_packed_cluster_size=getattr(
                args, "max_packed_cluster_size", DEFAULT_MAX_PACKED_CLUSTER_SIZE
            ),
            split_enabled=args.semantic_split,
            split_model=args.split_model,
            split_max_chars_cjk=args.split_max_chars_cjk,
            split_max_words_en=args.split_max_words_en,
            split_max_chars_en=args.split_max_chars_en,
            split_chunk_word_limit=args.split_chunk_word_limit,
            split_max_retries=args.split_max_retries,
            llm_timeout_seconds=args.llm_timeout_seconds,
            api_key=split_api_key,
            base_url=split_base_url,
            seam_times_out=seam_times_ms if args.semantic_split else None,
            seam_failures_out=seam_repair_failures if args.semantic_split else None,
            asr_metadata_out=asr_metadata,
            split_checkpoint_dir=str(work_dir) if args.semantic_split else None,
            split_progress_out=split_progress if args.semantic_split else None,
        )
    except TimestampRepairLimitError as exc:
        raise SubtitleSkillError(
            str(exc),
            action="transcribe",
            step="repair_word_timestamps",
            error_type="timestamp_repair_blocked",
            suggested_fix=(
                "Inspect the raw ASR JSON and repair summary. Change a safety limit only "
                "after confirming the timestamp collapse is local rather than a broader alignment failure."
            ),
            details={
                "raw_asr_json": str(exc.raw_asr_path),
                "raw_asr_hash_algorithm": "sha256",
                "raw_asr_sha256": exc.raw_asr_sha256,
                "timestamp_repair_summary": exc.repair_summary,
            },
        ) from exc
    except SubtitleSplitValidationError as exc:
        raise wrap_split_validation_error(exc, "transcribe") from exc
    require_valid_asr_timeline(asr_data, "transcribe")
    require_valid_srt_roundtrip(asr_data, "transcribe")
    if split_progress:
        asr_metadata["semantic_split_progress"] = split_progress
    return asr_data, asr_metadata, seam_times_ms, seam_repair_failures


def validate_asr_source_language(
    args: argparse.Namespace, asr_metadata: Dict[str, Any]
) -> tuple[Optional[str], Any]:
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
    return detected_language, language_probability


def publish_asr_transcription(
    args: argparse.Namespace,
    *,
    asr_data: ASRData,
    metadata: Dict[str, Any],
    asr_metadata: Dict[str, Any],
    seam_times_ms: list[int],
    seam_repair_failures: list[Dict[str, Any]],
    output_dir: Path,
    work_dir: Path,
    base_name: str,
    intended_paths: Dict[str, Path],
    protected: tuple[Path, ...],
    clip_timestamps: Optional[list[float]],
) -> Dict[str, Any]:
    detected_language, language_probability = validate_asr_source_language(args, asr_metadata)
    with output_pair_lock(intended_paths, "transcribe"):
        work_json = work_json_output_path(asr_data, work_dir, base_name, "transcription")
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
        semantic_split_progress = asr_metadata.get("semantic_split_progress")
        if semantic_split_progress:
            metadata["semantic_split_progress"] = semantic_split_progress
        if asr_metadata.get("raw_asr_json"):
            metadata["raw_asr_json"] = asr_metadata["raw_asr_json"]
            metadata["raw_asr_hash_algorithm"] = asr_metadata[
                "raw_asr_hash_algorithm"
            ]
            metadata["raw_asr_sha256"] = asr_metadata["raw_asr_sha256"]
        if asr_metadata.get("timestamp_repair_summary"):
            metadata["timestamp_repair_summary"] = asr_metadata[
                "timestamp_repair_summary"
            ]
        metadata_path = metadata_output_path(
            work_dir,
            base_name,
            str(metadata["source_srt_sha256"]),
            sha256_bytes(json_payload_bytes(metadata)),
        )
        qc_fields: Optional[Dict[str, Any]] = None
        artifact_paths = [work_json, metadata_path]
        if args.semantic_split:
            artifact_paths.extend(
                nested_qc_output_paths(asr_data, work_dir, base_name, include_seams=True)
            )
        with rollback_artifacts_on_error(artifact_paths, "transcribe"):
            save_work_json(asr_data, work_dir, base_name, "transcription")
            write_immutable_json_atomic(metadata_path, metadata, action="transcribe")
            if args.semantic_split:
                qc_fields = write_qc_report(
                    None,
                    work_dir,
                    base_name,
                    bilingual=False,
                    asr_data=asr_data,
                    source_path=str(intended_paths["srt"]),
                    seam_times_ms=seam_times_ms,
                    seam_repair_failures=seam_repair_failures,
                    max_word_count_english=args.split_max_words_en,
                    max_display_chars_english=args.split_max_chars_en,
                )
            if clip_timestamps is not None:
                outputs = _save_repair_outputs_unlocked(asr_data, output_dir, base_name)
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
    if asr_metadata.get("semantic_split_progress"):
        payload["semantic_split_progress"] = asr_metadata["semantic_split_progress"]
    if asr_metadata.get("raw_asr_json"):
        payload["raw_asr_json"] = asr_metadata["raw_asr_json"]
        payload["raw_asr_hash_algorithm"] = asr_metadata["raw_asr_hash_algorithm"]
        payload["raw_asr_sha256"] = asr_metadata["raw_asr_sha256"]
    if asr_metadata.get("timestamp_repair_summary"):
        payload["timestamp_repair_summary"] = asr_metadata[
            "timestamp_repair_summary"
        ]
    return payload


def run_transcribe(args: argparse.Namespace) -> Dict[str, Any]:
    output_dir = Path(args.output_dir).resolve()
    input_path = Path(args.input)
    input_is_file = input_path.exists()
    input_is_url = is_url(args.input)
    clip_timestamps, effective_vad_filter = validate_transcribe_request(
        args, input_path, input_is_file, input_is_url
    )

    work_dir = get_work_dir(output_dir)
    video_metadata = fetch_video_metadata(args.input) if is_youtube_url(args.input) else None
    context_path = write_youtube_context(work_dir, video_metadata)
    metadata = initial_transcribe_metadata(
        args,
        effective_vad_filter=effective_vad_filter,
        clip_timestamps=clip_timestamps,
        video_metadata=video_metadata,
        context_path=context_path,
    )
    manual_result = try_manual_subtitles(
        args,
        output_dir=output_dir,
        work_dir=work_dir,
        video_metadata=video_metadata,
        metadata=metadata,
    )
    if manual_result is not None:
        return manual_result

    base_name = transcribe_base_name(args, input_path, input_is_file, clip_timestamps)
    if clip_timestamps is not None:
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

    asr_data, asr_metadata, seam_times_ms, seam_repair_failures = run_asr(
        args,
        work_dir=work_dir,
        effective_vad_filter=effective_vad_filter,
        clip_timestamps=clip_timestamps,
    )
    return publish_asr_transcription(
        args,
        asr_data=asr_data,
        metadata=metadata,
        asr_metadata=asr_metadata,
        seam_times_ms=seam_times_ms,
        seam_repair_failures=seam_repair_failures,
        output_dir=output_dir,
        work_dir=work_dir,
        base_name=base_name,
        intended_paths=intended_paths,
        protected=protected,
        clip_timestamps=clip_timestamps,
    )
