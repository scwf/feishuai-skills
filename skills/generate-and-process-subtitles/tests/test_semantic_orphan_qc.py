from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

SKILL_ROOT = Path(__file__).resolve().parents[1]
CLI_PATH = SKILL_ROOT / "scripts" / "generate_and_process_subtitles.py"
if str(SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILL_ROOT))

CLI_SPEC = importlib.util.spec_from_file_location("subtitle_cli_for_qc_tests", CLI_PATH)
assert CLI_SPEC and CLI_SPEC.loader
CLI = importlib.util.module_from_spec(CLI_SPEC)
CLI_SPEC.loader.exec_module(CLI)

from subtitle_tools.data import ASRData, ASRDataSeg
from subtitle_tools.qc import ApprovalValidationError, inspect_asr_data, inspect_subtitle_path


def write_srt(path: Path, text: str) -> None:
    path.write_text(text.strip() + "\n", encoding="utf-8")


class SemanticOrphanQcTests(unittest.TestCase):
    def test_customers_fragment_is_high_risk(self) -> None:
        asr_data = ASRData(
            [
                ASRDataSeg("Please help our", 0, 900),
                ASRDataSeg("customers.", 900, 1300),
            ]
        )
        report = inspect_asr_data(asr_data, seam_times_ms=[900])
        self.assertEqual(report["status"], "review_required")
        self.assertEqual(report["exit_code"], 2)
        customers = next(item for item in report["review_items"] if item["text"] == "customers.")
        self.assertEqual(customers["severity"], "high_risk")
        self.assertIn("short_fragment", customers["reasons"])
        self.assertIn("chunk_seam_fragment", customers["reasons"])
        hanging = next(item for item in report["review_items"] if item["text"] == "Please help our")
        self.assertIn("hanging_function_word", hanging["reasons"])

    def test_legal_yes_is_ok_short_not_merged(self) -> None:
        asr_data = ASRData(
            [
                ASRDataSeg("That is correct.", 0, 1200),
                ASRDataSeg("Yes.", 1300, 1600),
                ASRDataSeg("We continue", 1700, 2500),
            ]
        )
        report = inspect_asr_data(asr_data)
        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["high_risk_count"], 0)
        self.assertEqual(report["ok_short_count"], 1)
        self.assertEqual(report["findings"][0]["text"], "Yes.")
        self.assertEqual(report["findings"][0]["severity"], "ok_short")

    def test_legal_yes_at_chunk_seam_stays_ok_short(self) -> None:
        asr_data = ASRData(
            [
                ASRDataSeg("That is correct.", 0, 1200),
                ASRDataSeg("Yes.", 1200, 1500),
                ASRDataSeg("We continue", 1500, 2300),
            ]
        )
        report = inspect_asr_data(asr_data, seam_times_ms=[1200])
        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["high_risk_count"], 0)
        self.assertEqual(report["findings"][0]["text"], "Yes.")
        self.assertEqual(report["findings"][0]["severity"], "ok_short")
        self.assertNotIn("chunk_seam_fragment", report["findings"][0]["reasons"])

    def test_terminal_prepositions_do_not_trigger_hanging_word_qc(self) -> None:
        cases = [
            "Come on.",
            "Who are you with?",
            "This is where I am from.",
        ]
        for text in cases:
            with self.subTest(text=text):
                report = inspect_asr_data(
                    ASRData([ASRDataSeg(text, 0, 1200)])
                )
                self.assertEqual(report["status"], "ok")
                self.assertEqual(report["high_risk_count"], 0)

    def test_terminal_punctuation_does_not_hide_hanging_determiner(self) -> None:
        report = inspect_asr_data(
            ASRData(
                [
                    ASRDataSeg("Please help our.", 0, 1200),
                    ASRDataSeg("Customers around the world.", 1200, 2600),
                ]
            ),
            seam_times_ms=[1200],
        )
        self.assertEqual(report["status"], "review_required")
        first = next(item for item in report["review_items"] if item["cue"] == 1)
        self.assertIn("hanging_function_word", first["reasons"])

    def test_short_cjk_sentence_with_terminal_punctuation_is_ok_short(self) -> None:
        for text in ("好。", "对。"):
            with self.subTest(text=text):
                report = inspect_asr_data(
                    ASRData([ASRDataSeg(text, 0, 400)])
                )
                self.assertEqual(report["status"], "ok")
                self.assertEqual(report["high_risk_count"], 0)
                self.assertEqual(report["ok_short_count"], 1)
                self.assertEqual(report["findings"][0]["severity"], "ok_short")

    def test_unlisted_short_cjk_noun_at_seam_requires_review(self) -> None:
        report = inspect_asr_data(
            ASRData(
                [
                    ASRDataSeg("这是我们的", 0, 1000),
                    ASRDataSeg("客户。", 1000, 1400),
                ]
            ),
            seam_times_ms=[1000],
        )
        self.assertEqual(report["status"], "review_required")
        fragment = next(item for item in report["review_items"] if item["text"] == "客户。")
        self.assertIn("chunk_seam_fragment", fragment["reasons"])

    def test_cjk_function_word_at_seam_is_high_risk(self) -> None:
        report = inspect_asr_data(
            ASRData(
                [
                    ASRDataSeg("这是我们需要", 0, 1000),
                    ASRDataSeg("的。", 1000, 1400),
                ]
            ),
            seam_times_ms=[1000],
        )
        self.assertEqual(report["status"], "review_required")
        fragment = next(item for item in report["review_items"] if item["text"] == "的。")
        self.assertIn("chunk_seam_fragment", fragment["reasons"])

    def test_quoted_cjk_function_word_at_seam_is_high_risk(self) -> None:
        report = inspect_asr_data(
            ASRData(
                [
                    ASRDataSeg("这是我们需要", 0, 1000),
                    ASRDataSeg("“的。”", 1000, 1400),
                ]
            ),
            seam_times_ms=[1000],
        )
        self.assertEqual(report["status"], "review_required")
        fragment = next(item for item in report["review_items"] if item["text"] == "“的。”")
        self.assertEqual(fragment["word_count"], 1)
        self.assertIn("chunk_seam_fragment", fragment["reasons"])
        self.assertIn("hanging_cjk_function_word", fragment["reasons"])

        with self.assertRaises(ApprovalValidationError):
            inspect_asr_data(
                ASRData(
                    [
                        ASRDataSeg("这是我们需要", 0, 1000),
                        ASRDataSeg("“的。”", 1000, 1400),
                    ]
                ),
                seam_times_ms=[1000],
                approved_cues={
                    2: {
                        "text": "“的。”",
                        "reason": "Incorrect attempted waiver.",
                    }
                },
            )

    def test_uppercase_option_label_is_not_an_article(self) -> None:
        report = inspect_asr_data(
            ASRData([ASRDataSeg("Choose option A.", 0, 1200)])
        )
        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["high_risk_count"], 0)

    def test_reviewed_short_utterance_can_clear_the_gate(self) -> None:
        asr_data = ASRData([ASRDataSeg("I agree.", 0, 400)])
        blocked = inspect_asr_data(asr_data)
        self.assertEqual(blocked["status"], "review_required")

        approved = inspect_asr_data(
            asr_data,
            approved_cues={
                1: {
                    "text": "I agree.",
                    "reason": "Confirmed complete in source audio.",
                }
            },
        )
        self.assertEqual(approved["status"], "ok")
        self.assertEqual(approved["exit_code"], 0)
        self.assertEqual(approved["approved_short_count"], 1)
        self.assertIn(
            "human_approved_complete_utterance",
            approved["findings"][0]["reasons"],
        )

    def test_short_approval_cannot_waive_hanging_word(self) -> None:
        with self.assertRaises(ApprovalValidationError):
            inspect_asr_data(
                ASRData([ASRDataSeg("Please help our", 0, 1200)]),
                approved_cues={
                    1: {
                        "text": "Please help our",
                        "reason": "Incorrect attempted waiver.",
                    }
                },
            )

    def test_cli_loads_exact_reviewed_short_approval(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            srt = root / "reviewed.srt"
            approvals = root / "approvals.json"
            write_srt(
                srt,
                """
1
00:00:00,000 --> 00:00:00,400
I agree.
""",
            )
            approvals.write_text(
                json.dumps(
                    {
                        "approved_cues": [
                            {
                                "cue": 1,
                                "text": "I agree.",
                                "reason": "Confirmed complete in source audio.",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            args = CLI.build_parser().parse_args(
                ["qc", str(srt), "--approved-cues-file", str(approvals)]
            )
            result = CLI.run_qc(args)
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["approved_short_count"], 1)

    def test_boolean_cue_number_cannot_approve_cue_one(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            approvals = Path(temp_dir) / "approvals.json"
            approvals.write_text(
                json.dumps(
                    {
                        "approved_cues": [
                            {
                                "cue": True,
                                "text": "I agree.",
                                "reason": "Invalid boolean cue number.",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaises(CLI.SubtitleSkillError) as raised:
                CLI.load_approved_cues_file(approvals)
            self.assertEqual(raised.exception.error_type, "invalid_input")

    def test_stale_or_mismatched_approvals_are_rejected(self) -> None:
        invalid_entries = [
            [
                {
                    "cue": 1,
                    "text": "I agree.",
                    "reason": "Valid current approval.",
                },
                {
                    "cue": 99,
                    "text": "Stale cue.",
                    "reason": "No longer present.",
                },
            ],
            [
                {
                    "cue": 1,
                    "text": "Old text.",
                    "reason": "Text no longer matches.",
                }
            ],
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            srt = root / "reviewed.srt"
            approvals = root / "approvals.json"
            write_srt(
                srt,
                """
1
00:00:00,000 --> 00:00:00,400
I agree.
""",
            )
            for entries in invalid_entries:
                with self.subTest(entries=entries):
                    approvals.write_text(
                        json.dumps({"approved_cues": entries}),
                        encoding="utf-8",
                    )
                    args = CLI.build_parser().parse_args(
                        ["qc", str(srt), "--approved-cues-file", str(approvals)]
                    )
                    with self.assertRaises(CLI.SubtitleSkillError) as raised:
                        CLI.run_qc(args)
                    self.assertEqual(raised.exception.error_type, "invalid_approval")
                    self.assertEqual(raised.exception.step, "validate_input")

    def test_slow_seam_fragment_is_still_high_risk(self) -> None:
        asr_data = ASRData(
            [
                ASRDataSeg("Please help our", 0, 900),
                ASRDataSeg("customers.", 900, 1900),
            ]
        )
        report = inspect_asr_data(asr_data, seam_times_ms=[900])
        self.assertEqual(report["status"], "review_required")
        customers = next(item for item in report["review_items"] if item["text"] == "customers.")
        self.assertIn("chunk_seam_fragment", customers["reasons"])
        self.assertNotIn("short_fragment", customers["reasons"])

    def test_slow_seam_fragment_after_silence_is_still_high_risk(self) -> None:
        asr_data = ASRData(
            [
                ASRDataSeg("We proudly serve", 0, 900),
                ASRDataSeg("customers.", 1300, 2300),
            ]
        )
        report = inspect_asr_data(asr_data, seam_times_ms=[900])
        self.assertEqual(report["status"], "review_required")
        customers = next(item for item in report["review_items"] if item["text"] == "customers.")
        self.assertIn("chunk_seam_fragment", customers["reasons"])
        self.assertNotIn("short_fragment", customers["reasons"])

    def test_long_cue_before_lowercase_continuation_is_high_risk(self) -> None:
        report = inspect_asr_data(
            ASRData(
                [
                    ASRDataSeg("This helps all of our customers", 0, 1500),
                    ASRDataSeg("around the world.", 1500, 2600),
                ]
            ),
            seam_times_ms=[1500],
        )
        self.assertEqual(report["status"], "review_required")
        first = next(item for item in report["review_items"] if item["cue"] == 1)
        self.assertIn("lowercase_continuation", first["reasons"])

    def test_bilingual_english_fragment_is_not_hidden_by_chinese(self) -> None:
        asr_data = ASRData(
            [
                ASRDataSeg("我们为客户提供完整的服务。\ncustomers.", 0, 400),
            ]
        )
        hidden = inspect_asr_data(asr_data, bilingual=False)
        self.assertEqual(hidden["status"], "ok")
        visible = inspect_asr_data(asr_data, bilingual=True)
        self.assertEqual(visible["status"], "review_required")
        self.assertEqual(visible["review_items"][0]["text"], "customers.")

    def test_bilingual_multiline_english_is_checked_as_one_source_text(self) -> None:
        report = inspect_asr_data(
            ASRData(
                [
                    ASRDataSeg(
                        "请帮助我们的客户。\nPlease help our\ncustomers.",
                        0,
                        1200,
                    )
                ]
            ),
            bilingual=True,
        )
        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["high_risk_count"], 0)

    def test_cli_qc_writes_report_and_uses_review_exit_code(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            srt = root / "orphans.srt"
            report_path = root / "qc.json"
            write_srt(
                srt,
                """
1
00:00:00,000 --> 00:00:00,900
Please help our

2
00:00:00,900 --> 00:00:01,300
customers.
""",
            )
            args = CLI.build_parser().parse_args(
                ["qc", str(srt), "--output", str(report_path)]
            )
            result = CLI.run_qc(args)
            self.assertEqual(result["status"], "review_required")
            self.assertEqual(result["exit_code"], 2)
            saved = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["high_risk_count"], 2)

    def test_cli_qc_without_output_uses_atomic_work_report(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            srt = root / "input.srt"
            write_srt(
                srt,
                """
1
00:00:00,000 --> 00:00:01,000
Complete sentence.
""",
            )
            args = CLI.build_parser().parse_args(["qc", str(srt)])
            result = CLI.run_qc(args)
            expected = (
                root
                / CLI.WORK_DIR_NAME
                / CLI.qc_report_filename("input")
            ).resolve()

            self.assertEqual(Path(result["qc_path"]), expected)
            self.assertTrue(expected.is_file())
            self.assertEqual(
                json.loads(expected.read_text(encoding="utf-8"))["status"],
                "ok",
            )
            self.assertEqual(list(expected.parent.glob(".*.tmp")), [])

    def test_default_qc_output_handles_long_input_filename(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            srt = root / f"{'a' * 204}.srt"
            write_srt(
                srt,
                """
1
00:00:00,000 --> 00:00:01,000
Complete sentence.
""",
            )
            args = CLI.build_parser().parse_args(["qc", str(srt)])
            result = CLI.run_qc(args)
            report_path = Path(result["qc_path"])

            self.assertTrue(report_path.is_file())
            self.assertLessEqual(
                len(report_path.name.encode("utf-8")),
                CLI.MAX_QC_STEM_UTF8_BYTES + len(CLI.QC_REPORT_SUFFIX),
            )
            self.assertEqual(list(report_path.parent.glob(".json-*.tmp")), [])

    def test_default_qc_report_names_do_not_collide_after_sanitizing(self) -> None:
        colon_name = CLI.qc_report_filename("a:b")
        question_name = CLI.qc_report_filename("a?b")
        crafted_name = CLI.qc_report_filename(
            colon_name.removesuffix(CLI.QC_REPORT_SUFFIX)
        )

        self.assertNotEqual(colon_name, question_name)
        self.assertNotEqual(colon_name, crafted_name)
        self.assertNotIn(":", colon_name)
        self.assertNotIn("?", question_name)

    def test_existing_work_directory_match_is_case_insensitive(self) -> None:
        input_path = Path("root") / "_SUBTITLE_WORK" / "input.srt"
        output_path = CLI.default_qc_output_path(input_path)

        self.assertEqual(output_path.parent, input_path.parent)

    def test_default_output_is_resolved_before_input_collision_checks(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            srt = root / "input.srt"
            alias_dir = root / "alias"
            actual_dir = root / "actual"
            alias_dir.mkdir()
            actual_dir.mkdir()
            approval_path = actual_dir / "report.json"
            write_srt(
                srt,
                """
1
00:00:00,000 --> 00:00:00,400
I agree.
""",
            )
            approval_path.write_text(
                json.dumps(
                    {
                        "approved_cues": [
                            {
                                "cue": 1,
                                "text": "I agree.",
                                "reason": "Reviewed.",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            before = approval_path.read_bytes()
            noncanonical_output = alias_dir / ".." / "actual" / "report.json"
            args = CLI.build_parser().parse_args(
                ["qc", str(srt), "--approved-cues-file", str(approval_path)]
            )

            with patch.object(
                CLI,
                "default_qc_output_path",
                return_value=noncanonical_output,
            ):
                with self.assertRaises(CLI.SubtitleSkillError) as raised:
                    CLI.run_qc(args)
            self.assertEqual(raised.exception.error_type, "path_collision")
            self.assertEqual(approval_path.read_bytes(), before)

    def test_atomic_json_write_retries_concurrent_windows_replace_conflicts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target = root / "report.json"

            with ThreadPoolExecutor(max_workers=16) as executor:
                futures = [
                    executor.submit(CLI.write_json_atomic, target, {"writer": index})
                    for index in range(50)
                ]
                for future in futures:
                    future.result()

            payload = json.loads(target.read_text(encoding="utf-8"))
            self.assertIn(payload["writer"], range(50))
            self.assertEqual(list(root.glob(".json-*.tmp")), [])

    def test_write_qc_report_lifts_exit_code_and_persists_seams(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            srt = root / "orphans.srt"
            write_srt(
                srt,
                """
1
00:00:00,000 --> 00:00:00,900
Please help our

2
00:00:00,900 --> 00:00:01,300
customers.
""",
            )
            fields = CLI.write_qc_report(
                srt,
                root,
                "orphans",
                bilingual=False,
                seam_times_ms=[900],
            )
            self.assertEqual(fields["status"], "review_required")
            self.assertEqual(fields["exit_code"], 2)
            self.assertEqual(fields["qc"]["seam_times_ms"], [900])
            customers = next(
                item for item in fields["qc"]["review_items"] if item["text"] == "customers."
            )
            self.assertIn("chunk_seam_fragment", customers["reasons"])
            seams = json.loads(Path(fields["seam_times_path"]).read_text(encoding="utf-8"))
            self.assertEqual(seams["seam_times_ms"], [900])

    def test_write_qc_report_sorts_nonmonotonic_seams_for_independent_qc(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            srt = root / "input.srt"
            write_srt(
                srt,
                """
1
00:00:00,000 --> 00:00:00,200
two

2
00:00:00,200 --> 00:00:00,400
Complete sentence after the seam.
""",
            )
            fields = CLI.write_qc_report(
                srt,
                root,
                "jitter",
                bilingual=False,
                seam_times_ms=[200, 70],
            )
            artifact = Path(fields["seam_times_path"])
            loaded = CLI.load_seam_artifact(artifact)

            self.assertEqual(loaded["seam_times_ms"], [70, 200])
            self.assertEqual(
                json.loads(artifact.read_text(encoding="utf-8"))["seam_times_ms"],
                [70, 200],
            )
            self.assertEqual(fields["qc"]["seam_times_ms"], [70, 200])

    def test_write_qc_report_persists_an_empty_seam_list(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            srt = root / "short.srt"
            write_srt(
                srt,
                """
1
00:00:00,000 --> 00:00:01,000
Complete sentence.
""",
            )
            fields = CLI.write_qc_report(
                srt,
                root,
                "short",
                bilingual=False,
                seam_times_ms=[],
            )
            seams = json.loads(Path(fields["seam_times_path"]).read_text(encoding="utf-8"))
            self.assertEqual(seams["seam_times_ms"], [])

    def test_nested_qc_artifact_names_handle_long_base_name(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            srt = root / "input.srt"
            write_srt(
                srt,
                """
1
00:00:00,000 --> 00:00:01,000
Complete sentence.
""",
            )
            fields = CLI.write_qc_report(
                srt,
                root,
                "a" * 240,
                bilingual=False,
                seam_times_ms=[],
            )

            for key in ("qc_path", "seam_times_path"):
                artifact = Path(fields[key])
                self.assertTrue(artifact.is_file())
                self.assertLessEqual(len(artifact.name.encode("utf-8")), 255)
            self.assertEqual(list(root.glob(".json-*.tmp")), [])

    def test_write_qc_report_rejects_zero_duration_as_structured_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            srt = root / "zero.srt"
            write_srt(
                srt,
                """
1
00:00:01,000 --> 00:00:01,000
No duration.
""",
            )
            with self.assertRaises(CLI.SubtitleSkillError) as raised:
                CLI.write_qc_report(srt, root, "zero", bilingual=False, seam_times_ms=[])
            self.assertEqual(raised.exception.error_type, "invalid_srt")
            self.assertEqual(raised.exception.step, "parse_input")
            self.assertEqual(list(root.glob("*.semantic-orphan-qc.json")), [])
            self.assertEqual(list(root.glob("*.chunk-seams.json")), [])

    def test_failed_seam_repair_forces_nested_qc_review(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            srt = root / "long-fragment.srt"
            write_srt(
                srt,
                """
1
00:00:00,000 --> 00:00:01,000
We proudly serve

2
00:00:01,000 --> 00:00:02,000
customers around the world.
""",
            )
            fields = CLI.write_qc_report(
                srt,
                root,
                "long-fragment",
                bilingual=False,
                seam_times_ms=[1000],
                seam_repair_failures=[
                    {
                        "seam_index": 1,
                        "seam_time_ms": 1000,
                        "reason": "split_failed",
                        "message": "test failure",
                        "left_text": "We proudly serve",
                        "right_text": "customers around the world.",
                    }
                ],
            )
            self.assertEqual(fields["status"], "review_required")
            self.assertEqual(fields["exit_code"], 2)
            seam_failure = next(
                item
                for item in fields["qc"]["review_items"]
                if "seam_repair_failed" in item["reasons"]
            )
            self.assertIn(
                "seam_repair_failed",
                seam_failure["reasons"],
            )
            saved = json.loads(Path(fields["qc_path"]).read_text(encoding="utf-8"))
            self.assertEqual(saved["status"], "review_required")
            seam_artifact = json.loads(
                Path(fields["seam_times_path"]).read_text(encoding="utf-8")
            )
            self.assertEqual(
                seam_artifact["seam_repair_failures"][0]["reason"],
                "split_failed",
            )

    def test_independent_qc_inherits_seam_failure_until_explicitly_resolved(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            srt = root / "repaired.srt"
            seams = root / "seams.json"
            resolutions = root / "resolved.json"
            write_srt(
                srt,
                """
1
00:00:00,000 --> 00:00:02,000
Complete sentence after manual review.
""",
            )
            failure = {
                "seam_index": 1,
                "seam_time_ms": 1000,
                "reason": "split_failed",
                "message": "test failure",
                "left_text": "Complete sentence",
                "right_text": "after manual review.",
            }
            seams.write_text(
                json.dumps(
                    {
                        "seam_times_ms": [1000],
                        "seam_repair_failures": [failure],
                    }
                ),
                encoding="utf-8",
            )

            args = CLI.build_parser().parse_args(
                ["qc", str(srt), "--seam-times-file", str(seams)]
            )
            blocked = CLI.run_qc(args)
            self.assertEqual(blocked["status"], "review_required")
            self.assertEqual(blocked["exit_code"], 2)

            resolutions.write_text(
                json.dumps(
                    {
                        "resolved_seams": [
                            {
                                "seam_index": 1,
                                "seam_time_ms": 1000,
                                "reason": "Merged and reviewed against the source.",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            args = CLI.build_parser().parse_args(
                [
                    "qc",
                    str(srt),
                    "--seam-times-file",
                    str(seams),
                    "--resolved-seams-file",
                    str(resolutions),
                ]
            )
            cleared = CLI.run_qc(args)
            self.assertEqual(cleared["status"], "ok")
            self.assertEqual(cleared["exit_code"], 0)
            self.assertEqual(len(cleared["resolved_seam_failures"]), 1)

    def test_cli_qc_reads_seam_times_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            srt = root / "orphans.srt"
            seams = root / "seams.json"
            write_srt(
                srt,
                """
1
00:00:00,000 --> 00:00:00,400
customers.
""",
            )
            seams.write_text(json.dumps({"seam_times_ms": [0]}), encoding="utf-8")
            args = CLI.build_parser().parse_args(
                ["qc", str(srt), "--seam-times-file", str(seams)]
            )
            result = CLI.run_qc(args)
            self.assertEqual(result["status"], "review_required")
            self.assertIn("chunk_seam_fragment", result["review_items"][0]["reasons"])

    def test_qc_report_cannot_overwrite_any_input(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            srt = root / "input.srt"
            seams = root / "seams.json"
            write_srt(
                srt,
                """
1
00:00:00,000 --> 00:00:01,000
Complete sentence.
""",
            )
            seams.write_text(json.dumps({"seam_times_ms": []}), encoding="utf-8")

            for output in (srt, seams):
                with self.subTest(output=output.name):
                    srt_before = srt.read_bytes()
                    seams_before = seams.read_bytes()
                    args = CLI.build_parser().parse_args(
                        [
                            "qc",
                            str(srt),
                            "--seam-times-file",
                            str(seams),
                            "--output",
                            str(output),
                        ]
                    )
                    with self.assertRaises(CLI.SubtitleSkillError) as raised:
                        CLI.run_qc(args)
                    self.assertEqual(raised.exception.error_type, "path_collision")
                    self.assertEqual(srt.read_bytes(), srt_before)
                    self.assertEqual(seams.read_bytes(), seams_before)
                    self.assertEqual(list(root.glob(".*.tmp")), [])

    def test_malformed_srt_block_is_rejected_instead_of_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            srt = Path(temp_dir) / "broken.srt"
            write_srt(
                srt,
                """
1
00:00:00,000 --> 00:00:01,000
Complete sentence.

2
not-a-timing-line
customers.
""",
            )
            with self.assertRaises(ValueError):
                inspect_subtitle_path(srt)

            args = CLI.build_parser().parse_args(["qc", str(srt)])
            with self.assertRaises(CLI.SubtitleSkillError) as raised:
                CLI.run_qc(args)
            self.assertEqual(raised.exception.error_type, "invalid_srt")
            self.assertEqual(raised.exception.step, "parse_input")

    def test_invalid_seam_json_is_a_structured_input_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            srt = root / "input.srt"
            seams = root / "broken-seams.json"
            write_srt(
                srt,
                """
1
00:00:00,000 --> 00:00:01,000
Complete sentence.
""",
            )
            invalid_payloads = [
                b"",
                json.dumps([]).encode(),
                json.dumps({"unexpected": 123}).encode(),
                json.dumps({"seam_times_ms": ["1000"]}).encode(),
                json.dumps({"seam_times_ms": [-1]}).encode(),
                json.dumps({"seam_times_ms": [1000, 500]}).encode(),
            ]
            for payload in invalid_payloads:
                with self.subTest(payload=payload):
                    seams.write_bytes(payload)
                    args = CLI.build_parser().parse_args(
                        ["qc", str(srt), "--seam-times-file", str(seams)]
                    )
                    with self.assertRaises(CLI.SubtitleSkillError) as raised:
                        CLI.run_qc(args)
                    self.assertEqual(raised.exception.error_type, "invalid_input")
                    self.assertEqual(raised.exception.step, "validate_input")

    def test_nested_qc_console_result_is_a_small_summary(self) -> None:
        findings = [
            {
                "cue": index,
                "text": f"fragment {index}",
                "severity": "high_risk",
            }
            for index in range(1000)
        ]
        payload = {
            "ok": True,
            "action": "split",
            "status": "review_required",
            "exit_code": 2,
            "qc_path": "qc.json",
            "qc": {
                "status": "review_required",
                "exit_code": 2,
                "cue_count": 1000,
                "high_risk_count": 1000,
                "ok_short_count": 0,
                "approved_short_count": 0,
                "findings": findings,
                "review_items": findings,
            },
        }
        summary = CLI.console_result(payload)
        self.assertNotIn("qc", summary)
        self.assertEqual(summary["qc_summary"]["high_risk_count"], 1000)
        self.assertLess(len(json.dumps(summary)), 1000)

    def test_standalone_qc_console_result_is_bounded_without_qc_path(self) -> None:
        findings = [
            {"cue": index, "text": "x" * 1000, "severity": "high_risk"}
            for index in range(1000)
        ]
        payload = {
            "ok": True,
            "action": "qc",
            "status": "review_required",
            "exit_code": 2,
            "source_path": "input.srt",
            "cue_count": 1000,
            "high_risk_count": 1000,
            "ok_short_count": 0,
            "approved_short_count": 0,
            "findings": findings,
            "review_items": findings,
        }

        summary = CLI.console_result(payload)
        self.assertNotIn("findings", summary)
        self.assertNotIn("review_items", summary)
        self.assertLess(len(json.dumps(summary)), 1000)

    def test_bracketed_lowercase_continuation_is_high_risk(self) -> None:
        report = inspect_asr_data(
            ASRData(
                [
                    ASRDataSeg("This looks like a complete sentence.", 0, 1000),
                    ASRDataSeg("[because more context follows]", 1000, 2000),
                ]
            )
        )
        first = next(item for item in report["review_items"] if item["cue"] == 1)
        self.assertIn("lowercase_continuation", first["reasons"])

    def test_nonsequential_srt_cue_numbers_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            srt = Path(temp_dir) / "duplicate-cues.srt"
            write_srt(
                srt,
                """
7
00:00:00,000 --> 00:00:01,000
First sentence.

7
00:00:01,000 --> 00:00:02,000
Second sentence.
""",
            )
            args = CLI.build_parser().parse_args(["qc", str(srt)])
            with self.assertRaises(CLI.SubtitleSkillError) as raised:
                CLI.run_qc(args)
            self.assertEqual(raised.exception.error_type, "invalid_srt")

    def test_reverse_timeline_srt_is_rejected_before_sorting(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            srt = Path(temp_dir) / "reverse-timeline.srt"
            write_srt(
                srt,
                """
1
00:00:10,000 --> 00:00:11,000
Later sentence.

2
00:00:00,000 --> 00:00:01,000
Earlier sentence.
""",
            )
            args = CLI.build_parser().parse_args(["qc", str(srt)])
            with self.assertRaises(CLI.SubtitleSkillError) as raised:
                CLI.run_qc(args)
            self.assertEqual(raised.exception.error_type, "invalid_srt")

    def test_zero_duration_and_overlapping_srt_cues_are_rejected(self) -> None:
        cases = {
            "zero-duration": """
1
00:00:01,000 --> 00:00:01,000
No duration.
""",
            "overlap": """
1
00:00:00,000 --> 00:00:02,000
First cue.

2
00:00:01,500 --> 00:00:03,000
Second cue.
""",
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            for name, content in cases.items():
                with self.subTest(name=name):
                    srt = Path(temp_dir) / f"{name}.srt"
                    write_srt(srt, content)
                    args = CLI.build_parser().parse_args(["qc", str(srt)])
                    with self.assertRaises(CLI.SubtitleSkillError) as raised:
                        CLI.run_qc(args)
                    self.assertEqual(raised.exception.error_type, "invalid_srt")

    def test_argparse_failures_use_structured_json_and_exit_one(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(CLI_PATH), "qc"],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        payload = json.loads(completed.stdout)
        self.assertEqual(completed.returncode, 1)
        self.assertEqual(payload["error_type"], "invalid_arguments")
        self.assertEqual(payload["step"], "parse_arguments")
        self.assertEqual(completed.stderr, "")

    def test_broken_pipe_preserves_review_exit_after_report_write(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            srt = root / "orphans.srt"
            report = root / "report.json"
            cues = []
            for index in range(1, 301):
                start_ms = (index - 1) * 1000
                end_ms = start_ms + 500
                start_minutes, start_seconds = divmod(start_ms // 1000, 60)
                end_minutes, end_seconds = divmod(end_ms // 1000, 60)
                cues.append(
                    f"{index}\n"
                    f"00:{start_minutes:02d}:{start_seconds:02d},000 --> "
                    f"00:{end_minutes:02d}:{end_seconds:02d},500\n"
                    "fragment"
                )
            write_srt(srt, "\n\n".join(cues))
            process = subprocess.Popen(
                [
                    sys.executable,
                    str(CLI_PATH),
                    "qc",
                    str(srt),
                    "--output",
                    str(report),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            assert process.stdout is not None
            assert process.stderr is not None
            process.stdout.close()
            stderr = process.stderr.read().decode("utf-8", errors="replace")
            process.stderr.close()
            returncode = process.wait(timeout=10)

            self.assertEqual(returncode, 2, stderr)
            self.assertTrue(report.is_file())
            self.assertEqual(
                json.loads(report.read_text(encoding="utf-8"))["status"],
                "review_required",
            )
            self.assertNotIn("Exception ignored", stderr)


if __name__ == "__main__":
    unittest.main()
