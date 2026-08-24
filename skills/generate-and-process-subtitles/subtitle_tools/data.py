import json
import os
import platform
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff\uac00-\ud7af]")
_SPACELESS_RE = re.compile(r"^[\s\.,!?;:()\[\]{}<>\"'`~@#$%^&*_+=/\\|-]*$")
_NO_SPACE_BEFORE = {".", ",", "!", "?", ";", ":", "%", ")", "]", "}", ">", "'s"}
_NO_SPACE_AFTER = {"(", "[", "{", "<", "$", "#", '"', "'"}
_HYPHEN_TOKENS = {"-", "–", "—"}
_OPENING_PUNCT = {"(", "[", "{", "<", '"', "'"}
_PUNCT_ATTACH_PREV = {".", ",", "!", "?", ";", ":", "%", ")", "]", "}", ">", "…"}


def _has_hyphen_prefix(text: str) -> bool:
    stripped = (text or "").strip()
    return len(stripped) > 1 and stripped[0] in "-–—"


def _has_hyphen_suffix(text: str) -> bool:
    stripped = (text or "").strip()
    return len(stripped) > 1 and stripped[-1] in "-–—"


def _has_attach_prev_prefix(text: str) -> bool:
    stripped = (text or "").strip()
    return len(stripped) > 1 and stripped[0] in _PUNCT_ATTACH_PREV


def _is_numeric_token(text: str) -> bool:
    stripped = (text or "").strip()
    return bool(stripped) and stripped.isdigit()


def normalize_words(words: List["ASRWord"]) -> List["ASRWord"]:
    normalized: List[ASRWord] = []

    for word in words:
        token = word.text.replace("\n", " ").strip()
        if not token:
            continue

        current = ASRWord(text=token, start_time=word.start_time, end_time=word.end_time)
        if not normalized:
            normalized.append(current)
            continue

        prev = normalized[-1]
        prev_text = prev.text

        if token in _PUNCT_ATTACH_PREV:
            prev.text = f"{prev.text}{token}"
            prev.end_time = current.end_time
            continue

        if token.startswith("'") or _has_hyphen_prefix(token) or _has_attach_prev_prefix(token):
            prev.text = f"{prev.text}{token}"
            prev.end_time = current.end_time
            continue

        if prev_text in _OPENING_PUNCT or _has_hyphen_suffix(prev_text):
            prev.text = f"{prev.text}{token}"
            prev.end_time = current.end_time
            continue

        # Join number formatting like 18 , 000 -> 18,000
        if _is_numeric_token(token) and (prev_text.endswith(",") or prev_text.endswith(".")):
            numeric_prefix = prev_text[:-1]
            if _is_numeric_token(numeric_prefix):
                prev.text = f"{prev.text}{token}"
                prev.end_time = current.end_time
                continue

        normalized.append(current)

    return normalized


def handle_long_path(path: str) -> str:
    if platform.system() == "Windows" and len(path) > 260 and not path.startswith("\\\\?\\"):
        return rf"\\?\{os.path.abspath(path)}"
    return path


def _contains_cjk(text: str) -> bool:
    return bool(_CJK_RE.search(text or ""))


def _is_spacing_punctuation(text: str) -> bool:
    cleaned = (text or "").strip()
    return bool(cleaned) and bool(_SPACELESS_RE.match(cleaned))


def join_word_texts(words: List["ASRWord"]) -> str:
    words = normalize_words(words)
    result: List[str] = []
    for word in words:
        token = word.text.replace("\n", " ").strip()
        if not token:
            continue

        if not result:
            result.append(token)
            continue

        prev = result[-1]

        if _contains_cjk(prev) or _contains_cjk(token):
            result.append(token)
        elif token in _NO_SPACE_BEFORE or token.startswith("'"):
            result.append(token)
        elif prev in _NO_SPACE_AFTER:
            result.append(token)
        elif (
            prev in _HYPHEN_TOKENS
            or token in _HYPHEN_TOKENS
            or _has_hyphen_prefix(token)
            or _has_hyphen_suffix(prev)
        ):
            result.append(token)
        elif _is_spacing_punctuation(token):
            result.append(token)
        elif _is_spacing_punctuation(prev[-1:]) and prev[-1:] not in _HYPHEN_TOKENS:
            result.append(f" {token}")
        else:
            result.append(f" {token}")
    return "".join(result).strip()


@dataclass
class ASRWord:
    text: str
    start_time: int
    end_time: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "start_time": self.start_time,
            "end_time": self.end_time,
        }


@dataclass
class ASRDataSeg:
    text: str
    start_time: int
    end_time: int
    translated_text: str = ""
    words: List[ASRWord] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.words and not self.text.strip():
            self.text = join_word_texts(self.words)

    def to_srt_ts(self) -> str:
        return f"{self._ms_to_srt_time(self.start_time)} --> {self._ms_to_srt_time(self.end_time)}"

    @staticmethod
    def _ms_to_srt_time(ms: int) -> str:
        total_seconds, milliseconds = divmod(ms, 1000)
        minutes, seconds = divmod(total_seconds, 60)
        hours, minutes = divmod(minutes, 60)
        return f"{int(hours):02}:{int(minutes):02}:{int(seconds):02},{int(milliseconds):03}"

    def copy_with(self, **changes: Any) -> "ASRDataSeg":
        payload = {
            "text": self.text,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "translated_text": self.translated_text,
            "words": list(self.words),
        }
        payload.update(changes)
        return ASRDataSeg(**payload)

    def to_dict(self, *, include_words: bool = False) -> Dict[str, Any]:
        payload = {
            "start_time": self.start_time,
            "end_time": self.end_time,
            "text": self.text,
            "translated_text": self.translated_text,
        }
        if include_words and self.words:
            payload["words"] = [word.to_dict() for word in self.words]
        return payload


class ASRData:
    def __init__(self, segments: List[ASRDataSeg]):
        filtered = []
        for seg in segments:
            if seg.text and seg.text.strip():
                filtered.append(seg)
            elif seg.words:
                filtered.append(seg)
        self.segments = filtered
        self.segments.sort(key=lambda x: x.start_time)

    @property
    def words(self) -> List[ASRWord]:
        return [word for seg in self.segments for word in seg.words]

    def has_word_timestamps(self) -> bool:
        return bool(self.segments) and all(seg.words for seg in self.segments)

    def save(self, save_path: str, subtitle_format: str = "bilingual-trans-first"):
        save_path = handle_long_path(save_path)
        Path(save_path).parent.mkdir(parents=True, exist_ok=True)

        if save_path.endswith(".srt"):
            self.to_srt(save_path=save_path, subtitle_format=subtitle_format)
        elif save_path.endswith(".txt"):
            self.to_txt(save_path=save_path, subtitle_format=subtitle_format)
        elif save_path.endswith(".json"):
            with open(save_path, "w", encoding="utf-8") as f:
                json.dump(self.to_json(), f, ensure_ascii=False, indent=2)
        else:
            raise ValueError(f"Unsupported format: {save_path}")

    def to_plain_text(self) -> str:
        if self.has_word_timestamps():
            return join_word_texts(self.words)
        return "\n".join(seg.text for seg in self.segments if seg.text.strip())

    def to_txt(self, save_path=None, subtitle_format: str = "bilingual-trans-first") -> str:
        text_lines = []
        for seg in self.segments:
            if not seg.translated_text:
                line = seg.text
            else:
                if subtitle_format == "bilingual-trans-first":
                    line = f"{seg.translated_text}\n{seg.text}"
                elif subtitle_format == "bilingual-source-first":
                    line = f"{seg.text}\n{seg.translated_text}"
                elif subtitle_format == "translation-only":
                    line = seg.translated_text
                else:
                    line = f"{seg.translated_text}\n{seg.text}"
            text_lines.append(line)
        text = "\n".join(text_lines)
        if save_path:
            with open(save_path, "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
        return text

    def to_srt(self, save_path=None, subtitle_format: str = "bilingual-trans-first") -> str:
        srt_lines = []
        for n, seg in enumerate(self.segments, 1):
            if not seg.translated_text:
                content = seg.text
            else:
                if subtitle_format == "bilingual-trans-first":
                    content = f"{seg.translated_text}\n{seg.text}"
                elif subtitle_format == "bilingual-source-first":
                    content = f"{seg.text}\n{seg.translated_text}"
                elif subtitle_format == "translation-only":
                    content = seg.translated_text
                else:
                    content = f"{seg.translated_text}\n{seg.text}"
            srt_lines.append(f"{n}\n{seg.to_srt_ts()}\n{content}\n")
        srt_text = "\n".join(srt_lines)
        if save_path:
            with open(save_path, "w", encoding="utf-8", newline="\n") as f:
                f.write(srt_text)
        return srt_text

    def to_json(self, *, include_words: bool = False) -> dict:
        result = {}
        for i, seg in enumerate(self.segments, 1):
            result[str(i)] = seg.to_dict(include_words=include_words)
        return result

    @staticmethod
    def from_srt(srt_str: str) -> "ASRData":
        segments = []
        srt_time_pattern = re.compile(
            r"(\d{2}):(\d{2}):(\d{1,2})[.,](\d{3})\s-->\s(\d{2}):(\d{2}):(\d{1,2})[.,](\d{3})"
        )
        blocks = re.split(r"\n\s*\n", srt_str.strip())

        for block in blocks:
            lines = block.splitlines()
            if len(lines) < 3:
                continue

            match = srt_time_pattern.match(lines[1])
            if not match:
                continue

            time_parts = list(map(int, match.groups()))
            start_time = time_parts[0] * 3600000 + time_parts[1] * 60000 + time_parts[2] * 1000 + time_parts[3]
            end_time = time_parts[4] * 3600000 + time_parts[5] * 60000 + time_parts[6] * 1000 + time_parts[7]

            text = "\n".join(lines[2:]).strip()
            segments.append(ASRDataSeg(text, start_time, end_time))

        return ASRData(segments)

    @classmethod
    def from_whisper_json(cls, payload: Any) -> "ASRData":
        if isinstance(payload, str):
            payload = json.loads(payload)

        segments_payload = cls._extract_segments_payload(payload)
        segments: List[ASRDataSeg] = []

        for seg_payload in segments_payload:
            words = cls._extract_words(seg_payload)
            if not words:
                raise RuntimeError("Whisper JSON did not include word timestamps.")

            text = (seg_payload.get("text") or "").strip()
            if not text:
                text = join_word_texts(words)

            start_time = cls._seconds_to_ms(seg_payload.get("start", words[0].start_time / 1000))
            end_time = cls._seconds_to_ms(seg_payload.get("end", words[-1].end_time / 1000))
            segments.append(
                ASRDataSeg(
                    text=text,
                    start_time=start_time,
                    end_time=end_time,
                    words=words,
                )
            )

        if not segments:
            raise RuntimeError("Whisper JSON did not contain any transcription segments.")

        cls._validate_original_timeline(segments)
        for segment in segments:
            segment.words = normalize_words(segment.words)

        return cls(segments)

    @staticmethod
    def _validate_original_timeline(segments: List[ASRDataSeg]) -> None:
        previous_segment_end: Optional[int] = None
        previous_word_end: Optional[int] = None
        for segment_index, segment in enumerate(segments, start=1):
            if segment.start_time < 0 or segment.end_time <= segment.start_time:
                raise ValueError(
                    f"Whisper segment {segment_index} has non-positive duration."
                )
            if (
                previous_segment_end is not None
                and segment.start_time < previous_segment_end
            ):
                raise ValueError(
                    f"Whisper segment {segment_index} is reverse-timeline or overlaps the previous segment."
                )

            for word_index, word in enumerate(segment.words, start=1):
                if word.start_time < 0 or word.end_time <= word.start_time:
                    raise ValueError(
                        f"Whisper segment {segment_index} word {word_index} has non-positive duration."
                    )
                if previous_word_end is not None and word.start_time < previous_word_end:
                    raise ValueError(
                        f"Whisper segment {segment_index} word {word_index} is reverse-timeline or overlaps the previous word."
                    )
                if (
                    word.start_time < segment.start_time
                    or word.end_time > segment.end_time
                ):
                    raise ValueError(
                        f"Whisper segment {segment_index} word {word_index} falls outside its segment."
                    )
                previous_word_end = word.end_time

            previous_segment_end = segment.end_time

    @staticmethod
    def _extract_segments_payload(payload: Any) -> List[Dict[str, Any]]:
        if isinstance(payload, dict):
            if isinstance(payload.get("segments"), list):
                return payload["segments"]
            if isinstance(payload.get("transcription"), dict):
                return ASRData._extract_segments_payload(payload["transcription"])
            if isinstance(payload.get("result"), dict):
                return ASRData._extract_segments_payload(payload["result"])
        if isinstance(payload, list):
            return payload
        return []

    @staticmethod
    def _extract_words(segment_payload: Dict[str, Any]) -> List[ASRWord]:
        words_payload = segment_payload.get("words") or segment_payload.get("tokens") or []
        words: List[ASRWord] = []
        for item in words_payload:
            text = (item.get("word") or item.get("text") or "").strip()
            if not text:
                continue
            start_time = ASRData._seconds_to_ms(item.get("start"))
            end_time = ASRData._seconds_to_ms(item.get("end"))
            words.append(ASRWord(text=text, start_time=start_time, end_time=end_time))
        return words

    @staticmethod
    def _seconds_to_ms(value: Any) -> int:
        if value is None:
            return 0
        return int(round(float(value) * 1000))
