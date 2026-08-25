"""Argument parser construction for the subtitle CLI."""

from __future__ import annotations

import argparse
import os
from collections.abc import Callable, Mapping

from .qc import DEFAULT_MAX_DISPLAY_CHARS_ENGLISH, DEFAULT_MAX_WORD_COUNT_ENGLISH
from .split import DEFAULT_MAX_WORD_COUNT_CJK


def build_parser(
    parser_class: type[argparse.ArgumentParser],
    handlers: Mapping[str, Callable[[argparse.Namespace], dict[str, object]]],
    positive_int: Callable[[str], int],
    *,
    default_model_name: str,
    default_llm_model: str,
) -> argparse.ArgumentParser:
    parser = parser_class(description="Generate and process subtitles with standard SRT/TXT outputs.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    transcribe = subparsers.add_parser("transcribe", help="Generate SRT/TXT from a local media file or video URL.")
    transcribe.add_argument("input", help="Local audio/video path or video URL.")
    transcribe.add_argument("--output-dir", "-o", default="subtitles", help="Directory for final SRT/TXT outputs.")
    transcribe.add_argument("--model", default=os.getenv("SUBTITLE_WHISPER_MODEL", default_model_name), help="faster-whisper model name or local model path.")
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
    transcribe.add_argument("--split-model", default=os.getenv("SUBTITLE_LLM_MODEL", default_llm_model), help="LLM model for semantic splitting.")
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
    transcribe.add_argument(
        "--llm-timeout-seconds",
        type=positive_int,
        default=int(os.getenv("SUBTITLE_LLM_TIMEOUT_SECONDS", "180")),
        help="Timeout for each semantic-split LLM request. Completed chunks are checkpointed for resume.",
    )
    transcribe.add_argument("--api-key", help="LLM API key for semantic split when enabled.")
    transcribe.add_argument("--base-url", help="LLM API base URL for semantic split when enabled.")
    transcribe.set_defaults(func=handlers["transcribe"])

    split = subparsers.add_parser("split", help="Apply LLM semantic segmentation to raw Whisper JSON.")
    split.add_argument("input", help="Raw Whisper JSON with word timestamps.")
    split.add_argument("--output-dir", "-o", default="subtitles")
    split.add_argument("--output-base", help="Base filename for final SRT/TXT outputs.")
    split.add_argument("--replace-existing", action="store_true", help="Archive and replace an existing SRT/TXT output pair.")
    split.add_argument("--split-model", default=os.getenv("SUBTITLE_LLM_MODEL", default_llm_model))
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
    split.add_argument(
        "--llm-timeout-seconds",
        type=positive_int,
        default=int(os.getenv("SUBTITLE_LLM_TIMEOUT_SECONDS", "180")),
        help="Timeout for each LLM request. Completed chunks are checkpointed for resume.",
    )
    split.add_argument("--api-key", help="LLM API key.")
    split.add_argument("--base-url", help="LLM API base URL.")
    split.set_defaults(func=handlers["split"])

    normalize = subparsers.add_parser("normalize", help="Normalize an existing SRT and export standard SRT/TXT.")
    normalize.add_argument("input", help="Input SRT file.")
    normalize.add_argument("--output-dir", "-o", default="subtitles")
    normalize.add_argument("--output-base", help="Base filename for final SRT/TXT outputs.")
    normalize.add_argument("--replace-existing", action="store_true", help="Archive and replace an existing SRT/TXT output pair.")
    normalize.set_defaults(func=handlers["normalize"])

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
    optimize.set_defaults(func=handlers["optimize"])

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
    translate.set_defaults(func=handlers["translate"])

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
    qc.set_defaults(func=handlers["qc"])

    return parser

