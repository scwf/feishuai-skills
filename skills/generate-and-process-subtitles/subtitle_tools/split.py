"""LLM-based subtitle segmentation using word timestamps."""

from __future__ import annotations

import difflib
import re
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from .data import ASRData, ASRDataSeg, ASRWord, join_word_texts
from .llm import call_llm
from .prompts import get_prompt
from .qc import normalize_seam_times, validate_asr_timeline
from .utils import count_words, is_mainly_cjk, setup_logger


logger = setup_logger("subtitle_splitter")

DEFAULT_CHUNK_WORD_LIMIT = 350
DEFAULT_MAX_WORD_COUNT_CJK = 25
DEFAULT_MAX_WORD_COUNT_ENGLISH = 21
MAX_STEPS = 2
CHUNK_CUT_MIN_FRACTION = 0.7
SEAM_PAUSE_MS = 400
SENTENCE_END_RE = re.compile(r"""[.!?…。！？]["')\]”’）》】」』〕〉》]*$""")
SplitFn = Callable[..., List[str]]


class SubtitleSplitValidationError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        candidate_output: Optional[ASRData] = None,
        candidate_segments: Optional[Sequence[str]] = None,
        original_text: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.candidate_output = candidate_output
        self.candidate_segments = list(candidate_segments) if candidate_segments is not None else None
        self.original_text = original_text


def normalize_text_for_match(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def split_subtitle(
    subtitle_data: ASRData,
    *,
    model: str,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    max_word_count_cjk: int = DEFAULT_MAX_WORD_COUNT_CJK,
    max_word_count_english: int = DEFAULT_MAX_WORD_COUNT_ENGLISH,
    chunk_word_limit: int = DEFAULT_CHUNK_WORD_LIMIT,
    max_retries: int = MAX_STEPS,
    split_fn: Optional[SplitFn] = None,
    seam_times_out: Optional[List[int]] = None,
    seam_failures_out: Optional[List[Dict[str, Any]]] = None,
) -> ASRData:
    splitter = SubtitleSplitter(
        model=model,
        api_key=api_key,
        base_url=base_url,
        max_word_count_cjk=max_word_count_cjk,
        max_word_count_english=max_word_count_english,
        chunk_word_limit=chunk_word_limit,
        max_retries=max_retries,
        split_fn=split_fn,
    )
    result = splitter.split_subtitle(subtitle_data)
    if seam_times_out is not None:
        seam_times_out.extend(normalize_seam_times(splitter.seam_times_ms))
    if seam_failures_out is not None:
        seam_failures_out.extend(splitter.seam_repair_failures)
    return result


def original_segment_end_indices(subtitle_data: ASRData) -> List[int]:
    ends: List[int] = []
    cursor = -1
    for segment in subtitle_data.segments:
        if not segment.words:
            continue
        cursor += len(segment.words)
        ends.append(cursor)
    return ends


def is_sentence_end(text: str) -> bool:
    return bool(SENTENCE_END_RE.search((text or "").strip()))


def is_clean_sentence_seam(left: ASRDataSeg, right: ASRDataSeg) -> bool:
    left_text = (left.text or "").strip()
    right_text = (right.text or "").strip()
    if not left_text or not right_text:
        return False
    if not is_sentence_end(left_text):
        return False
    right_content = right_text.lstrip("\"'“‘([（《【「『 ")
    if not right_content:
        return False
    first = right_content[0]
    is_uncased_letter = first.isalpha() and first.lower() == first.upper()
    return first.isupper() or is_uncased_letter


class SubtitleSplitter:
    def __init__(
        self,
        *,
        model: str,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        max_word_count_cjk: int = DEFAULT_MAX_WORD_COUNT_CJK,
        max_word_count_english: int = DEFAULT_MAX_WORD_COUNT_ENGLISH,
        chunk_word_limit: int = DEFAULT_CHUNK_WORD_LIMIT,
        max_retries: int = MAX_STEPS,
        split_fn: Optional[SplitFn] = None,
    ) -> None:
        self.model = model
        self.api_key = api_key
        self.base_url = base_url
        self.max_word_count_cjk = max_word_count_cjk
        self.max_word_count_english = max_word_count_english
        self.chunk_word_limit = chunk_word_limit
        self.max_retries = max_retries
        self.split_fn = split_fn or split_by_llm
        self.seam_times_ms: List[int] = []
        self.seam_repair_failures: List[Dict[str, Any]] = []

    def split_subtitle(self, subtitle_data: ASRData) -> ASRData:
        if not subtitle_data.has_word_timestamps():
            raise RuntimeError("Subtitle splitting requires word-level timestamps.")

        words = subtitle_data.words
        chunks = self._chunk_words(words, original_segment_end_indices(subtitle_data))
        self.seam_times_ms = [chunk[-1].end_time for chunk in chunks[:-1] if chunk]
        self.seam_repair_failures = []
        result_segments: List[ASRDataSeg] = []
        chunk_ranges: List[Tuple[int, int]] = []
        for chunk_words in chunks:
            mapped = self._split_chunk(chunk_words)
            start = len(result_segments)
            result_segments.extend(mapped)
            chunk_ranges.append((start, len(result_segments)))
        repaired = self._repair_seams(result_segments, chunk_ranges)
        try:
            validate_asr_timeline(repaired)
        except ValueError as exc:
            raise SubtitleSplitValidationError(str(exc)) from exc
        return ASRData(repaired)

    def _split_chunk(self, chunk_words: Sequence[ASRWord]) -> List[ASRDataSeg]:
        text = join_word_texts(list(chunk_words))
        sentences = self.split_fn(
            text,
            words=chunk_words,
            model=self.model,
            api_key=self.api_key,
            base_url=self.base_url,
            max_word_count_cjk=self.max_word_count_cjk,
            max_word_count_english=self.max_word_count_english,
            max_retries=self.max_retries,
        )
        return map_sentences_to_words(chunk_words, sentences)

    def _chunk_words(
        self,
        words: Sequence[ASRWord],
        segment_end_indices: Optional[Sequence[int]] = None,
    ) -> List[List[ASRWord]]:
        if not words:
            return []

        ends = set(segment_end_indices or ())
        chunks: List[List[ASRWord]] = []
        start = 0
        total = len(words)
        min_cut_count = max(1, int(self.chunk_word_limit * CHUNK_CUT_MIN_FRACTION))

        while start < total:
            current_count = 0
            last_good_end: Optional[int] = None
            last_good_count = 0
            index = start
            while index < total:
                weight = max(1, count_words(words[index].text))
                if current_count + weight > self.chunk_word_limit and index > start:
                    break
                current_count += weight
                index += 1
                if index < total and self._is_good_cut_after(words, index - 1, ends):
                    last_good_end = index
                    last_good_count = current_count
            if index < total and last_good_end is not None and last_good_count >= min_cut_count:
                cut = last_good_end
            else:
                cut = index
            chunks.append(list(words[start:cut]))
            start = cut
        return chunks

    def _is_good_cut_after(
        self,
        words: Sequence[ASRWord],
        index: int,
        segment_end_indices: Sequence[int] | set[int],
    ) -> bool:
        word = words[index]
        if is_sentence_end(word.text):
            return True
        if index in segment_end_indices:
            return True
        if index + 1 < len(words) and words[index + 1].start_time - word.end_time >= SEAM_PAUSE_MS:
            return True
        return False

    def _repair_seams(
        self,
        segments: Sequence[ASRDataSeg],
        chunk_ranges: Sequence[Tuple[int, int]],
    ) -> List[ASRDataSeg]:
        if len(chunk_ranges) < 2:
            return list(segments)

        repaired: List[ASRDataSeg] = []
        previous_singleton_consumed = False
        for chunk_index, (start, end) in enumerate(chunk_ranges):
            chunk_segments = list(segments[start:end])
            if chunk_index == 0 or not repaired or not chunk_segments:
                repaired.extend(chunk_segments)
                previous_singleton_consumed = False
                continue

            left = repaired[-1]
            right = chunk_segments[0]
            if is_clean_sentence_seam(left, right):
                repaired.extend(chunk_segments)
                previous_singleton_consumed = False
                continue

            if previous_singleton_consumed:
                logger.warning("Seam repair skipped because its window overlaps the prior repaired seam.")
                self._record_seam_failure(
                    chunk_index,
                    left,
                    right,
                    reason="overlapping_repair_window",
                    message="The previous chunk had one cue already consumed by the prior seam repair.",
                )
                repaired.extend(chunk_segments)
                previous_singleton_consumed = False
                continue

            window_words = list(left.words) + list(right.words)
            if not window_words:
                repaired.extend(chunk_segments)
                previous_singleton_consumed = False
                continue

            try:
                window_segments = self._split_chunk(window_words)
            except Exception as exc:
                logger.warning("Seam repair skipped after split failure: %s", exc)
                self._record_seam_failure(
                    chunk_index,
                    left,
                    right,
                    reason="split_failed",
                    message=str(exc),
                )
                repaired.extend(chunk_segments)
                previous_singleton_consumed = False
                continue

            if not self._seam_window_is_valid(window_words, left, right, window_segments):
                logger.warning("Seam repair rejected because text or timing was not preserved.")
                self._record_seam_failure(
                    chunk_index,
                    left,
                    right,
                    reason="validation_failed",
                    message="Text, word order, or timing was not preserved.",
                )
                repaired.extend(chunk_segments)
                previous_singleton_consumed = False
                continue

            repaired[-1:] = window_segments
            repaired.extend(chunk_segments[1:])
            previous_singleton_consumed = len(chunk_segments) == 1
        return repaired

    def _record_seam_failure(
        self,
        chunk_index: int,
        left: ASRDataSeg,
        right: ASRDataSeg,
        *,
        reason: str,
        message: str,
    ) -> None:
        seam_position = chunk_index - 1
        seam_time_ms = (
            self.seam_times_ms[seam_position]
            if 0 <= seam_position < len(self.seam_times_ms)
            else left.end_time
        )
        self.seam_repair_failures.append(
            {
                "seam_index": chunk_index,
                "seam_time_ms": seam_time_ms,
                "reason": reason,
                "message": message,
                "left_text": left.text,
                "right_text": right.text,
            }
        )

    def _seam_window_is_valid(
        self,
        window_words: Sequence[ASRWord],
        left: ASRDataSeg,
        right: ASRDataSeg,
        window_segments: Sequence[ASRDataSeg],
    ) -> bool:
        if not window_segments:
            return False
        repaired_words = [word for segment in window_segments for word in segment.words]
        if [word.text for word in repaired_words] != [word.text for word in window_words]:
            return False
        original_norm = normalize_text_for_match(join_word_texts(list(window_words)))
        repaired_norm = normalize_text_for_match(" ".join(segment.text for segment in window_segments))
        if original_norm != repaired_norm:
            return False
        for segment in window_segments:
            max_allowed = (
                self.max_word_count_cjk
                if is_mainly_cjk(segment.text)
                else self.max_word_count_english
            )
            if count_words(segment.text) > max_allowed:
                return False
        if window_segments[0].start_time != left.start_time:
            return False
        if window_segments[-1].end_time != right.end_time:
            return False
        previous_end = window_segments[0].end_time
        for segment in window_segments:
            if segment.start_time >= segment.end_time:
                return False
        for segment in window_segments[1:]:
            if segment.start_time < previous_end:
                return False
            previous_end = segment.end_time
        return True


def split_by_llm(
    text: str,
    *,
    words: Optional[Sequence[ASRWord]] = None,
    model: str,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    max_word_count_cjk: int = DEFAULT_MAX_WORD_COUNT_CJK,
    max_word_count_english: int = DEFAULT_MAX_WORD_COUNT_ENGLISH,
    max_retries: int = MAX_STEPS,
) -> List[str]:
    system_prompt = get_prompt(
        "split/sentence",
        max_word_count_cjk=max_word_count_cjk,
        max_word_count_english=max_word_count_english,
    )
    messages = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": (
                "The following subtitle chunk may start or end at an arbitrary word boundary. "
                "Preserve leading/trailing fragments exactly, including trailing conjunctions such as And. "
                "Only insert <br> inside the subtitle text wrapped by <text> tags. "
                "Return the segmented subtitle text only, without the <text> tags.\n\n"
                f"<text>\n{text}\n</text>"
            ),
        },
    ]
    last_result: Optional[List[str]] = None

    for step in range(max_retries):
        response = call_llm(
            messages=messages,
            model=model,
            temperature=0.1,
            api_key=api_key,
            base_url=base_url,
        )
        result_text = response.choices[0].message.content or ""
        split_result = [segment.strip() for segment in re.sub(r"\n+", "", result_text).split("<br>") if segment.strip()]
        last_result = split_result
        is_valid, error_message = validate_split_result(
            original_text=text,
            split_result=split_result,
            max_word_count_cjk=max_word_count_cjk,
            max_word_count_english=max_word_count_english,
        )
        if is_valid:
            return split_result

        logger.warning("Split validation failed (attempt %s): %s", step + 1, error_message)
        if "Content changed during segmentation" in error_message:
            logger.warning("Split content diff (attempt %s): %s", step + 1, _describe_content_change(text, split_result))
        messages.append({"role": "assistant", "content": result_text})
        messages.append(
            {
                "role": "user",
                "content": (
                    f"Validation failed: {error_message}\n"
                    "Fix the segmentation by changing `<br>` positions only.\n"
                    "Do NOT add, remove, replace, rewrite, normalize, or reorder any text.\n"
                    "Do NOT remove trailing partial words, conjunctions, or fragments.\n"
                    "Do NOT add punctuation.\n"
                    "Do NOT complete partial words or partial sentences.\n"
                    "Keep every original token exactly as-is and return the COMPLETE corrected text using `<br>` separators only."
                ),
            }
        )

    if (
        last_result is not None
        and words is not None
        and _is_length_only_validation_error(error_message if last_result is not None else "")
        and _preserves_original_text(text, last_result)
    ):
        try:
            map_sentences_to_words(words, last_result)
            logger.warning(
                "Accepting final split result despite length overflow because content is preserved and word alignment still succeeds."
            )
            return last_result
        except RuntimeError:
            pass

    candidate_output: Optional[ASRData] = None
    if last_result is not None and words is not None:
        try:
            candidate_output = ASRData(map_sentences_to_words(words, last_result))
        except RuntimeError:
            candidate_output = None

    raise SubtitleSplitValidationError(
        f"Subtitle splitting failed validation: {error_message if last_result is not None else 'empty result'}",
        candidate_output=candidate_output,
        candidate_segments=last_result,
        original_text=text,
    )


def validate_split_result(
    *,
    original_text: str,
    split_result: Sequence[str],
    max_word_count_cjk: int,
    max_word_count_english: int,
) -> Tuple[bool, str]:
    if not split_result:
        return False, "No segments found."

    text_is_cjk = is_mainly_cjk(original_text)
    merged = "".join(split_result) if text_is_cjk else " ".join(split_result)
    original_norm = normalize_text_for_match(original_text)
    merged_norm = normalize_text_for_match(merged)

    if original_norm != merged_norm:
        similarity = difflib.SequenceMatcher(None, original_norm, merged_norm).ratio()
        return False, f"Content changed during segmentation (similarity={similarity:.2%})."

    max_allowed = max_word_count_cjk if text_is_cjk else max_word_count_english
    for idx, segment in enumerate(split_result, 1):
        if count_words(segment) > max_allowed:
            return False, f"Segment {idx} exceeds length limit {max_allowed}: {segment[:40]}"

    return True, ""


def _preserves_original_text(original_text: str, split_result: Sequence[str]) -> bool:
    text_is_cjk = is_mainly_cjk(original_text)
    merged = "".join(split_result) if text_is_cjk else " ".join(split_result)
    return normalize_text_for_match(original_text) == normalize_text_for_match(merged)


def _is_length_only_validation_error(error_message: str) -> bool:
    return "exceeds length limit" in (error_message or "")


def _describe_content_change(original_text: str, split_result: Sequence[str]) -> str:
    text_is_cjk = is_mainly_cjk(original_text)
    merged = "".join(split_result) if text_is_cjk else " ".join(split_result)
    original_norm = normalize_text_for_match(original_text)
    merged_norm = normalize_text_for_match(merged)
    matcher = difflib.SequenceMatcher(None, original_norm, merged_norm)

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        orig_start = max(0, i1 - 80)
        orig_end = min(len(original_text), i2 + 80)
        new_start = max(0, j1 - 80)
        new_end = min(len(merged), j2 + 80)
        return (
            f"first_diff={tag}; "
            f"original_snippet={original_text[orig_start:orig_end]!r}; "
            f"reconstructed_snippet={merged[new_start:new_end]!r}"
        )

    return "unable to isolate first diff"


def map_sentences_to_words(words: Sequence[ASRWord], sentences: Sequence[str]) -> List[ASRDataSeg]:
    normalized_words = [normalize_text_for_match(word.text) for word in words]
    cursor = 0
    segments: List[ASRDataSeg] = []

    for sentence in sentences:
        target = normalize_text_for_match(sentence)
        if not target:
            continue

        start = cursor
        current = ""
        while cursor < len(words) and len(current) < len(target):
            current += normalized_words[cursor]
            cursor += 1
            if current == target:
                sentence_words = list(words[start:cursor])
                segments.append(
                    ASRDataSeg(
                        text=join_word_texts(sentence_words),
                        start_time=sentence_words[0].start_time,
                        end_time=sentence_words[-1].end_time,
                        words=sentence_words,
                    )
                )
                break

        if current != target:
            raise RuntimeError(f"Failed to align segmented sentence back to words: {sentence[:80]}")

    if cursor != len(words):
        remaining = list(words[cursor:])
        if remaining:
            segments.append(
                ASRDataSeg(
                    text=join_word_texts(remaining),
                    start_time=remaining[0].start_time,
                    end_time=remaining[-1].end_time,
                    words=remaining,
                )
            )
    return segments


def build_split_stats(before: ASRData, after: ASRData) -> Dict[str, Any]:
    return {
        "word_count": count_words(before.to_plain_text()),
        "original_segments": len(before.segments),
        "final_segments": len(after.segments),
    }
