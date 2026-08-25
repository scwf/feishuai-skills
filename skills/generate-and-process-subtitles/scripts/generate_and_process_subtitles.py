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
DEFAULT_MODEL_NAME = "large-v2"

if str(SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILL_ROOT))

from subtitle_tools import ApprovalValidationError, ASRData, inspect_subtitle_path, optimize_subtitle, process_media, split_subtitle, translate_subtitle, validate_asr_timeline  # noqa: E402
from subtitle_tools.qc import DEFAULT_MAX_DISPLAY_CHARS_ENGLISH, DEFAULT_MAX_WORD_COUNT_ENGLISH, inspect_asr_data, normalize_seam_times, parse_srt_strict  # noqa: E402
from subtitle_tools.split import DEFAULT_MAX_WORD_COUNT_CJK, SubtitleSplitValidationError  # noqa: E402
from subtitle_tools.local_config import load_local_llm_config  # noqa: E402
from subtitle_tools.llm_runtime import DEFAULT_LLM_MODEL, llm_base_url, llm_model, require_llm_api_key  # noqa: E402
from subtitle_tools.cli_parser import build_parser as build_cli_parser  # noqa: E402
from subtitle_tools.transcribe_command import (  # noqa: E402
    download_manual_subtitles,
    fetch_video_metadata,
    is_url,
    is_youtube_url,
    language_matches,
    pick_subtitle_language,
    resolve_clip_timestamps,
    run_transcribe,
    targeted_repair_base_name,
    write_youtube_context,
)
from subtitle_tools.qc_command import (  # noqa: E402
    add_seam_failures_to_report,
    load_approved_cues_file,
    load_resolved_seams_file,
    load_seam_artifact,
    load_seam_times_file,
    run_qc,
    write_qc_report,
)
from subtitle_tools.publishing import (  # noqa: E402
    MAX_QC_STEM_UTF8_BYTES,
    QC_REPORT_SUFFIX,
    WORK_DIR_NAME,
    SubtitleSkillError,
    _save_main_outputs_unlocked,
    _save_repair_outputs_unlocked,
    component_safe_base_name,
    copy_file_atomic,
    default_qc_output_path,
    file_identity,
    get_work_dir,
    metadata_output_path,
    nested_qc_output_paths,
    output_pair_lock,
    output_paths,
    promote_temp_file,
    qc_report_filename,
    require_strict_srt_input,
    require_valid_asr_timeline,
    require_valid_srt_roundtrip,
    rollback_artifacts_on_error,
    sanitize_filename,
    save_main_outputs,
    save_repair_outputs,
    save_work_json,
    serialized_srt_sha256,
    sha256_bytes,
    unlink_with_retries,
    validate_main_outputs,
    validate_output_pair_preflight,
    work_artifact_filename,
    work_json_output_path,
    wrap_split_validation_error,
    write_bytes_atomic,
    write_json_atomic,
)


def positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive integer") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


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
    split_progress: Dict[str, Any] = {}
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
            llm_timeout_seconds=args.llm_timeout_seconds,
            seam_times_out=seam_times_ms,
            seam_failures_out=seam_repair_failures,
            checkpoint_dir=work_dir,
            progress_state_out=split_progress,
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
        "semantic_split_progress": split_progress,
    }
    payload.update(qc_fields)
    return payload


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
    return build_cli_parser(
        StructuredArgumentParser,
        {
            "transcribe": run_transcribe,
            "split": run_split,
            "normalize": run_normalize,
            "optimize": run_optimize,
            "translate": run_translate,
            "qc": run_qc,
        },
        positive_int,
        default_model_name=DEFAULT_MODEL_NAME,
        default_llm_model=DEFAULT_LLM_MODEL,
    )

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
