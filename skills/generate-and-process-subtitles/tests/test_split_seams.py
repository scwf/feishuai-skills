from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

SKILL_ROOT = Path(__file__).resolve().parents[1]
if str(SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILL_ROOT))

from subtitle_tools.data import ASRData, ASRDataSeg, ASRWord, join_word_texts
from subtitle_tools.split import (
    SubtitleSplitValidationError,
    SubtitleSplitter,
    is_clean_sentence_seam,
    is_sentence_end,
    split_subtitle,
)


def make_words(*tokens: str, start: int = 0, duration: int = 200, gap: int = 0) -> list[ASRWord]:
    words: list[ASRWord] = []
    cursor = start
    for token in tokens:
        words.append(ASRWord(text=token, start_time=cursor, end_time=cursor + duration))
        cursor += duration + gap
    return words


def asr_from_words(words: list[ASRWord]) -> ASRData:
    return ASRData(
        [
            ASRDataSeg(
                text=join_word_texts(words),
                start_time=words[0].start_time,
                end_time=words[-1].end_time,
                words=list(words),
            )
        ]
    )


class SplitSeamTests(unittest.TestCase):
    def test_chunking_prefers_punctuation_near_the_limit(self) -> None:
        words = make_words(*[f"w{i}" for i in range(1, 8)], "done.", "keep", "going", "now")
        splitter = SubtitleSplitter(model="test", chunk_word_limit=10)
        chunks = splitter._chunk_words(words)

        self.assertEqual(join_word_texts(chunks[0]), join_word_texts(words[:8]))
        self.assertTrue(chunks[0][-1].text.endswith("."))
        self.assertNotEqual(len(chunks[0]), 10)
        self.assertEqual(join_word_texts(chunks[1]), "keep going now")

    def test_our_customers_seam_is_rejoined(self) -> None:
        words = make_words("Please", "help", "our", "customers.")
        mapping = {
            "Please help our": ["Please help our"],
            "customers.": ["customers."],
            "Please help our customers.": ["Please help our customers."],
        }

        def fake_split(text: str, **_kwargs: object) -> list[str]:
            return mapping[text]

        result = split_subtitle(
            asr_from_words(words),
            model="test",
            chunk_word_limit=3,
            split_fn=fake_split,
        )

        self.assertEqual([segment.text for segment in result.segments], ["Please help our customers."])
        self.assertEqual(result.segments[0].start_time, words[0].start_time)
        self.assertEqual(result.segments[0].end_time, words[-1].end_time)
        self.assertEqual([word.text for word in result.segments[0].words], [word.text for word in words])

    def test_singleton_seam_repair_does_not_cascade_across_later_chunks(self) -> None:
        words = make_words("one", "two", "three", "four", "five", "six.")
        failures: list[dict[str, object]] = []

        def fake_split(text: str, **_kwargs: object) -> list[str]:
            mapping = {
                "one two": ["one two"],
                "three four": ["three four"],
                "five six.": ["five six."],
                "one two three four": ["one two three four"],
            }
            return mapping[text]

        result = split_subtitle(
            asr_from_words(words),
            model="test",
            chunk_word_limit=2,
            split_fn=fake_split,
            seam_failures_out=failures,
        )

        self.assertEqual(
            [segment.text for segment in result.segments],
            ["one two three four", "five six."],
        )
        self.assertEqual(failures[0]["reason"], "overlapping_repair_window")
        self.assertEqual(join_word_texts(result.words), join_word_texts(words))

    def test_legal_yes_is_not_merged(self) -> None:
        words = make_words("That", "is", "correct.", "Yes.", "We", "continue")
        mapping = {
            "That is correct.": ["That is correct."],
            "Yes. We continue": ["Yes.", "We continue"],
        }

        def fake_split(text: str, **_kwargs: object) -> list[str]:
            if text in mapping:
                return mapping[text]
            self.fail(f"unexpected seam window {text!r}")

        result = split_subtitle(
            asr_from_words(words),
            model="test",
            chunk_word_limit=3,
            split_fn=fake_split,
        )

        self.assertEqual(
            [segment.text for segment in result.segments],
            ["That is correct.", "Yes.", "We continue"],
        )
        self.assertTrue(is_clean_sentence_seam(result.segments[0], result.segments[1]))

    def test_cjk_terminal_punctuation_is_a_clean_sentence_seam(self) -> None:
        left = ASRDataSeg("已经完成。", 0, 1000)
        right = ASRDataSeg("继续下一步。", 1000, 2000)

        self.assertTrue(is_sentence_end(left.text))
        self.assertTrue(is_sentence_end("已经完成。”"))
        self.assertTrue(is_clean_sentence_seam(left, right))

    def test_quoted_lowercase_continuation_is_not_a_clean_seam(self) -> None:
        left = ASRDataSeg("This step is complete.", 0, 1000)
        lowercase = ASRDataSeg("“because more work remains.”", 1000, 2000)
        uppercase = ASRDataSeg("“Next we continue.”", 1000, 2000)

        self.assertFalse(is_clean_sentence_seam(left, lowercase))
        self.assertTrue(is_clean_sentence_seam(left, uppercase))

    def test_trailing_and_is_not_dropped_when_repair_changes_text(self) -> None:
        words = make_words("We", "waited", "And", "then", "left.")
        failures: list[dict[str, object]] = []
        mapping = {
            "We waited And": ["We waited", "And"],
            "then left.": ["then left."],
            "And then left.": ["then left."],
        }

        def fake_split(text: str, **_kwargs: object) -> list[str]:
            return mapping[text]

        result = split_subtitle(
            asr_from_words(words),
            model="test",
            chunk_word_limit=3,
            split_fn=fake_split,
            seam_failures_out=failures,
        )

        self.assertEqual(join_word_texts(result.words), join_word_texts(words))
        self.assertIn("And", [segment.text for segment in result.segments])
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0]["reason"], "split_failed")
        self.assertEqual(failures[0]["left_text"], "And")

    def test_successful_seam_repair_keeps_trailing_function_word(self) -> None:
        words = make_words("We", "waited", "And", "then", "left.")
        mapping = {
            "We waited And": ["We waited", "And"],
            "then left.": ["then left."],
            "And then left.": ["And then left."],
        }

        def fake_split(text: str, **_kwargs: object) -> list[str]:
            return mapping[text]

        result = split_subtitle(
            asr_from_words(words),
            model="test",
            chunk_word_limit=3,
            split_fn=fake_split,
        )

        self.assertEqual([segment.text for segment in result.segments], ["We waited", "And then left."])
        self.assertEqual(join_word_texts(result.words), join_word_texts(words))
        self.assertEqual(result.segments[-1].start_time, words[2].start_time)
        self.assertEqual(result.segments[-1].end_time, words[-1].end_time)

    def test_seam_times_are_emitted_at_chunk_boundaries(self) -> None:
        words = make_words("Please", "help", "our", "customers.")
        mapping = {
            "Please help our": ["Please help our"],
            "customers.": ["customers."],
            "Please help our customers.": ["Please help our customers."],
        }
        seams: list[int] = []

        def fake_split(text: str, **_kwargs: object) -> list[str]:
            return mapping[text]

        split_subtitle(
            asr_from_words(words),
            model="test",
            chunk_word_limit=3,
            split_fn=fake_split,
            seam_times_out=seams,
        )

        self.assertEqual(seams, [words[2].end_time])

    def test_nonmonotonic_word_times_emit_sorted_seam_times(self) -> None:
        words = [
            ASRWord("one", 0, 100),
            ASRWord("two", 100, 200),
            ASRWord("three", 10, 40),
            ASRWord("four", 40, 70),
            ASRWord("five", 70, 90),
            ASRWord("six.", 90, 110),
        ]
        seams: list[int] = []

        def fake_split(text: str, **_kwargs: object) -> list[str]:
            return [text]

        split_subtitle(
            asr_from_words(words),
            model="test",
            chunk_word_limit=2,
            split_fn=fake_split,
            seam_times_out=seams,
        )

        self.assertEqual(seams, [70, 200])
        self.assertEqual(seams, sorted(seams))

    def test_overlapping_repaired_cues_are_rejected(self) -> None:
        splitter = SubtitleSplitter(model="test")
        left = ASRDataSeg("our", 0, 200, words=[ASRWord("our", 0, 200)])
        right = ASRDataSeg("customers.", 200, 400, words=[ASRWord("customers.", 200, 400)])
        overlapping = [
            ASRDataSeg("our", 0, 250, words=[ASRWord("our", 0, 250)]),
            ASRDataSeg("customers.", 200, 400, words=[ASRWord("customers.", 200, 400)]),
        ]
        touching = [
            ASRDataSeg("our", 0, 200, words=[ASRWord("our", 0, 200)]),
            ASRDataSeg("customers.", 200, 400, words=[ASRWord("customers.", 200, 400)]),
        ]
        window_words = left.words + right.words

        self.assertFalse(splitter._seam_window_is_valid(window_words, left, right, overlapping))
        self.assertTrue(splitter._seam_window_is_valid(window_words, left, right, touching))

    def test_zero_duration_repaired_cue_is_rejected(self) -> None:
        splitter = SubtitleSplitter(model="test")
        left = ASRDataSeg("Yes.", 0, 200, words=[ASRWord("Yes.", 0, 200)])
        right = ASRDataSeg("We continue.", 200, 400, words=[ASRWord("We", 200, 300), ASRWord("continue.", 300, 400)])
        zero_duration = [
            ASRDataSeg("Yes.", 0, 0, words=[ASRWord("Yes.", 0, 0)]),
            ASRDataSeg("We continue.", 200, 400, words=[ASRWord("We", 200, 300), ASRWord("continue.", 300, 400)]),
        ]

        self.assertFalse(
            splitter._seam_window_is_valid(left.words + right.words, left, right, zero_duration)
        )

    def test_oversized_repaired_cue_is_rejected(self) -> None:
        words = make_words("one", "two", "three", "four")
        left = ASRDataSeg("one two", 0, 400, words=words[:2])
        right = ASRDataSeg("three four", 400, 800, words=words[2:])
        merged = ASRDataSeg("one two three four", 0, 800, words=words)
        splitter = SubtitleSplitter(model="test", max_word_count_english=3)

        self.assertFalse(
            splitter._seam_window_is_valid(words, left, right, [merged])
        )

    def test_reverse_repaired_cues_are_rejected_before_sorting(self) -> None:
        words = make_words("Later", "sentence.", "Earlier", "now.")
        later = ASRDataSeg(
            "Later sentence.",
            words[2].start_time,
            words[3].end_time,
            words=words[2:],
        )
        earlier = ASRDataSeg(
            "Earlier now.",
            words[0].start_time,
            words[1].end_time,
            words=words[:2],
        )
        splitter = SubtitleSplitter(model="test")

        def fake_split(text: str, **_kwargs: object) -> list[str]:
            return [text]

        splitter.split_fn = fake_split
        with patch.object(splitter, "_repair_seams", return_value=[later, earlier]):
            with self.assertRaises(SubtitleSplitValidationError):
                splitter.split_subtitle(asr_from_words(words))
        wrapped = ASRData([later, earlier])
        self.assertEqual(wrapped.segments[0].text, earlier.text)


if __name__ == "__main__":
    unittest.main()
