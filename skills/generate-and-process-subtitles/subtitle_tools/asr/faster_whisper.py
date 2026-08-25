from __future__ import annotations

import json
import os
import sysconfig
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from ..config import TranscribeConfig
from ..data import ASRData
from ..utils import setup_logger
from .base import BaseASR


logger = setup_logger("faster_whisper")
_DLL_DIR_HANDLES: list[Any] = []
_MIN_WORD_DURATION_SECONDS = 0.001


def _repair_zero_duration_words(segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Give rare zero-duration Whisper words a minimal, non-overlapping 1 ms span."""
    repairs: List[Dict[str, Any]] = []
    for segment_index, segment in enumerate(segments):
        words = segment.get("words") or []
        for word_index, word in enumerate(words):
            start = float(word["start"])
            end = float(word["end"])
            if end != start:
                continue

            previous_end = (
                float(words[word_index - 1]["end"])
                if word_index > 0
                else float(segment["start"])
            )
            next_start = (
                float(words[word_index + 1]["start"])
                if word_index + 1 < len(words)
                else float(segment["end"])
            )
            repaired_start = start
            repaired_end = end
            method = ""
            if start - previous_end >= _MIN_WORD_DURATION_SECONDS:
                repaired_start = start - _MIN_WORD_DURATION_SECONDS
                repaired_end = start
                method = "bounded_1ms_before_reported_time"
            elif next_start - end >= _MIN_WORD_DURATION_SECONDS:
                repaired_start = end
                repaired_end = end + _MIN_WORD_DURATION_SECONDS
                method = "bounded_1ms_after_reported_time"
            else:
                continue

            word["start"] = repaired_start
            word["end"] = repaired_end
            repairs.append(
                {
                    "segment_index": segment_index,
                    "word_index": word_index,
                    "word": word.get("word"),
                    "original_start": start,
                    "original_end": end,
                    "repaired_start": repaired_start,
                    "repaired_end": repaired_end,
                    "method": method,
                }
            )
    return repairs


def _configure_windows_cuda_dll_paths() -> None:
    if os.name != "nt":
        return

    purelib = Path(sysconfig.get_paths().get("purelib") or "")
    candidates = [
        purelib / "nvidia" / "cublas" / "bin",
        purelib / "nvidia" / "cudnn" / "bin",
        purelib / "nvidia" / "cuda_nvrtc" / "bin",
        purelib / "ctranslate2",
    ]
    existing_paths = os.environ.get("PATH", "").split(os.pathsep)
    prepend_paths: list[str] = []

    for candidate in candidates:
        if not candidate.exists():
            continue
        path = str(candidate)
        if path not in existing_paths and path not in prepend_paths:
            prepend_paths.append(path)
        if hasattr(os, "add_dll_directory"):
            try:
                _DLL_DIR_HANDLES.append(os.add_dll_directory(path))
            except OSError as exc:
                logger.warning("Failed to add CUDA DLL directory %s: %s", path, exc)

    if prepend_paths:
        os.environ["PATH"] = os.pathsep.join(prepend_paths + existing_paths)


class FasterWhisperASR(BaseASR):
    def __init__(self, audio_input: str, config: TranscribeConfig):
        super().__init__(audio_input)
        self.config = config

    def run(self, callback: Optional[Callable[[int, str], None]] = None) -> ASRData:
        _configure_windows_cuda_dll_paths()
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise RuntimeError(
                "Missing dependency `faster-whisper`. Install requirements.txt for this skill."
            ) from exc

        model, device, compute_type = self._load_model_with_fallback(WhisperModel)
        logger.info("Transcribing with model=%s device=%s compute_type=%s", self.config.model_name, device, compute_type)

        segments_iter, info = model.transcribe(
            self.audio_input,
            language=self.config.language,
            initial_prompt=self.config.prompt,
            vad_filter=self.config.vad_filter,
            vad_parameters={"threshold": self.config.vad_threshold},
            word_timestamps=True,
            clip_timestamps=self.config.clip_timestamps or "0",
        )

        segments: List[Dict[str, Any]] = []
        for index, segment in enumerate(segments_iter, 1):
            words = [
                {
                    "word": word.word,
                    "start": float(word.start or 0.0),
                    "end": float(word.end or word.start or 0.0),
                }
                for word in (segment.words or [])
            ]
            segments.append(
                {
                    "id": getattr(segment, "id", index - 1),
                    "start": float(segment.start),
                    "end": float(segment.end),
                    "text": segment.text.strip(),
                    "words": words,
                }
            )
            if callback and getattr(info, "duration", None):
                progress = int(min(100, max(0, (float(segment.end) / float(info.duration)) * 100)))
                callback(progress, f"{progress}%")

        timestamp_repairs = _repair_zero_duration_words(segments)
        if timestamp_repairs:
            logger.warning(
                "Repaired %s zero-duration ASR words with bounded 1 ms intervals; evidence is recorded in raw ASR JSON.",
                len(timestamp_repairs),
            )

        raw_payload = {
            "language": getattr(info, "language", None),
            "language_probability": getattr(info, "language_probability", None),
            "duration": getattr(info, "duration", None),
            "model": self.config.model_name,
            "device": device,
            "compute_type": compute_type,
            "vad_filter": self.config.vad_filter,
            "clip_timestamps": self.config.clip_timestamps,
            "segments": segments,
            "timestamp_repairs": timestamp_repairs,
        }
        self.result_metadata = {
            "language": raw_payload["language"],
            "language_probability": raw_payload["language_probability"],
            "duration": raw_payload["duration"],
        }

        output_dir = Path(self.config.output_dir or Path(self.audio_input).parent)
        output_dir.mkdir(parents=True, exist_ok=True)
        raw_path = output_dir / f"{Path(self.audio_input).stem}.asr.json"
        raw_path.write_text(json.dumps(raw_payload, ensure_ascii=False, indent=2), encoding="utf-8")

        asr_data = ASRData.from_whisper_json(raw_payload)
        if not asr_data.has_word_timestamps():
            raise RuntimeError("ASR did not provide word-level timestamps.")
        if callback:
            callback(100, "100%")
        return asr_data

    def _load_model_with_fallback(self, whisper_model_cls: Any) -> tuple[Any, str, str]:
        requested = (self.config.device or "auto", self.config.compute_type or "auto")
        attempts = [requested]
        if requested != ("cpu", "int8"):
            attempts.append(("cpu", "int8"))

        last_error: Optional[Exception] = None
        for device, compute_type in attempts:
            try:
                return (
                    whisper_model_cls(self.config.model_name, device=device, compute_type=compute_type),
                    device,
                    compute_type,
                )
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "Failed to load faster-whisper model on device=%s compute_type=%s: %s",
                    device,
                    compute_type,
                    exc,
                )

        raise RuntimeError(f"Failed to load faster-whisper model: {last_error}")
