"""LLM-based subtitle segmentation using word timestamps."""

import difflib
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .data import ASRData, ASRDataSeg, ASRWord, join_word_texts
from .llm import call_llm
from .prompts import get_prompt
from .utils import count_words, is_mainly_cjk, setup_logger


logger = setup_logger("subtitle_splitter")

DEFAULT_CHUNK_WORD_LIMIT = 350
DEFAULT_MAX_WORD_COUNT_CJK = 25
DEFAULT_MAX_WORD_COUNT_ENGLISH = 21
MAX_STEPS = 2


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
) -> ASRData:
    splitter = SubtitleSplitter(
        model=model,
        api_key=api_key,
        base_url=base_url,
        max_word_count_cjk=max_word_count_cjk,
        max_word_count_english=max_word_count_english,
        chunk_word_limit=chunk_word_limit,
        max_retries=max_retries,
    )
    return splitter.split_subtitle(subtitle_data)


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
    ) -> None:
        self.model = model
        self.api_key = api_key
        self.base_url = base_url
        self.max_word_count_cjk = max_word_count_cjk
        self.max_word_count_english = max_word_count_english
        self.chunk_word_limit = chunk_word_limit
        self.max_retries = max_retries

    def split_subtitle(self, subtitle_data: ASRData) -> ASRData:
        if not subtitle_data.has_word_timestamps():
            raise RuntimeError("Subtitle splitting requires word-level timestamps.")

        chunks = self._chunk_words(subtitle_data.words)
        result_segments: List[ASRDataSeg] = []
        for chunk_words in chunks:
            text = join_word_texts(chunk_words)
            sentences = split_by_llm(
                text=text,
                words=chunk_words,
                model=self.model,
                api_key=self.api_key,
                base_url=self.base_url,
                max_word_count_cjk=self.max_word_count_cjk,
                max_word_count_english=self.max_word_count_english,
                max_retries=self.max_retries,
            )
            result_segments.extend(map_sentences_to_words(chunk_words, sentences))
        return ASRData(result_segments)

    def _chunk_words(self, words: Sequence[ASRWord]) -> List[List[ASRWord]]:
        chunks: List[List[ASRWord]] = []
        current: List[ASRWord] = []
        current_count = 0

        for word in words:
            token_weight = max(1, count_words(word.text))
            if current and current_count + token_weight > self.chunk_word_limit:
                chunks.append(current)
                current = []
                current_count = 0
            current.append(word)
            current_count += token_weight

        if current:
            chunks.append(current)
        return chunks


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
        {"role": "user", "content": text},
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
