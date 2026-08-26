from __future__ import annotations

import copy
import os
import sysconfig
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from ..config import TranscribeConfig
from ..data import ASRData
from ..publishing import (
    component_safe_base_name,
    json_payload_bytes,
    sha256_bytes,
    write_immutable_json_atomic,
)
from ..utils import setup_logger
from .base import BaseASR


logger = setup_logger("faster_whisper")
_DLL_DIR_HANDLES: list[Any] = []
_MIN_WORD_DURATION_MS = 1
_MIN_DONOR_REMAINING_MS = 20
_MAX_CLUSTER_SAMPLE_WORDS = 5
_MAX_CLUSTER_SAMPLE_CHARS = 40


class TimestampRepairLimitError(ValueError):
    """Raised after raw evidence is saved when packed timestamp repair is unsafe."""

    def __init__(
        self,
        message: str,
        *,
        raw_asr_path: Path,
        raw_asr_sha256: str,
        repair_summary: Dict[str, Any],
    ) -> None:
        super().__init__(message)
        self.raw_asr_path = raw_asr_path
        self.raw_asr_sha256 = raw_asr_sha256
        self.repair_summary = repair_summary


def _seconds_to_ms(value: Any) -> int:
    return int(round(float(value) * 1000))


def _set_word_interval_ms(word: Dict[str, Any], start_ms: int, end_ms: int) -> None:
    word["start"] = start_ms / 1000
    word["end"] = end_ms / 1000


def _is_quantized_zero_duration(word: Dict[str, Any]) -> bool:
    start = float(word["start"])
    end = float(word["end"])
    return end >= start and _seconds_to_ms(end) == _seconds_to_ms(start)


def _repair_zero_duration_words(
    segments: List[Dict[str, Any]],
    *,
    skip_word_indices: Optional[set[tuple[int, int]]] = None,
) -> List[Dict[str, Any]]:
    """Use a proven adjacent gap for a minimal, non-overlapping 1 ms span."""
    repairs: List[Dict[str, Any]] = []
    for segment_index, segment in enumerate(segments):
        words = segment.get("words") or []
        for word_index, word in enumerate(words):
            if skip_word_indices and (segment_index, word_index) in skip_word_indices:
                continue
            start = float(word["start"])
            end = float(word["end"])
            if not _is_quantized_zero_duration(word):
                continue

            start_ms = _seconds_to_ms(start)
            previous_end_ms = (
                _seconds_to_ms(words[word_index - 1]["end"])
                if word_index > 0
                else _seconds_to_ms(segment["start"])
            )
            next_start_ms = (
                _seconds_to_ms(words[word_index + 1]["start"])
                if word_index + 1 < len(words)
                else _seconds_to_ms(segment["end"])
            )
            repaired_start_ms = start_ms
            repaired_end_ms = start_ms
            method = ""
            if start_ms - previous_end_ms >= _MIN_WORD_DURATION_MS:
                repaired_start_ms = start_ms - _MIN_WORD_DURATION_MS
                repaired_end_ms = start_ms
                method = "bounded_1ms_before_reported_time"
            elif next_start_ms - start_ms >= _MIN_WORD_DURATION_MS:
                repaired_start_ms = start_ms
                repaired_end_ms = start_ms + _MIN_WORD_DURATION_MS
                method = "bounded_1ms_after_reported_time"
            else:
                continue

            _set_word_interval_ms(word, repaired_start_ms, repaired_end_ms)
            repairs.append(
                {
                    "segment_index": segment_index,
                    "word_index": word_index,
                    "word": word.get("word"),
                    "original_start": start,
                    "original_end": end,
                    "repaired_start": word["start"],
                    "repaired_end": word["end"],
                    "method": method,
                }
            )
    return repairs


def _find_packed_zero_clusters(
    segments: List[Dict[str, Any]],
    *,
    require_same_timestamp: bool = True,
) -> List[Dict[str, Any]]:
    clusters: List[Dict[str, Any]] = []
    for segment_index, segment in enumerate(segments):
        words = segment.get("words") or []
        word_index = 0
        while word_index < len(words):
            if not _is_quantized_zero_duration(words[word_index]):
                word_index += 1
                continue
            timestamp_ms = _seconds_to_ms(words[word_index]["start"])
            start_index = word_index
            while (
                word_index + 1 < len(words)
                and _is_quantized_zero_duration(words[word_index + 1])
                and (
                    not require_same_timestamp
                    or _seconds_to_ms(words[word_index + 1]["start"])
                    == timestamp_ms
                )
            ):
                word_index += 1
            end_index = word_index
            timestamp_samples = [
                _seconds_to_ms(words[index]["start"])
                for index in range(
                    start_index,
                    min(end_index + 1, start_index + _MAX_CLUSTER_SAMPLE_WORDS),
                )
            ]
            timestamps_monotonic = all(
                _seconds_to_ms(words[index]["start"])
                <= _seconds_to_ms(words[index + 1]["start"])
                for index in range(start_index, end_index)
            )
            sample_indices = list(
                range(
                    start_index,
                    min(end_index + 1, start_index + _MAX_CLUSTER_SAMPLE_WORDS),
                )
            )
            clusters.append(
                {
                    "segment_index": segment_index,
                    "start_word_index": start_index,
                    "end_word_index": end_index,
                    "timestamp_ms": timestamp_ms,
                    "end_timestamp_ms": _seconds_to_ms(words[end_index]["start"]),
                    "word_count": end_index - start_index + 1,
                    "timestamps_monotonic": timestamps_monotonic,
                    "timestamp_ms_samples": timestamp_samples,
                    "timestamp_samples_truncated": end_index - start_index + 1
                    > len(timestamp_samples),
                    "word_samples": [
                        {
                            "word_index": index,
                            "word": str(words[index].get("word") or "")[
                                :_MAX_CLUSTER_SAMPLE_CHARS
                            ],
                        }
                        for index in sample_indices
                    ],
                    "word_samples_truncated": end_index - start_index + 1
                    > len(sample_indices),
                }
            )
            word_index += 1
    return clusters


def _donor_capacity_ms(word: Optional[Dict[str, Any]]) -> int:
    if word is None:
        return 0
    start_ms = _seconds_to_ms(word["start"])
    end_ms = _seconds_to_ms(word["end"])
    if end_ms <= start_ms:
        return 0
    return max(0, end_ms - start_ms - _MIN_DONOR_REMAINING_MS)


def _cluster_allocation_plan(
    word_count: int,
    *,
    left_gap: int,
    right_gap: int,
    left_donor_capacity: int,
    right_donor_capacity: int,
) -> Optional[tuple[int, int, int, int]]:
    candidates: List[tuple[int, int, int, int, int, int]] = []
    left_capacity = left_gap + left_donor_capacity
    right_capacity = right_gap + right_donor_capacity
    for left_span in range(word_count + 1):
        right_span = word_count - left_span
        if left_span > left_capacity or right_span > right_capacity:
            continue
        left_borrow = max(0, left_span - left_gap)
        right_borrow = max(0, right_span - right_gap)
        candidates.append(
            (
                left_borrow + right_borrow,
                left_span,
                left_span,
                right_span,
                left_borrow,
                right_borrow,
            )
        )
    if not candidates:
        return None
    _, _, left_span, right_span, left_borrow, right_borrow = min(candidates)
    return left_span, right_span, left_borrow, right_borrow


def _repair_packed_zero_duration_words(
    segments: List[Dict[str, Any]],
    *,
    max_repairs_per_10k: int,
    max_cluster_size: int,
    observed_clusters: Optional[List[Dict[str, Any]]] = None,
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
    """Repair packed zero-duration clusters atomically by shrinking adjacent donors."""
    clusters = _find_packed_zero_clusters(segments)
    original_clusters = observed_clusters if observed_clusters is not None else clusters
    total_words = sum(len(segment.get("words") or []) for segment in segments)
    packed_word_count = sum(cluster["word_count"] for cluster in clusters)
    allowed_repairs = (
        max(
            max_cluster_size,
            (total_words * max_repairs_per_10k + 9999) // 10000,
        )
        if packed_word_count
        else 0
    )
    max_observed_cluster_size = max(
        (cluster["word_count"] for cluster in original_clusters), default=0
    )
    non_monotonic_clusters = [
        cluster
        for cluster in original_clusters
        if not bool(cluster.get("timestamps_monotonic", True))
    ]
    blocked_reasons: List[str] = []
    if packed_word_count > allowed_repairs:
        blocked_reasons.append(
            f"{packed_word_count} packed words exceed the scaled limit of {allowed_repairs}"
        )
    if max_observed_cluster_size > max_cluster_size:
        blocked_reasons.append(
            f"cluster size {max_observed_cluster_size} exceeds the limit of {max_cluster_size}"
        )
    if non_monotonic_clusters:
        blocked_reasons.append(
            f"{len(non_monotonic_clusters)} zero-duration run(s) have non-monotonic "
            "timestamps and cannot be repaired safely"
        )

    summary: Dict[str, Any] = {
        "status": "blocked" if blocked_reasons else "ok",
        "total_words": total_words,
        "observed_zero_cluster_count": len(original_clusters),
        "packed_cluster_count": len(clusters),
        "packed_word_count": packed_word_count,
        "packed_word_repairs": 0,
        "donor_adjustments": 0,
        "borrowed_ms": 0,
        "max_observed_cluster_size": max_observed_cluster_size,
        "review_recommended": max_observed_cluster_size >= 4,
        "limits": {
            "max_packed_word_repairs_per_10k": max_repairs_per_10k,
            "scaled_packed_word_limit": allowed_repairs,
            "max_packed_cluster_size": max_cluster_size,
            "minimum_donor_remaining_ms": _MIN_DONOR_REMAINING_MS,
        },
        "blocked_reasons": blocked_reasons,
        "cluster_samples": original_clusters[:5],
    }
    if blocked_reasons or not clusters:
        return segments, [], summary

    repaired_segments = copy.deepcopy(segments)
    repairs: List[Dict[str, Any]] = []
    for cluster_number, cluster in enumerate(clusters, start=1):
        segment_index = int(cluster["segment_index"])
        start_index = int(cluster["start_word_index"])
        end_index = int(cluster["end_word_index"])
        timestamp_ms = int(cluster["timestamp_ms"])
        word_count = int(cluster["word_count"])
        segment = repaired_segments[segment_index]
        words = segment.get("words") or []
        left_donor = words[start_index - 1] if start_index > 0 else None
        right_donor = words[end_index + 1] if end_index + 1 < len(words) else None
        left_boundary_ms = (
            _seconds_to_ms(left_donor["end"])
            if left_donor is not None
            else _seconds_to_ms(segment["start"])
        )
        right_boundary_ms = (
            _seconds_to_ms(right_donor["start"])
            if right_donor is not None
            else _seconds_to_ms(segment["end"])
        )
        left_gap = max(0, timestamp_ms - left_boundary_ms)
        right_gap = max(0, right_boundary_ms - timestamp_ms)
        left_donor_capacity = (
            _donor_capacity_ms(left_donor) if left_boundary_ms <= timestamp_ms else 0
        )
        right_donor_capacity = (
            _donor_capacity_ms(right_donor) if right_boundary_ms >= timestamp_ms else 0
        )
        allocation = _cluster_allocation_plan(
            word_count,
            left_gap=left_gap,
            right_gap=right_gap,
            left_donor_capacity=left_donor_capacity,
            right_donor_capacity=right_donor_capacity,
        )
        if allocation is None:
            summary["status"] = "blocked"
            summary["blocked_reasons"].append(
                "segment "
                f"{segment_index + 1} words {start_index + 1}-{end_index + 1} "
                f"need {word_count} ms but adjacent gaps and donors safely provide only "
                f"{left_gap + right_gap + left_donor_capacity + right_donor_capacity} ms"
            )
            return segments, [], summary
        left_span, right_span, left_borrow, right_borrow = allocation

        cluster_id = f"segment-{segment_index + 1}-cluster-{cluster_number}"
        original_cluster_words = segments[segment_index].get("words") or []
        for offset, word_index in enumerate(range(start_index, end_index + 1)):
            if offset < left_span:
                repaired_start_ms = timestamp_ms - left_span + offset
            else:
                repaired_start_ms = timestamp_ms + (offset - left_span)
            repaired_end_ms = repaired_start_ms + _MIN_WORD_DURATION_MS
            word = words[word_index]
            original_word = original_cluster_words[word_index]
            _set_word_interval_ms(word, repaired_start_ms, repaired_end_ms)
            repairs.append(
                {
                    "segment_index": segment_index,
                    "word_index": word_index,
                    "word": word.get("word"),
                    "original_start": original_word["start"],
                    "original_end": original_word["end"],
                    "repaired_start": word["start"],
                    "repaired_end": word["end"],
                    "method": "packed_cluster_redistribution",
                    "cluster_id": cluster_id,
                }
            )

        if left_borrow and left_donor is not None:
            original_start = left_donor["start"]
            original_end = left_donor["end"]
            repaired_start_ms = _seconds_to_ms(left_donor["start"])
            repaired_end_ms = _seconds_to_ms(left_donor["end"]) - left_borrow
            _set_word_interval_ms(left_donor, repaired_start_ms, repaired_end_ms)
            repairs.append(
                {
                    "segment_index": segment_index,
                    "word_index": start_index - 1,
                    "word": left_donor.get("word"),
                    "original_start": original_start,
                    "original_end": original_end,
                    "repaired_start": left_donor["start"],
                    "repaired_end": left_donor["end"],
                    "method": "packed_cluster_left_donor_adjustment",
                    "cluster_id": cluster_id,
                    "borrowed_ms": left_borrow,
                }
            )
        if right_borrow and right_donor is not None:
            original_start = right_donor["start"]
            original_end = right_donor["end"]
            repaired_start_ms = _seconds_to_ms(right_donor["start"]) + right_borrow
            repaired_end_ms = _seconds_to_ms(right_donor["end"])
            _set_word_interval_ms(right_donor, repaired_start_ms, repaired_end_ms)
            repairs.append(
                {
                    "segment_index": segment_index,
                    "word_index": end_index + 1,
                    "word": right_donor.get("word"),
                    "original_start": original_start,
                    "original_end": original_end,
                    "repaired_start": right_donor["start"],
                    "repaired_end": right_donor["end"],
                    "method": "packed_cluster_right_donor_adjustment",
                    "cluster_id": cluster_id,
                    "borrowed_ms": right_borrow,
                }
            )

    summary["packed_word_repairs"] = packed_word_count
    summary["donor_adjustments"] = sum(
        repair["method"].endswith("donor_adjustment") for repair in repairs
    )
    summary["borrowed_ms"] = sum(
        int(repair.get("borrowed_ms") or 0) for repair in repairs
    )
    return repaired_segments, repairs, summary


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

        observed_clusters = _find_packed_zero_clusters(
            segments, require_same_timestamp=False
        )
        max_observed_cluster_size = max(
            (cluster["word_count"] for cluster in observed_clusters), default=0
        )
        has_non_monotonic_zero_run = any(
            not bool(cluster.get("timestamps_monotonic", True))
            for cluster in observed_clusters
        )
        same_timestamp_clusters = _find_packed_zero_clusters(segments)
        multiword_cluster_indices = {
            (int(cluster["segment_index"]), word_index)
            for cluster in same_timestamp_clusters
            if int(cluster["word_count"]) > 1
            for word_index in range(
                int(cluster["start_word_index"]),
                int(cluster["end_word_index"]) + 1,
            )
        }
        repair_candidate_segments = copy.deepcopy(segments)
        planned_gap_repairs = (
            []
            if (
                max_observed_cluster_size > self.config.max_packed_cluster_size
                or has_non_monotonic_zero_run
            )
            else _repair_zero_duration_words(
                repair_candidate_segments,
                skip_word_indices=multiword_cluster_indices,
            )
        )
        repaired_segments, packed_repairs, timestamp_repair_summary = (
            _repair_packed_zero_duration_words(
                repair_candidate_segments,
                max_repairs_per_10k=self.config.max_packed_word_repairs_per_10k,
                max_cluster_size=self.config.max_packed_cluster_size,
                observed_clusters=observed_clusters,
            )
        )
        if timestamp_repair_summary["status"] == "ok":
            segments = repaired_segments
            gap_repairs = planned_gap_repairs
            timestamp_repairs = gap_repairs + packed_repairs
        else:
            gap_repairs = []
            packed_repairs = []
            timestamp_repairs = []
            timestamp_repair_summary["packed_word_repairs"] = 0
            timestamp_repair_summary["donor_adjustments"] = 0
            timestamp_repair_summary["borrowed_ms"] = 0
        timestamp_repair_summary["gap_repairs"] = len(gap_repairs)
        timestamp_repair_summary["total_repair_records"] = len(timestamp_repairs)
        if timestamp_repairs:
            logger.warning(
                "Repaired %s zero-duration ASR words (%s gap, %s packed) with bounded 1 ms intervals; evidence is recorded in raw ASR JSON.",
                len(gap_repairs) + timestamp_repair_summary["packed_word_repairs"],
                len(gap_repairs),
                timestamp_repair_summary["packed_word_repairs"],
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
            "timestamp_repair_summary": timestamp_repair_summary,
        }

        output_dir = Path(self.config.output_dir or Path(self.audio_input).parent)
        output_dir.mkdir(parents=True, exist_ok=True)
        raw_payload_sha256 = sha256_bytes(json_payload_bytes(raw_payload))
        raw_base_name = component_safe_base_name(Path(self.audio_input).stem)
        raw_path = output_dir / f"{raw_base_name}-{raw_payload_sha256[:12]}.asr.json"
        write_immutable_json_atomic(raw_path, raw_payload, action="transcribe")
        self.result_metadata = {
            "language": raw_payload["language"],
            "language_probability": raw_payload["language_probability"],
            "duration": raw_payload["duration"],
            "raw_asr_json": str(raw_path),
            "raw_asr_hash_algorithm": "sha256",
            "raw_asr_sha256": raw_payload_sha256,
            "timestamp_repair_summary": timestamp_repair_summary,
        }

        if timestamp_repair_summary["status"] != "ok":
            reasons = "; ".join(timestamp_repair_summary["blocked_reasons"])
            raise TimestampRepairLimitError(
                f"packed zero-duration ASR repair was blocked: {reasons}",
                raw_asr_path=raw_path,
                raw_asr_sha256=raw_payload_sha256,
                repair_summary=timestamp_repair_summary,
            )

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
