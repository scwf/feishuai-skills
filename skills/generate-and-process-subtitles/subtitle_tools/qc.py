"""Post-split semantic orphan checks. Flag for review; do not auto-merge."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from .data import ASRData, ASRDataSeg


SHORT_WORD_LIMIT = 3
SHORT_DURATION_MS = 800
VIEWER_SHORT_DURATION_MS = 1000
LONG_PAUSE_GAP_MS = 1500
CONTINUATION_MAX_GAP_MS = 500
DUPLICATE_SUFFIX_MAX_WORDS = 6
DUPLICATE_SUFFIX_MAX_DURATION_MS = 1500
SEAM_TOLERANCE_MS = 20
DEFAULT_MAX_WORD_COUNT_ENGLISH = 21
DEFAULT_MAX_DISPLAY_CHARS_ENGLISH = 79
APPROVABLE_SHORT_REASONS = {
    "ambiguous_short_dependent_fragment",
    "chunk_seam_fragment",
    "short_fragment",
}
HANGING_ENDINGS = {
    "a",
    "an",
    "and",
    "as",
    "at",
    "by",
    "for",
    "from",
    "if",
    "in",
    "into",
    "of",
    "on",
    "or",
    "our",
    "the",
    "to",
    "with",
    "my",
    "your",
    "their",
    "its",
    "his",
    "her",
}
ALWAYS_HANGING_ENDINGS = {
    "a",
    "an",
    "and",
    "my",
    "or",
    "our",
    "the",
    "their",
    "its",
    "your",
}
HANGING_AUXILIARY_CONTRACTIONS = {
    "he'd",
    "he'll",
    "he's",
    "i'd",
    "i'll",
    "i'm",
    "i've",
    "it'd",
    "it'll",
    "it's",
    "she'd",
    "she'll",
    "she's",
    "they'd",
    "they'll",
    "they're",
    "they've",
    "we'd",
    "we'll",
    "we're",
    "we've",
    "you'd",
    "you'll",
    "you're",
    "you've",
}
RELATIVE_CLAUSE_ENDINGS = {
    "that",
    "when",
    "where",
    "which",
    "who",
    "whom",
    "whose",
}
READABLE_CLAUSE_OPENERS = {
    "although",
    "because",
    "between",
    "that",
    "unless",
    "when",
    "where",
    "which",
    "while",
}
INDEPENDENT_TO_OPENINGS = {
    ("to", "be", "clear"),
    ("to", "be", "fair"),
    ("to", "be", "honest"),
    ("to", "be", "sure"),
}
INDEPENDENT_TO_DISCOURSE_VERBS = {
    "begin",
    "clarify",
    "conclude",
    "continue",
    "explain",
    "illustrate",
    "recap",
    "start",
    "summarize",
}
TO_COMPLEMENT_BASE_VERBS = {
    "aim",
    "hope",
    "intend",
    "need",
    "plan",
    "try",
    "want",
}
TO_COMPLEMENT_FINITE_OR_PAST_VERBS = {
    "aimed",
    "aims",
    "hoped",
    "hopes",
    "intended",
    "intends",
    "needed",
    "needs",
    "planned",
    "plans",
    "tried",
    "tries",
    "wanted",
    "wants",
}
TO_COMPLEMENT_GERUNDS = {
    "aiming",
    "hoping",
    "intending",
    "needing",
    "planning",
    "trying",
    "wanting",
}
NOMINAL_PREDECESSORS = {
    "a",
    "an",
    "any",
    "her",
    "his",
    "its",
    "my",
    "no",
    "our",
    "some",
    "that",
    "the",
    "their",
    "this",
    "your",
}
COPULAR_WORDS = {"am", "are", "is", "was", "were"}
TO_COMPLEMENT_AUXILIARIES = {
    "am",
    "are",
    "is",
    "i'm",
    "it's",
    "they're",
    "was",
    "been",
    "had",
    "has",
    "have",
    "we're",
    "were",
    "you're",
}
GERUND_CONTROL_VERBS = {
    "began",
    "begin",
    "begins",
    "continue",
    "continued",
    "continues",
    "keep",
    "keeps",
    "kept",
    "resume",
    "resumed",
    "resumes",
    "start",
    "started",
    "starts",
    "stop",
    "stopped",
    "stops",
}
SUBJECT_PRONOUNS = {"he", "i", "it", "she", "they", "we", "you"}
SUBJECT_AUX_CONTRACTIONS = {"i'm", "it's", "they're", "we're", "you're"}
CLAUSE_CLOSERS = {"all", "anything", "everything", "nothing", "something", "what"}
LEADING_ADJUNCTS = {
    "again",
    "currently",
    "eventually",
    "finally",
    "first",
    "fortunately",
    "generally",
    "here",
    "now",
    "often",
    "perhaps",
    "sometimes",
    "then",
    "today",
    "tomorrow",
    "ultimately",
    "usually",
    "yesterday",
}
NOUN_SUBJECT_BREAKERS = CLAUSE_CLOSERS | {
    "although",
    "as",
    "because",
    "if",
    "that",
    "there",
    "though",
    "unless",
    "when",
    "where",
    "which",
    "while",
    "who",
    "whom",
    "whose",
}
TRAILING_FILLER_SEQUENCES = (
    ("you", "know"),
    ("i", "mean"),
    ("you", "see"),
    ("right",),
    ("actually",),
    ("uh",),
    ("um",),
)
HANGING_MODIFIER_PREDECESSORS = {
    "a",
    "an",
    "any",
    "for",
    "many",
    "of",
    "other",
    "several",
    "some",
    "such",
    "the",
    "various",
    "with",
}
COMPLETE_OTHER_PREDECESSORS = {"any", "each", "no", "one", "some", "the"}
OK_SHORT_UTTERANCES = {
    "ah",
    "alright",
    "bye",
    "correct",
    "exactly",
    "good",
    "got it",
    "great",
    "hello",
    "hi",
    "hmm",
    "indeed",
    "no",
    "nope",
    "oh",
    "ok",
    "okay",
    "please",
    "right",
    "sorry",
    "sure",
    "thanks",
    "thank you",
    "uh",
    "um",
    "wait",
    "well",
    "what",
    "wow",
    "yeah",
    "yep",
    "yes",
    "yup",
}
WORD_RE = re.compile(r"[A-Za-z0-9]+(?:['’][A-Za-z0-9]+)?", re.UNICODE)
TERMINAL_PUNCT_RE = re.compile(r"""[.!?…。！？]["')\]”’）》】」』〕〉》]*$""")
BOUNDARY_PUNCT_RE = re.compile(r"""[.!?,;:…。！？，；：]["')\]”’）》】」』〕〉》]*$""")
CJK_RE = re.compile(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]")
CJK_HANGING_SHORTS = {
    "与",
    "为",
    "以及",
    "从",
    "但",
    "和",
    "因为",
    "在",
    "地",
    "如果",
    "得",
    "把",
    "所以",
    "或",
    "是因为",
    "然后",
    "由",
    "的",
    "而",
    "给",
    "被",
    "向",
    "以",
}
OK_SHORT_CJK_UTTERANCES = {
    "不是",
    "不行",
    "再见",
    "可以",
    "好的",
    "好",
    "对",
    "对的",
    "当然",
    "明白",
    "明白了",
    "是的",
    "没错",
    "知道了",
    "谢谢",
    "你好",
    "はい",
    "いいえ",
    "ありがとう",
    "네",
    "아니요",
    "감사합니다",
}
SRT_TIMING_RE = re.compile(
    r"^(\d{2,}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*"
    r"(\d{2,}):(\d{2}):(\d{2})[,.](\d{3})(?:\s+.*)?$"
)


class ApprovalValidationError(ValueError):
    """Raised when an approval entry does not exactly match an approvable cue."""


def normalize_seam_times(values: Sequence[int]) -> list[int]:
    normalized: list[int] = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError("Seam times must be non-negative integers.")
        normalized.append(value)
    return sorted(normalized)


def inspect_subtitle_path(
    path: Path,
    *,
    bilingual: bool = False,
    english_line: str = "last",
    seam_times_ms: Optional[Sequence[int]] = None,
    approved_cues: Optional[Dict[int, Dict[str, Any]]] = None,
    max_word_count_english: int = DEFAULT_MAX_WORD_COUNT_ENGLISH,
    max_display_chars_english: int = DEFAULT_MAX_DISPLAY_CHARS_ENGLISH,
) -> Dict[str, Any]:
    asr_data = parse_srt_strict(Path(path).read_text(encoding="utf-8-sig"))
    return inspect_asr_data(
        asr_data,
        bilingual=bilingual,
        english_line=english_line,
        seam_times_ms=seam_times_ms,
        approved_cues=approved_cues,
        source_path=str(Path(path).resolve()),
        max_word_count_english=max_word_count_english,
        max_display_chars_english=max_display_chars_english,
    )


@dataclass(frozen=True)
class CueContext:
    cue: int
    segment: ASRDataSeg
    text: str
    duration_ms: int
    word_count: int
    previous_segment: Optional[ASRDataSeg]
    previous_text: str
    next_text: str
    gap_before_ms: Optional[int]
    gap_after_ms: Optional[int]


def build_cue_context(
    asr_data: ASRData,
    index: int,
    *,
    bilingual: bool,
    english_line: str,
) -> CueContext:
    segment = asr_data.segments[index]
    previous_segment = asr_data.segments[index - 1] if index > 0 else None
    next_segment = asr_data.segments[index + 1] if index + 1 < len(asr_data.segments) else None
    previous_text = (
        english_text(previous_segment, bilingual=bilingual, english_line=english_line)
        if previous_segment is not None
        else ""
    )
    next_text = (
        english_text(next_segment, bilingual=bilingual, english_line=english_line)
        if next_segment is not None
        else ""
    )
    text = english_text(segment, bilingual=bilingual, english_line=english_line)
    return CueContext(
        cue=index + 1,
        segment=segment,
        text=text,
        duration_ms=max(0, segment.end_time - segment.start_time),
        word_count=semantic_word_count(text),
        previous_segment=previous_segment,
        previous_text=previous_text,
        next_text=next_text,
        gap_before_ms=(
            segment.start_time - previous_segment.end_time
            if previous_segment is not None
            else None
        ),
        gap_after_ms=(
            next_segment.start_time - segment.end_time
            if next_segment is not None
            else None
        ),
    )


def classify_cue_context(
    cue: CueContext,
    *,
    seams: Sequence[int],
    max_word_count_english: int,
    max_display_chars_english: int,
) -> tuple[List[str], bool, bool]:
    reasons: List[str] = []
    last_token = last_word_token(cue.text)
    last = last_token.lower()
    lowercase_continuation = next_starts_lower(cue.next_text)
    uppercase_or_numeric_continuation = next_starts_upper_or_number(cue.next_text)
    next_tokens = normalized_word_tokens(cue.next_text)
    hanging = (
        last in HANGING_ENDINGS
        and not is_uppercase_label(last_token)
        and (
            last in ALWAYS_HANGING_ENDINGS
            or not has_terminal_punctuation(cue.text)
            or lowercase_continuation
        )
    )
    if hanging:
        reasons.append("hanging_function_word")
    if last in HANGING_AUXILIARY_CONTRACTIONS:
        reasons.append("hanging_auxiliary_contraction")
    length_wrap = is_english_length_wrap(
        cue.text,
        max_word_count_english=max_word_count_english,
        max_display_chars_english=max_display_chars_english,
    )
    if lowercase_continuation and (has_terminal_punctuation(cue.text) or not length_wrap):
        reasons.append("lowercase_continuation")
    if (
        uppercase_or_numeric_continuation
        and cue.gap_after_ms is not None
        and 0 <= cue.gap_after_ms <= CONTINUATION_MAX_GAP_MS
        and not has_boundary_punctuation(cue.text)
        and (not next_tokens or next_tokens[0] != "to")
        and (not next_tokens or next_tokens[0] not in READABLE_CLAUSE_OPENERS)
    ):
        reasons.append("unpunctuated_continuation")
    if display_line_length(cue.text) > max_display_chars_english:
        reasons.append("overlong_display_line")
    if cue.word_count > max_word_count_english:
        reasons.append("overlong_word_count")

    short = cue.word_count < SHORT_WORD_LIMIT and cue.duration_ms < SHORT_DURATION_MS
    few_words = cue.word_count < SHORT_WORD_LIMIT
    allowed_short = is_allowed_short(cue.text)
    if is_cjk_hanging_short(cue.text):
        reasons.append("hanging_cjk_function_word")
    if (
        is_at_chunk_seam(cue.segment, seams, previous_segment=cue.previous_segment)
        and few_words
        and not allowed_short
    ):
        reasons.append("chunk_seam_fragment")
    if short and not allowed_short:
        reasons.append("short_fragment")
    dependent_reason = classify_short_dependent_fragment(
        cue.text,
        previous_text=cue.previous_text,
        duration_ms=cue.duration_ms,
    )
    if dependent_reason:
        reasons.append(dependent_reason)
    if (
        cue.duration_ms <= DUPLICATE_SUFFIX_MAX_DURATION_MS
        and is_adjacent_duplicate_suffix(cue.previous_text, cue.text)
    ):
        reasons.append("adjacent_duplicate_suffix")
    if is_incomplete_before_long_gap(cue.text, gap_after_ms=cue.gap_after_ms):
        reasons.append("incomplete_before_long_gap")
    return list(dict.fromkeys(reasons)), short, allowed_short


def make_context_finding(
    cue: CueContext,
    *,
    severity: str,
    reasons: List[str],
) -> Dict[str, Any]:
    return make_finding(
        cue=cue.cue,
        segment=cue.segment,
        text=cue.text,
        duration_ms=cue.duration_ms,
        word_count=cue.word_count,
        severity=severity,
        reasons=reasons,
        previous_text=cue.previous_text,
        next_text=cue.next_text,
        gap_before_ms=cue.gap_before_ms,
        gap_after_ms=cue.gap_after_ms,
    )


def inspect_asr_data(
    asr_data: ASRData,
    *,
    bilingual: bool = False,
    english_line: str = "last",
    seam_times_ms: Optional[Sequence[int]] = None,
    approved_cues: Optional[Dict[int, Dict[str, Any]]] = None,
    source_path: Optional[str] = None,
    max_word_count_english: int = DEFAULT_MAX_WORD_COUNT_ENGLISH,
    max_display_chars_english: int = DEFAULT_MAX_DISPLAY_CHARS_ENGLISH,
) -> Dict[str, Any]:
    findings: List[Dict[str, Any]] = []
    seams = list(seam_times_ms or [])
    approvals = approved_cues or {}
    consumed_approvals: set[int] = set()

    for index, _segment in enumerate(asr_data.segments):
        cue = build_cue_context(
            asr_data, index, bilingual=bilingual, english_line=english_line
        )
        reasons, short, allowed_short = classify_cue_context(
            cue,
            seams=seams,
            max_word_count_english=max_word_count_english,
            max_display_chars_english=max_display_chars_english,
        )
        approval = approvals.get(cue.cue)
        if (
            reasons
            and approval is not None
            and approval.get("text") == cue.text
            and set(reasons).issubset(APPROVABLE_SHORT_REASONS)
        ):
            approved = make_context_finding(
                cue,
                severity="ok_short",
                reasons=["human_approved_complete_utterance"],
            )
            approved["approval_reason"] = approval.get("reason")
            findings.append(approved)
            consumed_approvals.add(cue.cue)
            continue

        if not reasons:
            if short and allowed_short:
                findings.append(
                    make_context_finding(
                        cue,
                        severity="ok_short",
                        reasons=["allowed_short_utterance"],
                    )
                )
            continue

        findings.append(
            make_context_finding(
                cue,
                severity="high_risk",
                reasons=reasons,
            )
        )

    unused_approvals = sorted(set(approvals) - consumed_approvals)
    if unused_approvals:
        raise ApprovalValidationError(
            "Approval entries were not consumed by exact approvable cue matches: "
            + ", ".join(str(cue) for cue in unused_approvals)
        )

    high_risk = [item for item in findings if item["severity"] == "high_risk"]
    ok_short = [item for item in findings if item["severity"] == "ok_short"]
    approved_short = [
        item
        for item in ok_short
        if "human_approved_complete_utterance" in item["reasons"]
    ]
    review_required = bool(high_risk)
    default_limits = {
        "max_words_en": DEFAULT_MAX_WORD_COUNT_ENGLISH,
        "max_display_chars_en": DEFAULT_MAX_DISPLAY_CHARS_ENGLISH,
    }
    effective_limits = {
        "max_words_en": max_word_count_english,
        "max_display_chars_en": max_display_chars_english,
    }
    return {
        "ok": True,
        "action": "qc",
        "status": "review_required" if review_required else "ok",
        "exit_code": 2 if review_required else 0,
        "source_path": source_path,
        "bilingual": bilingual,
        "english_line": english_line if bilingual else "all",
        "cue_count": len(asr_data.segments),
        "high_risk_count": len(high_risk),
        "ok_short_count": len(ok_short),
        "approved_short_count": len(approved_short),
        "seam_times_ms": seams,
        "default_limits": default_limits,
        "effective_limits": effective_limits,
        "limits_relaxed_from_default": (
            max_word_count_english > DEFAULT_MAX_WORD_COUNT_ENGLISH
            or max_display_chars_english > DEFAULT_MAX_DISPLAY_CHARS_ENGLISH
        ),
        "relaxed_limits_authorized": False,
        "policy": (
            "Flag semantic or viewer-facing orphans for review. Do not auto-merge "
            "short cues or delete repeated text without source evidence; Yes./Great. "
            "and similar utterances may be complete. "
            "Do not merge full-length lowercase wraps to pass QC; recut overlong English instead."
        ),
        "findings": findings,
        "review_items": high_risk,
    }


def english_text(
    segment: ASRDataSeg,
    *,
    bilingual: bool,
    english_line: str,
) -> str:
    lines = [line.strip() for line in (segment.text or "").splitlines() if line.strip()]
    if not lines:
        return ""
    if not bilingual or len(lines) == 1:
        return " ".join(lines)
    if english_line == "first":
        candidates = contiguous_english_lines(lines)
        return " ".join(candidates) if candidates else lines[0]
    candidates = contiguous_english_lines(list(reversed(lines)))
    return " ".join(reversed(candidates)) if candidates else lines[-1]


def contiguous_english_lines(lines: Sequence[str]) -> List[str]:
    selected: List[str] = []
    for line in lines:
        if CJK_RE.search(line):
            break
        if re.search(r"[A-Za-z]", line):
            selected.append(line)
            continue
        if selected:
            selected.append(line)
            continue
        break
    return selected


def display_line_length(text: str) -> int:
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    if not lines:
        return 0
    return max(len(line) for line in lines)


def is_english_length_wrap(
    text: str,
    *,
    max_word_count_english: int = DEFAULT_MAX_WORD_COUNT_ENGLISH,
    max_display_chars_english: int = DEFAULT_MAX_DISPLAY_CHARS_ENGLISH,
) -> bool:
    return (
        semantic_word_count(text) >= max_word_count_english
        or display_line_length(text) >= max_display_chars_english
    )


def last_word_token(text: str) -> str:
    tokens = WORD_RE.findall(text or "")
    return tokens[-1] if tokens else ""


def last_word(text: str) -> str:
    return last_word_token(text).lower()


def semantic_word_count(text: str) -> int:
    cjk_count = len(CJK_RE.findall(text or ""))
    non_cjk = CJK_RE.sub(" ", text or "")
    return cjk_count + len(WORD_RE.findall(non_cjk))


def is_uppercase_label(token: str) -> bool:
    return bool(re.fullmatch(r"[A-Z]", token or ""))


def is_allowed_short(text: str) -> bool:
    normalized = " ".join(WORD_RE.findall((text or "").lower()))
    if normalized in OK_SHORT_UTTERANCES:
        return True
    if not CJK_RE.search(text or "") or not has_terminal_punctuation(text):
        return False
    cjk_text = "".join(CJK_RE.findall(text or ""))
    return cjk_text in OK_SHORT_CJK_UTTERANCES


def normalized_word_tokens(text: str) -> List[str]:
    return [token.lower().replace("’", "'") for token in WORD_RE.findall(text or "")]


def is_short_dependent_fragment(
    text: str,
    *,
    previous_text: str,
    duration_ms: int,
) -> bool:
    return bool(
        classify_short_dependent_fragment(
            text,
            previous_text=previous_text,
            duration_ms=duration_ms,
        )
    )


def classify_short_dependent_fragment(
    text: str,
    *,
    previous_text: str,
    duration_ms: int,
) -> Optional[str]:
    if duration_ms > VIEWER_SHORT_DURATION_MS or is_allowed_short(text):
        return None
    tokens = normalized_word_tokens(text)
    if not tokens:
        return None
    if tokens[0] == "to":
        if has_terminal_punctuation(previous_text) and is_independent_to_opening(
            text, tokens
        ):
            return None
        previous_stripped = (previous_text or "").rstrip()
        if is_independent_to_opening(text, tokens):
            if previous_stripped.endswith((";", ":")):
                return None
            if previous_stripped.endswith(("—", "–")):
                return "ambiguous_short_dependent_fragment"
        previous_for_evidence = re.sub(
            r"\s*(?:\([^()]{1,80}\)|\[[^\[\]]{1,80}\])\s*[.!?]?\s*$",
            "",
            previous_text or "",
        ).rstrip(", ")
        previous_tokens = strip_trailing_fillers(
            normalized_word_tokens(previous_for_evidence)
        )
        if not previous_tokens:
            return None
        evidence = previous_to_complement_evidence(previous_tokens)
        if evidence is None:
            trailing_parenthetical = split_trailing_parenthetical(previous_text)
            prefix, suffix_tokens = trailing_parenthetical or ("", [])
            if is_short_parenthetical_suffix(suffix_tokens):
                prefix_tokens = normalized_word_tokens(prefix)
                prefix_evidence = previous_to_complement_evidence(prefix_tokens)
                if prefix_evidence is not None:
                    previous_tokens = prefix_tokens
                    evidence = prefix_evidence
        if evidence is not None and is_independent_to_opening(text, tokens):
            if "how" in previous_tokens:
                return None
            if has_pronominal_subject(previous_tokens):
                return (
                    "short_dependent_fragment"
                    if evidence == "hard"
                    else "ambiguous_short_dependent_fragment"
                )
            return "ambiguous_short_dependent_fragment"
        if evidence == "hard":
            return "short_dependent_fragment"
        if is_independent_to_opening(text, tokens):
            return None
        if evidence == "ambiguous":
            return "ambiguous_short_dependent_fragment"
        if len(tokens) >= 3 and tokens[:2] == ["to", "the"] and has_terminal_punctuation(text):
            return None
        return None
    if next_starts_lower(text):
        return "short_dependent_fragment"
    if (
        last_word(previous_text) in RELATIVE_CLAUSE_ENDINGS
        and not has_terminal_punctuation(previous_text)
    ):
        return "short_dependent_fragment"
    return None


def is_adjacent_duplicate_suffix(previous_text: str, text: str) -> bool:
    previous_tokens = normalized_word_tokens(previous_text)
    tokens = normalized_word_tokens(text)
    if not 2 <= len(tokens) <= DUPLICATE_SUFFIX_MAX_WORDS:
        return False
    if len(previous_tokens) < len(tokens):
        return False
    return previous_tokens[-len(tokens) :] == tokens


def is_independent_to_opening(text: str, tokens: Sequence[str]) -> bool:
    if any(
        list(tokens[: len(opening)]) == list(opening)
        for opening in INDEPENDENT_TO_OPENINGS
    ):
        return True
    prefix = (text or "").split(",", 1)[0]
    prefix_tokens = normalized_word_tokens(prefix)
    return (
        "," in (text or "")
        and len(prefix_tokens) == 2
        and prefix_tokens[0] == "to"
        and prefix_tokens[1] in INDEPENDENT_TO_DISCOURSE_VERBS
    )


def is_short_parenthetical_suffix(tokens: Sequence[str]) -> bool:
    if not tokens or len(tokens) > 6:
        return False
    first = tokens[0]
    return bool(
        first in SUBJECT_PRONOUNS
        or first in {"as", "in", "of", "or", "perhaps", "possibly", "probably"}
        or first.endswith("ly")
    )


def split_trailing_parenthetical(text: str) -> Optional[tuple[str, List[str]]]:
    separators = list(re.finditer(r"\s*(?:,|;|:|—|–)\s*", text or ""))
    if not separators:
        return None
    separator = separators[-1]
    prefix = (text or "")[: separator.start()].rstrip()
    suffix_tokens = normalized_word_tokens((text or "")[separator.end() :])
    return prefix, suffix_tokens


def has_pronominal_subject(tokens: Sequence[str]) -> bool:
    if not tokens:
        return False
    last = tokens[-1]
    if last in TO_COMPLEMENT_BASE_VERBS | TO_COMPLEMENT_FINITE_OR_PAST_VERBS:
        return bool(
            tokens[0] in SUBJECT_PRONOUNS
            or (len(tokens) >= 2 and tokens[-2] in SUBJECT_PRONOUNS)
        )
    return any(token in SUBJECT_PRONOUNS for token in tokens[-5:-1])


def strip_trailing_fillers(tokens: Sequence[str]) -> List[str]:
    stripped = list(tokens)
    changed = True
    while stripped and changed:
        changed = False
        for filler in TRAILING_FILLER_SEQUENCES:
            if len(stripped) >= len(filler) and tuple(stripped[-len(filler) :]) == filler:
                stripped = stripped[: -len(filler)]
                changed = True
                break
    return stripped


def previous_expects_to_complement(tokens: Sequence[str]) -> bool:
    return previous_to_complement_evidence(tokens) == "hard"


def previous_to_complement_evidence(tokens: Sequence[str]) -> Optional[str]:
    if not tokens:
        return None
    tokens = strip_trailing_fillers(tokens)
    if not tokens:
        return None
    last = tokens[-1]
    previous = tokens[-2] if len(tokens) >= 2 else ""
    if last == "plan" and len(tokens) >= 2 and tokens[0] in NOMINAL_PREDECESSORS:
        noun_head = tokens[-2]
        if len(tokens) != 3 or not noun_head.endswith("s"):
            return None
    if previous in NOMINAL_PREDECESSORS:
        return None
    if (
        last in TO_COMPLEMENT_BASE_VERBS
        and len(tokens) >= 3
        and "there" in tokens[-4:-1]
        and any(token in COPULAR_WORDS for token in tokens[-4:-1])
    ):
        return None
    if (
        last in TO_COMPLEMENT_FINITE_OR_PAST_VERBS
        and len(tokens) >= 3
        and tokens[0] == "there"
        and tokens[1] in COPULAR_WORDS
    ):
        return None
    if (
        len(tokens) >= 3
        and tokens[-2] in SUBJECT_PRONOUNS
        and tokens[-3] in CLAUSE_CLOSERS
    ):
        return None
    if last in TO_COMPLEMENT_BASE_VERBS | TO_COMPLEMENT_FINITE_OR_PAST_VERBS:
        if len(tokens) == 2:
            return "hard"
        if tokens[0] in SUBJECT_PRONOUNS:
            return "hard"
        if len(tokens) >= 2 and tokens[-2] in SUBJECT_PRONOUNS:
            leading = tokens[:-2]
            if leading and (
                all(token in LEADING_ADJUNCTS for token in leading)
                or all(token.endswith("ly") for token in leading)
                or tuple(leading)
                in {("in", "fact"), ("as", "a", "result"), ("of", "course")}
            ):
                return "hard"
            return "ambiguous"
        subject_tokens = tokens[:-1]
        subject_breakers = [
            token
            for index, token in enumerate(subject_tokens)
            if token in NOUN_SUBJECT_BREAKERS
            and token != "all"
        ]
        if (
            len(subject_tokens) >= 2
            and not subject_breakers
        ):
            return "hard"
        return None
    if last in ({"going"} | TO_COMPLEMENT_GERUNDS):
        if "how" in tokens[-5:-1] and any(
            token in TO_COMPLEMENT_AUXILIARIES for token in tokens[-4:-1]
        ):
            return "ambiguous"
        if last == "going" and previous in TO_COMPLEMENT_AUXILIARIES:
            return "hard"
        if (
            last in TO_COMPLEMENT_GERUNDS
            and previous in {"am", "are", "is", "was", "were"}
            and len(tokens) >= 4
            and not any(token in NOUN_SUBJECT_BREAKERS for token in tokens[:-2])
        ):
            return "hard"
        if previous in SUBJECT_AUX_CONTRACTIONS:
            return "hard"
        if previous in GERUND_CONTROL_VERBS:
            control_subject = tokens[:-2]
            if any(token in SUBJECT_PRONOUNS for token in control_subject):
                return "hard"
            if (
                len(control_subject) >= 2
                and not any(
                    token in NOUN_SUBJECT_BREAKERS and token != "all"
                    for token in control_subject
                )
            ):
                return "hard"
            return None
        auxiliary_window = tokens[-5:-1]
        if (
            (
                any(token in SUBJECT_PRONOUNS for token in auxiliary_window)
                or len(tokens[:-1]) >= 2
            )
            and any(token in TO_COMPLEMENT_AUXILIARIES for token in auxiliary_window)
            and not any(
                token in NOUN_SUBJECT_BREAKERS and token != "all"
                for token in tokens[:-1]
            )
        ):
            return "hard"
        return None
    return None


def is_incomplete_before_long_gap(text: str, *, gap_after_ms: Optional[int]) -> bool:
    if gap_after_ms is None or gap_after_ms < LONG_PAUSE_GAP_MS:
        return False
    tokens = strip_trailing_fillers(normalized_word_tokens(text))
    if not tokens:
        return False
    trailing_parenthetical = split_trailing_parenthetical(text)
    if trailing_parenthetical is not None:
        prefix, suffix_tokens = trailing_parenthetical
        prefix_tokens = normalized_word_tokens(prefix)
        if (
            is_short_parenthetical_suffix(suffix_tokens)
            and prefix_tokens
            and prefix_tokens[-1] == "other"
        ):
            tokens = prefix_tokens
    last = tokens[-1]
    unfinished_different = (
        last == "different"
        and len(tokens) >= 2
        and tokens[-2] in HANGING_MODIFIER_PREDECESSORS
    )
    unfinished_other = (
        last == "other"
        and len(tokens) >= 2
        and tokens[-2] not in COMPLETE_OTHER_PREDECESSORS
    )
    if unfinished_different or unfinished_other:
        return True
    if has_terminal_punctuation(text):
        return False
    return (
        last in HANGING_ENDINGS
        or last in HANGING_AUXILIARY_CONTRACTIONS
    )


def is_cjk_hanging_short(text: str) -> bool:
    cjk_text = "".join(CJK_RE.findall(text or ""))
    return bool(cjk_text) and cjk_text in CJK_HANGING_SHORTS


def has_terminal_punctuation(text: str) -> bool:
    return bool(TERMINAL_PUNCT_RE.search((text or "").strip()))


def has_boundary_punctuation(text: str) -> bool:
    return bool(BOUNDARY_PUNCT_RE.search((text or "").strip()))


def next_starts_lower(text: str) -> bool:
    stripped = (text or "").lstrip("\"'“‘([{（［【《「『〈 ")
    return bool(stripped) and stripped[0].isalpha() and stripped[0].islower()


def next_starts_upper_or_number(text: str) -> bool:
    stripped = (text or "").lstrip("\"'“‘([{（［【《「『〈 ")
    return bool(
        stripped
        and (stripped[0].isdigit() or (stripped[0].isalpha() and stripped[0].isupper()))
    )


def is_at_chunk_seam(
    segment: ASRDataSeg,
    seam_times_ms: Iterable[int],
    *,
    previous_segment: Optional[ASRDataSeg] = None,
) -> bool:
    for seam in seam_times_ms:
        if abs(segment.end_time - seam) <= SEAM_TOLERANCE_MS:
            return True
        if abs(segment.start_time - seam) <= SEAM_TOLERANCE_MS:
            return True
        if (
            previous_segment is not None
            and abs(previous_segment.end_time - seam) <= SEAM_TOLERANCE_MS
            and segment.start_time >= seam - SEAM_TOLERANCE_MS
        ):
            return True
    return False


def parse_srt_strict(srt_text: str) -> ASRData:
    normalized = (srt_text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        raise ValueError("Input SRT is empty.")

    segments: List[ASRDataSeg] = []
    for position, block in enumerate(re.split(r"\n\s*\n", normalized), start=1):
        lines = block.splitlines()
        if len(lines) < 3:
            raise ValueError(f"SRT block {position} has fewer than three lines.")
        try:
            cue_number = int(lines[0].strip())
        except ValueError as exc:
            raise ValueError(f"SRT block {position} has an invalid cue number.") from exc
        if cue_number != position:
            raise ValueError(
                f"SRT block {position} has cue number {cue_number}; expected {position}."
            )

        match = SRT_TIMING_RE.fullmatch(lines[1].strip())
        if not match:
            raise ValueError(f"SRT block {position} has an invalid timing line.")
        values = [int(value) for value in match.groups()]
        start_ms = srt_timestamp_to_ms(*values[:4], block_position=position)
        end_ms = srt_timestamp_to_ms(*values[4:], block_position=position)

        text = "\n".join(lines[2:]).strip()
        if not text:
            raise ValueError(f"SRT block {position} has no subtitle text.")
        segments.append(ASRDataSeg(text, start_ms, end_ms))

    validate_asr_timeline(segments)
    return ASRData(segments)


def validate_asr_timeline(segments: Sequence[ASRDataSeg]) -> None:
    previous_start_ms: Optional[int] = None
    previous_end_ms: Optional[int] = None
    for position, segment in enumerate(segments, start=1):
        start_ms = segment.start_time
        end_ms = segment.end_time
        if end_ms <= start_ms:
            raise ValueError(f"SRT block {position} must have positive duration.")
        if previous_start_ms is not None and start_ms < previous_start_ms:
            raise ValueError(f"SRT block {position} starts before the preceding cue.")
        if previous_end_ms is not None and start_ms < previous_end_ms:
            raise ValueError(f"SRT block {position} overlaps the preceding cue.")
        previous_start_ms = start_ms
        previous_end_ms = end_ms


def srt_timestamp_to_ms(
    hours: int,
    minutes: int,
    seconds: int,
    milliseconds: int,
    *,
    block_position: int,
) -> int:
    if minutes >= 60 or seconds >= 60:
        raise ValueError(f"SRT block {block_position} has an out-of-range timestamp.")
    return hours * 3_600_000 + minutes * 60_000 + seconds * 1000 + milliseconds


def make_finding(
    *,
    cue: int,
    segment: ASRDataSeg,
    text: str,
    duration_ms: int,
    word_count: int,
    severity: str,
    reasons: Sequence[str],
    previous_text: str = "",
    next_text: str = "",
    gap_before_ms: Optional[int] = None,
    gap_after_ms: Optional[int] = None,
) -> Dict[str, Any]:
    return {
        "cue": cue,
        "start_ms": segment.start_time,
        "end_ms": segment.end_time,
        "start_timestamp": ms_to_srt_timestamp(segment.start_time),
        "end_timestamp": ms_to_srt_timestamp(segment.end_time),
        "duration_ms": duration_ms,
        "text": text,
        "word_count": word_count,
        "previous_cue": cue - 1 if previous_text else None,
        "previous_text": previous_text or None,
        "next_cue": cue + 1 if next_text else None,
        "next_text": next_text or None,
        "gap_before_ms": gap_before_ms,
        "gap_after_ms": gap_after_ms,
        "severity": severity,
        "reasons": list(reasons),
    }


def ms_to_srt_timestamp(value: int) -> str:
    hours, remainder = divmod(value, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, milliseconds = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"
