"""Post-split semantic orphan checks. Flag for review; do not auto-merge."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from .data import ASRData, ASRDataSeg


SHORT_WORD_LIMIT = 3
SHORT_DURATION_MS = 800
SEAM_TOLERANCE_MS = 20
APPROVABLE_SHORT_REASONS = {"chunk_seam_fragment", "short_fragment"}
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
) -> Dict[str, Any]:
    asr_data = parse_srt_strict(Path(path).read_text(encoding="utf-8-sig"))
    return inspect_asr_data(
        asr_data,
        bilingual=bilingual,
        english_line=english_line,
        seam_times_ms=seam_times_ms,
        approved_cues=approved_cues,
        source_path=str(Path(path).resolve()),
    )


def inspect_asr_data(
    asr_data: ASRData,
    *,
    bilingual: bool = False,
    english_line: str = "last",
    seam_times_ms: Optional[Sequence[int]] = None,
    approved_cues: Optional[Dict[int, Dict[str, Any]]] = None,
    source_path: Optional[str] = None,
) -> Dict[str, Any]:
    findings: List[Dict[str, Any]] = []
    seams = list(seam_times_ms or [])
    approvals = approved_cues or {}
    consumed_approvals: set[int] = set()

    for index, segment in enumerate(asr_data.segments):
        text = english_text(segment, bilingual=bilingual, english_line=english_line)
        duration_ms = max(0, segment.end_time - segment.start_time)
        word_count = semantic_word_count(text)
        reasons: List[str] = []
        last_token = last_word_token(text)
        last = last_token.lower()
        previous_segment = asr_data.segments[index - 1] if index > 0 else None
        next_text = ""
        if index + 1 < len(asr_data.segments):
            next_text = english_text(
                asr_data.segments[index + 1],
                bilingual=bilingual,
                english_line=english_line,
            )

        lowercase_continuation = next_starts_lower(next_text)
        hanging = (
            last in HANGING_ENDINGS
            and not is_uppercase_label(last_token)
            and (
                last in ALWAYS_HANGING_ENDINGS
                or not has_terminal_punctuation(text)
                or lowercase_continuation
            )
        )
        if hanging:
            reasons.append("hanging_function_word")
        if lowercase_continuation:
            reasons.append("lowercase_continuation")

        short = word_count < SHORT_WORD_LIMIT and duration_ms < SHORT_DURATION_MS
        few_words = word_count < SHORT_WORD_LIMIT
        allowed_short = is_allowed_short(text)
        if is_cjk_hanging_short(text):
            reasons.append("hanging_cjk_function_word")
        at_seam = is_at_chunk_seam(
            segment,
            seams,
            previous_segment=previous_segment,
        )
        if at_seam and few_words and not allowed_short:
            reasons.append("chunk_seam_fragment")
        if short and not allowed_short:
            reasons.append("short_fragment")

        approval = approvals.get(index + 1)
        if (
            reasons
            and approval is not None
            and approval.get("text") == text
            and set(reasons).issubset(APPROVABLE_SHORT_REASONS)
        ):
            approved = make_finding(
                cue=index + 1,
                segment=segment,
                text=text,
                duration_ms=duration_ms,
                word_count=word_count,
                severity="ok_short",
                reasons=["human_approved_complete_utterance"],
            )
            approved["approval_reason"] = approval.get("reason")
            findings.append(approved)
            consumed_approvals.add(index + 1)
            continue

        if not reasons:
            if short and allowed_short:
                findings.append(
                    make_finding(
                        cue=index + 1,
                        segment=segment,
                        text=text,
                        duration_ms=duration_ms,
                        word_count=word_count,
                        severity="ok_short",
                        reasons=["allowed_short_utterance"],
                    )
                )
            continue

        unique_reasons = list(dict.fromkeys(reasons))
        findings.append(
            make_finding(
                cue=index + 1,
                segment=segment,
                text=text,
                duration_ms=duration_ms,
                word_count=word_count,
                severity="high_risk",
                reasons=unique_reasons,
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
        "policy": (
            "Flag semantic orphans for review. Do not auto-merge short cues; "
            "Yes./Great. and similar utterances may be complete."
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


def is_cjk_hanging_short(text: str) -> bool:
    cjk_text = "".join(CJK_RE.findall(text or ""))
    return bool(cjk_text) and cjk_text in CJK_HANGING_SHORTS


def has_terminal_punctuation(text: str) -> bool:
    return bool(TERMINAL_PUNCT_RE.search((text or "").strip()))


def next_starts_lower(text: str) -> bool:
    stripped = (text or "").lstrip("\"'“‘([{（［【《「『〈 ")
    return bool(stripped) and stripped[0].isalpha() and stripped[0].islower()


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
) -> Dict[str, Any]:
    return {
        "cue": cue,
        "start_ms": segment.start_time,
        "end_ms": segment.end_time,
        "duration_ms": duration_ms,
        "text": text,
        "word_count": word_count,
        "severity": severity,
        "reasons": list(reasons),
    }
