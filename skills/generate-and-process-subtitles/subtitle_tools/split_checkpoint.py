"""Content-addressed progress checkpoints for semantic subtitle splitting."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .data import ASRDataSeg, ASRWord, join_word_texts


def _fingerprint(
    chunks: Sequence[Sequence[ASRWord]],
    segment_end_indices: Sequence[int],
    settings: Dict[str, Any],
) -> str:
    payload = {
        "schema_version": 1,
        "chunks": [[word.to_dict() for word in chunk] for chunk in chunks],
        "segment_end_indices": list(segment_end_indices),
        "settings": settings,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _segments_from_payload(payload: Any) -> List[ASRDataSeg]:
    if not isinstance(payload, list):
        raise ValueError("checkpoint segments must be a list")
    segments: List[ASRDataSeg] = []
    for item in payload:
        if not isinstance(item, dict) or not isinstance(item.get("words"), list):
            raise ValueError("checkpoint segment is malformed")
        words = [
            ASRWord(
                text=str(word["text"]),
                start_time=int(word["start_time"]),
                end_time=int(word["end_time"]),
            )
            for word in item["words"]
        ]
        if not words:
            raise ValueError("checkpoint segment has no words")
        segments.append(
            ASRDataSeg(
                text=join_word_texts(words),
                start_time=words[0].start_time,
                end_time=words[-1].end_time,
                words=words,
            )
        )
    return segments


def load_split_checkpoint(
    checkpoint_dir: Optional[Path],
    chunks: Sequence[Sequence[ASRWord]],
    segment_end_indices: Sequence[int],
    settings: Dict[str, Any],
    logger: Any,
) -> Tuple[Optional[Path], List[List[ASRDataSeg]]]:
    if checkpoint_dir is None:
        return None, []
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    fingerprint = _fingerprint(chunks, segment_end_indices, settings)
    checkpoint_path = checkpoint_dir / f"semantic-split-{fingerprint[:16]}.checkpoint.json"
    if not checkpoint_path.exists():
        return checkpoint_path, []
    try:
        payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        if payload.get("schema_version") != 1 or payload.get("fingerprint") != fingerprint:
            raise ValueError("checkpoint identity does not match")
        raw_chunks = payload.get("completed_chunks")
        if not isinstance(raw_chunks, list) or len(raw_chunks) > len(chunks):
            raise ValueError("checkpoint chunk count is invalid")
        completed: List[List[ASRDataSeg]] = []
        for index, raw_segments in enumerate(raw_chunks):
            mapped = _segments_from_payload(raw_segments)
            if [word.to_dict() for segment in mapped for word in segment.words] != [
                word.to_dict() for word in chunks[index]
            ]:
                raise ValueError(f"checkpoint chunk {index + 1} does not preserve source words")
            completed.append(mapped)
        return checkpoint_path, completed
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        logger.warning("Ignoring invalid semantic split checkpoint %s: %s", checkpoint_path, exc)
        return checkpoint_path, []


def write_split_checkpoint(
    checkpoint_path: Optional[Path],
    chunks: Sequence[Sequence[ASRWord]],
    segment_end_indices: Sequence[int],
    settings: Dict[str, Any],
    completed_chunks: Sequence[Sequence[ASRDataSeg]],
) -> None:
    if checkpoint_path is None:
        return
    payload = {
        "schema_version": 1,
        "fingerprint": _fingerprint(chunks, segment_end_indices, settings),
        "chunk_count": len(chunks),
        "completed_chunk_count": len(completed_chunks),
        "completed_chunks": [
            [segment.to_dict(include_words=True) for segment in chunk]
            for chunk in completed_chunks
        ],
    }
    temp_path = checkpoint_path.with_name(f".{checkpoint_path.name}.{os.getpid()}.tmp")
    try:
        temp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
            newline="\n",
        )
        os.replace(temp_path, checkpoint_path)
    finally:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass
