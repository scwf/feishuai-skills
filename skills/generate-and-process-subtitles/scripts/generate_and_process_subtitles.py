#!/usr/bin/env python3
"""Cross-platform subtitle generation and processing CLI."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import parse_qs, urlparse


SKILL_ROOT = Path(__file__).resolve().parents[1]
WORK_DIR_NAME = "_subtitle_work"
DEFAULT_MODEL_NAME = "large-v2"
DEFAULT_LLM_MODEL = "deepseek-v4-flash"
DEFAULT_LLM_BASE_URL = "https://api.deepseek.com/v1"

if str(SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILL_ROOT))

from subtitle_tools import ASRData, optimize_subtitle, process_media, split_subtitle, translate_subtitle  # noqa: E402
from subtitle_tools.config import DEFAULT_LLM_BASE_URL as CONFIG_DEFAULT_LLM_BASE_URL  # noqa: E402
from subtitle_tools.local_config import LLM_CONFIG_PATH, load_local_llm_config  # noqa: E402


class SubtitleSkillError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        action: str,
        step: str,
        error_type: str,
        suggested_fix: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.action = action
        self.step = step
        self.error_type = error_type
        self.suggested_fix = suggested_fix


def sanitize_filename(value: str, fallback: str = "subtitles") -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", value).strip().rstrip(". ")
    return cleaned or fallback


def is_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def is_youtube_url(value: str) -> bool:
    host = (urlparse(value).netloc or "").lower()
    return "youtube.com" in host or "youtu.be" in host


def output_paths(output_dir: Path, base_name: str) -> Dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    safe_base = sanitize_filename(base_name)
    return {
        "srt": output_dir / f"{safe_base}.srt",
        "txt": output_dir / f"{safe_base}.txt",
    }


def get_work_dir(output_dir: Path) -> Path:
    work_dir = output_dir / WORK_DIR_NAME
    work_dir.mkdir(parents=True, exist_ok=True)
    return work_dir


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def save_main_outputs(asr_data: ASRData, output_dir: Path, base_name: str, *, subtitle_format: str = "bilingual-trans-first") -> Dict[str, Path]:
    paths = output_paths(output_dir, base_name)
    asr_data.save(str(paths["srt"]), subtitle_format=subtitle_format)
    asr_data.save(str(paths["txt"]), subtitle_format=subtitle_format)
    return paths


def save_work_json(asr_data: ASRData, work_dir: Path, base_name: str, suffix: str) -> Path:
    path = work_dir / f"{sanitize_filename(base_name)}.{suffix}.json"
    write_json(path, asr_data.to_json(include_words=True))
    return path


def validate_main_outputs(paths: Dict[str, Path], action: str) -> None:
    for key in ("srt", "txt"):
        path = paths[key]
        if not path.exists() or path.stat().st_size <= 0:
            raise SubtitleSkillError(
                f"Expected {key.upper()} output was not created: {path}",
                action=action,
                step="validate_output",
                error_type="missing_output",
            )
    if "-->" not in paths["srt"].read_text(encoding="utf-8"):
        raise SubtitleSkillError(
            f"Output does not look like SRT: {paths['srt']}",
            action=action,
            step="validate_output",
            error_type="invalid_srt",
        )


def print_result(payload: Dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


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

    work_dir = get_work_dir(output_dir)
    video_metadata = fetch_video_metadata(args.input) if is_youtube_url(args.input) else None
    context_path = write_youtube_context(work_dir, video_metadata)

    metadata: Dict[str, Any] = {
        "input": args.input,
        "model": args.model,
        "device": args.device,
        "compute_type": args.compute_type,
        "semantic_split": bool(args.semantic_split),
        "used_manual_subtitles": False,
    }
    if video_metadata is not None:
        metadata["video_metadata"] = video_metadata
    if context_path is not None:
        metadata["context_file"] = str(context_path)

    if not args.force_asr and is_youtube_url(args.input):
        manual_srt, video_metadata, selected_language = download_manual_subtitles(args.input, work_dir, args.language, video_metadata)
        metadata["manual_subtitle_language"] = selected_language
        if manual_srt is not None:
            asr_data = ASRData.from_srt(manual_srt.read_text(encoding="utf-8"))
            base_name = sanitize_filename((video_metadata or {}).get("title") or manual_srt.stem)
            outputs = save_main_outputs(asr_data, output_dir, base_name)
            work_json = save_work_json(asr_data, work_dir, base_name, "manual-subtitles")
            metadata.update({"used_manual_subtitles": True, "work_json": str(work_json)})
            metadata_path = work_dir / f"{sanitize_filename(base_name)}.metadata.json"
            write_json(metadata_path, metadata)
            validate_main_outputs(outputs, "transcribe")
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

    split_api_key = require_llm_api_key(args, "transcribe") if args.semantic_split else None
    split_base_url = llm_base_url(args) if args.semantic_split else None

    asr_data = process_media(
        args.input,
        str(work_dir),
        model_name=args.model,
        device=args.device,
        compute_type=args.compute_type,
        language=args.language,
        split_enabled=args.semantic_split,
        split_model=args.split_model,
        split_max_chars_cjk=args.split_max_chars_cjk,
        split_max_words_en=args.split_max_words_en,
        split_chunk_word_limit=args.split_chunk_word_limit,
        split_max_retries=args.split_max_retries,
        api_key=split_api_key,
        base_url=split_base_url,
    )
    outputs = save_main_outputs(asr_data, output_dir, base_name)
    work_json = save_work_json(asr_data, work_dir, base_name, "transcription")
    metadata.update({"work_json": str(work_json)})
    metadata_path = work_dir / f"{sanitize_filename(base_name)}.metadata.json"
    write_json(metadata_path, metadata)
    validate_main_outputs(outputs, "transcribe")
    return {
        "ok": True,
        "action": "transcribe",
        "outputs": {key: str(value) for key, value in outputs.items()},
        "work_dir": str(work_dir),
        "metadata": str(metadata_path),
    }


def run_split(args: argparse.Namespace) -> Dict[str, Any]:
    output_dir = Path(args.output_dir).resolve()
    input_path = Path(args.input).resolve()
    if not input_path.exists():
        raise SubtitleSkillError(f"Input JSON not found: {input_path}", action="split", step="validate_input", error_type="missing_input")

    work_dir = get_work_dir(output_dir)
    api_key = require_llm_api_key(args, "split")
    asr_data = ASRData.from_whisper_json(json.loads(input_path.read_text(encoding="utf-8")))
    split_data = split_subtitle(
        asr_data,
        model=args.split_model,
        api_key=api_key,
        base_url=llm_base_url(args),
        max_word_count_cjk=args.split_max_chars_cjk,
        max_word_count_english=args.split_max_words_en,
        chunk_word_limit=args.split_chunk_word_limit,
        max_retries=args.split_max_retries,
    )
    outputs = save_main_outputs(split_data, output_dir, args.output_base or input_path.stem)
    work_json = save_work_json(split_data, work_dir, args.output_base or input_path.stem, "semantic-split")
    validate_main_outputs(outputs, "split")
    return {
        "ok": True,
        "action": "split",
        "outputs": {key: str(value) for key, value in outputs.items()},
        "work_dir": str(work_dir),
        "work_json": str(work_json),
    }


def read_reference_text(args: argparse.Namespace) -> str:
    parts = []
    if getattr(args, "description", None):
        parts.append(args.description)
    if getattr(args, "description_file", None):
        parts.append(Path(args.description_file).read_text(encoding="utf-8"))
    return "\n\n".join(part.strip() for part in parts if part and part.strip())


def run_optimize(args: argparse.Namespace) -> Dict[str, Any]:
    output_dir = Path(args.output_dir).resolve()
    input_path = Path(args.input).resolve()
    if not input_path.exists():
        raise SubtitleSkillError(f"Input SRT not found: {input_path}", action="optimize", step="validate_input", error_type="missing_input")

    work_dir = get_work_dir(output_dir)
    optimized = optimize_subtitle(
        str(input_path),
        model=llm_model(args),
        custom_prompt=read_reference_text(args),
        api_key=require_llm_api_key(args, "optimize"),
        base_url=llm_base_url(args),
        thread_num=args.threads,
        batch_num=args.batch_size,
    )
    base_name = args.output_base or f"{input_path.stem}_optimized"
    outputs = save_main_outputs(optimized, output_dir, base_name)
    work_json = save_work_json(optimized, work_dir, base_name, "optimize")
    validate_main_outputs(outputs, "optimize")
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
    translated = translate_subtitle(
        str(input_path),
        target_language=args.target_language,
        is_reflect=args.reflect,
        model=llm_model(args),
        custom_prompt=read_reference_text(args),
        api_key=require_llm_api_key(args, "translate"),
        base_url=llm_base_url(args),
        thread_num=args.threads,
        batch_num=args.batch_size,
    )
    base_name = args.output_base or f"{input_path.stem}_{sanitize_filename(args.target_language)}"
    outputs = save_main_outputs(translated, output_dir, base_name, subtitle_format=args.subtitle_format)
    work_json = save_work_json(translated, work_dir, base_name, "translate")
    validate_main_outputs(outputs, "translate")
    return {
        "ok": True,
        "action": "translate",
        "outputs": {key: str(value) for key, value in outputs.items()},
        "work_dir": str(work_dir),
        "work_json": str(work_json),
    }


def run_clean(args: argparse.Namespace) -> Dict[str, Any]:
    output_dir = Path(args.output_dir).resolve()
    input_path = Path(args.input).resolve()
    if not input_path.exists():
        raise SubtitleSkillError(f"Input SRT not found: {input_path}", action="clean", step="validate_input", error_type="missing_input")

    work_dir = get_work_dir(output_dir)
    asr_data = ASRData.from_srt(input_path.read_text(encoding="utf-8"))
    base_name = args.output_base or input_path.stem
    outputs = save_main_outputs(asr_data, output_dir, base_name)
    shutil.copy2(input_path, work_dir / f"{sanitize_filename(input_path.stem)}.source.srt")
    work_json = save_work_json(asr_data, work_dir, base_name, "clean")
    validate_main_outputs(outputs, "clean")
    return {
        "ok": True,
        "action": "clean",
        "outputs": {key: str(value) for key, value in outputs.items()},
        "work_dir": str(work_dir),
        "work_json": str(work_json),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate and process subtitles with clean SRT/TXT outputs.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    transcribe = subparsers.add_parser("transcribe", help="Generate SRT/TXT from a local media file or video URL.")
    transcribe.add_argument("input", help="Local audio/video path or video URL.")
    transcribe.add_argument("--output-dir", "-o", default="subtitles", help="Directory for final SRT/TXT outputs.")
    transcribe.add_argument("--model", default=os.getenv("SUBTITLE_WHISPER_MODEL", DEFAULT_MODEL_NAME), help="faster-whisper model name or local model path.")
    transcribe.add_argument("--device", default=os.getenv("SUBTITLE_WHISPER_DEVICE", "auto"), help="faster-whisper device: auto, cuda, cpu.")
    transcribe.add_argument("--compute-type", default=os.getenv("SUBTITLE_WHISPER_COMPUTE_TYPE", "auto"), help="faster-whisper compute type: auto, float16, int8, etc.")
    transcribe.add_argument("--language", "-l", default=None, help="Optional language hint such as en, zh, ja.")
    transcribe.add_argument("--force-asr", action="store_true", help="Ignore reusable YouTube manual subtitles and run ASR.")
    transcribe.add_argument("--semantic-split", action="store_true", help="Run LLM semantic subtitle segmentation after ASR. Default is off.")
    transcribe.add_argument("--split-model", default=os.getenv("SUBTITLE_LLM_MODEL", DEFAULT_LLM_MODEL), help="LLM model for semantic splitting.")
    transcribe.add_argument("--split-max-chars-cjk", type=int, default=25)
    transcribe.add_argument("--split-max-words-en", type=int, default=21)
    transcribe.add_argument("--split-chunk-word-limit", type=int, default=350)
    transcribe.add_argument("--split-max-retries", type=int, default=2)
    transcribe.add_argument("--api-key", help="LLM API key for semantic split when enabled.")
    transcribe.add_argument("--base-url", help="LLM API base URL for semantic split when enabled.")
    transcribe.set_defaults(func=run_transcribe)

    split = subparsers.add_parser("split", help="Apply LLM semantic segmentation to raw Whisper JSON.")
    split.add_argument("input", help="Raw Whisper JSON with word timestamps.")
    split.add_argument("--output-dir", "-o", default="subtitles")
    split.add_argument("--output-base", help="Base filename for final SRT/TXT outputs.")
    split.add_argument("--split-model", default=os.getenv("SUBTITLE_LLM_MODEL", DEFAULT_LLM_MODEL))
    split.add_argument("--split-max-chars-cjk", type=int, default=25)
    split.add_argument("--split-max-words-en", type=int, default=21)
    split.add_argument("--split-chunk-word-limit", type=int, default=350)
    split.add_argument("--split-max-retries", type=int, default=2)
    split.add_argument("--api-key", help="LLM API key.")
    split.add_argument("--base-url", help="LLM API base URL.")
    split.set_defaults(func=run_split)

    clean = subparsers.add_parser("clean", help="Normalize an existing SRT and export clean SRT/TXT.")
    clean.add_argument("input", help="Input SRT file.")
    clean.add_argument("--output-dir", "-o", default="subtitles")
    clean.add_argument("--output-base", help="Base filename for final SRT/TXT outputs.")
    clean.set_defaults(func=run_clean)

    optimize = subparsers.add_parser("optimize", help="Clean recognition errors in an existing SRT using an LLM.")
    optimize.add_argument("input", help="Input SRT file.")
    optimize.add_argument("--output-dir", "-o", default="subtitles")
    optimize.add_argument("--output-base", help="Base filename for final SRT/TXT outputs.")
    optimize.add_argument("--description", help="Inline context, terminology, or correction guidance.")
    optimize.add_argument("--description-file", help="Text file with context, terminology, or correction guidance.")
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
    translate.add_argument("--description", help="Inline terminology or style guidance.")
    translate.add_argument("--description-file", help="Text file with terminology or style guidance.")
    translate.add_argument("--reflect", action="store_true", help="Use reflective two-step translation.")
    translate.add_argument("--subtitle-format", choices=["bilingual-trans-first", "bilingual-source-first", "translation-only"], default="bilingual-trans-first")
    translate.add_argument("--model", help="LLM model.")
    translate.add_argument("--api-key", help="LLM API key.")
    translate.add_argument("--base-url", help="LLM API base URL.")
    translate.add_argument("--threads", type=int, default=5)
    translate.add_argument("--batch-size", type=int, default=10)
    translate.set_defaults(func=run_translate)

    return parser


def main() -> None:
    load_local_llm_config()
    parser = build_parser()
    args = parser.parse_args()
    try:
        print_result(args.func(args))
    except SubtitleSkillError as exc:
        print_result(
            {
                "ok": False,
                "action": exc.action,
                "step": exc.step,
                "error_type": exc.error_type,
                "message": str(exc),
                "suggested_fix": exc.suggested_fix,
            }
        )
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
