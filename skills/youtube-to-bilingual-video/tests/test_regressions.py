from __future__ import annotations

import importlib.util
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
AUDIT_SCRIPT = SKILL_ROOT / "scripts" / "audit_subtitle_changes.py"
RENDER_SCRIPT = SKILL_ROOT / "scripts" / "render_bilingual_video.py"
VALIDATE_SCRIPT = SKILL_ROOT / "scripts" / "validate_bilingual_srt.py"
BIND_METADATA_SCRIPT = SKILL_ROOT / "scripts" / "bind_reviewed_source_metadata.py"
RESOLVE_JOB_DIR_SCRIPT = SKILL_ROOT / "scripts" / "resolve_job_dir.py"
ATOMIC_CLI = SKILL_ROOT.parent / "generate-and-process-subtitles" / "scripts" / "generate_and_process_subtitles.py"
CP936_ENV = {
    **os.environ,
    "PYTHONUTF8": "0",
    "PYTHONIOENCODING": "cp936",
}


def write_srt(path: Path, text: str) -> None:
    path.write_text(text.strip() + "\n", encoding="utf-8")


def write_source_metadata(
    path: Path,
    source_srt: Path,
    *,
    language: str = "en",
) -> None:
    path.write_text(
        json.dumps(
            {
                "source_language": language,
                "source_language_origin": "fixed_asr_language",
                "required_source_language": "en",
                "source_srt_hash_algorithm": "sha256",
                "source_srt_sha256": hashlib.sha256(source_srt.read_bytes()).hexdigest(),
                "source_srt_path": str(source_srt.resolve()),
            }
        ),
        encoding="utf-8",
    )


class AuditSubtitleChangesRegressionTests(unittest.TestCase):
    def test_ordinary_punctuation_and_case_remain_non_lexical(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            baseline = root / "baseline.srt"
            optimized = root / "optimized.srt"
            report_path = root / "audit.json"
            write_srt(
                baseline,
                """
1
00:00:00,000 --> 00:00:01,000
Hello, world.
""",
            )
            write_srt(
                optimized,
                """
1
00:00:00,000 --> 00:00:01,000
HELLO world!
""",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(AUDIT_SCRIPT),
                    str(baseline),
                    str(optimized),
                    "--output",
                    str(report_path),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
            )

            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "ok")
            self.assertEqual(report["lexical_change_count"], 0)

    def test_technical_symbol_removal_requires_review(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            baseline = root / "baseline.srt"
            optimized = root / "optimized.srt"
            report_path = root / "audit.json"
            write_srt(
                baseline,
                """
1
00:00:00,000 --> 00:00:01,000
We use C++ and C#.
""",
            )
            write_srt(
                optimized,
                """
1
00:00:00,000 --> 00:00:01,000
We use C and C.
""",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(AUDIT_SCRIPT),
                    str(baseline),
                    str(optimized),
                    "--output",
                    str(report_path),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
            )

            self.assertEqual(result.returncode, 2, result.stderr or result.stdout)
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "review_required")
            self.assertEqual(report["lexical_change_count"], 1)

    def test_balanced_quotes_around_a_number_remain_non_lexical(self) -> None:
        cases = [
            ('He answered "5".', "He answered 5."),
            ("He answered '5'.", "He answered 5."),
            ("He answered “5”.", "He answered 5."),
            ("He answered ‘5’.", "He answered 5."),
        ]
        for before_text, after_text in cases:
            with self.subTest(before=before_text):
                with tempfile.TemporaryDirectory() as temp_dir:
                    root = Path(temp_dir)
                    baseline = root / "baseline.srt"
                    optimized = root / "optimized.srt"
                    report_path = root / "audit.json"
                    write_srt(
                        baseline,
                        f"1\n00:00:00,000 --> 00:00:01,000\n{before_text}",
                    )
                    write_srt(
                        optimized,
                        f"1\n00:00:00,000 --> 00:00:01,000\n{after_text}",
                    )

                    result = subprocess.run(
                        [
                            sys.executable,
                            str(AUDIT_SCRIPT),
                            str(baseline),
                            str(optimized),
                            "--output",
                            str(report_path),
                        ],
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                    )

                    self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
                    report = json.loads(report_path.read_text(encoding="utf-8"))
                    self.assertEqual(report["lexical_change_count"], 0)

    def test_fluency_rewrite_requires_review(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            baseline = root / "baseline.srt"
            optimized = root / "optimized.srt"
            report_path = root / "audit.json"
            write_srt(
                baseline,
                """
1
00:00:00,000 --> 00:00:02,000
The product works good for our customers.
""",
            )
            write_srt(
                optimized,
                """
1
00:00:00,000 --> 00:00:02,000
The product works well for our customers.
""",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(AUDIT_SCRIPT),
                    str(baseline),
                    str(optimized),
                    "--output",
                    str(report_path),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
            )

            self.assertEqual(result.returncode, 2, result.stderr or result.stdout)
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "review_required")
            self.assertEqual(report["lexical_change_count"], 1)

    def test_unicode_letter_and_symbol_changes_require_review(self) -> None:
        cases = [
            ("Use α and x ≥ 4.", "Use β and x > 4."),
            ("The café is open.", "The cafè is open."),
            ("The temperature is -5 C.", "The temperature is 5 C."),
            ("Utilization is 5%.", "Utilization is 5."),
            ("Version v1.2 costs $5.", "Version v12 costs 5."),
            ("Follow #DataAI.", "Follow DataAI."),
            ("Wait .5 seconds.", "Wait 5 seconds."),
            ("The panel is 5′ wide.", "The panel is 5 wide."),
            ("The panel is 5' wide.", "The panel is 5 wide."),
            ('The panel is 5" wide.', "The panel is 5 wide."),
            ("The panel is 5’ wide.", "The panel is 5 wide."),
            ("The panel is 5” wide.", "The panel is 5 wide."),
            ("Widths are 5' 6'.", "Widths are 5 6."),
            ("Growth in '25 '26.", "Growth in 25 26."),
        ]
        for before_text, after_text in cases:
            with self.subTest(before=before_text, after=after_text):
                with tempfile.TemporaryDirectory() as temp_dir:
                    root = Path(temp_dir)
                    baseline = root / "baseline.srt"
                    optimized = root / "optimized.srt"
                    report_path = root / "audit.json"
                    write_srt(
                        baseline,
                        f"""
1
00:00:00,000 --> 00:00:01,000
{before_text}
""",
                    )
                    write_srt(
                        optimized,
                        f"""
1
00:00:00,000 --> 00:00:01,000
{after_text}
""",
                    )

                    result = subprocess.run(
                        [
                            sys.executable,
                            str(AUDIT_SCRIPT),
                            str(baseline),
                            str(optimized),
                            "--output",
                            str(report_path),
                        ],
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                    )

                    self.assertEqual(result.returncode, 2, result.stderr or result.stdout)
                    report = json.loads(report_path.read_text(encoding="utf-8"))
                    self.assertEqual(report["status"], "review_required")
                    self.assertEqual(report["lexical_change_count"], 1)

    def test_report_cannot_alias_either_srt_input(self) -> None:
        for output_target in ("baseline", "optimized"):
            with self.subTest(output_target=output_target):
                with tempfile.TemporaryDirectory() as temp_dir:
                    root = Path(temp_dir)
                    baseline = root / "baseline.srt"
                    optimized = root / "optimized.srt"
                    write_srt(
                        baseline,
                        """
1
00:00:00,000 --> 00:00:01,000
Hello
""",
                    )
                    write_srt(
                        optimized,
                        """
1
00:00:00,000 --> 00:00:01,000
Hello!
""",
                    )
                    output = baseline if output_target == "baseline" else optimized
                    original = output.read_bytes()
                    result = subprocess.run(
                        [
                            sys.executable,
                            str(AUDIT_SCRIPT),
                            str(baseline),
                            str(optimized),
                            "--output",
                            str(output),
                        ],
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                    )
                    self.assertEqual(result.returncode, 1)
                    self.assertEqual(output.read_bytes(), original)
                    self.assertEqual(json.loads(result.stdout)["reason"], "path_collision")

    def test_legacy_code_page_stdout_is_safe(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "emoji-😀"
            root.mkdir()
            baseline = root / "baseline.srt"
            optimized = root / "optimized.srt"
            report_path = root / "audit.json"
            write_srt(
                baseline,
                """
1
00:00:00,000 --> 00:00:01,000
Keep 😀
""",
            )
            write_srt(
                optimized,
                """
1
00:00:00,000 --> 00:00:01,000
Keep 🚀
""",
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(AUDIT_SCRIPT),
                    str(baseline),
                    str(optimized),
                    "--output",
                    str(report_path),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                env=CP936_ENV,
            )
            self.assertEqual(result.returncode, 2, result.stderr or result.stdout)
            self.assertEqual(json.loads(result.stdout)["status"], "review_required")


class BilingualValidationRegressionTests(unittest.TestCase):
    def run_validator(
        self,
        srt_text: str,
        source_text: str | None = None,
        *extra_args: str,
        env: dict[str, str] | None = None,
    ) -> tuple[subprocess.CompletedProcess[str], dict]:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        root = Path(temp_dir.name)
        srt = root / "bilingual.srt"
        source = root / "source.srt"
        source_metadata = root / "source.metadata.json"
        report_path = root / "validation.json"
        write_srt(srt, srt_text)
        write_srt(
            source,
            source_text
            or """
1
00:00:00,000 --> 00:00:01,000
Welcome to Databricks Lakehouse.
""",
        )
        write_source_metadata(source_metadata, source)
        result = subprocess.run(
            [
                sys.executable,
                str(VALIDATE_SCRIPT),
                str(srt),
                "--source-srt",
                str(source),
                "--source-metadata",
                str(source_metadata),
                "--output",
                str(report_path),
                *extra_args,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
        )
        return result, json.loads(report_path.read_text(encoding="utf-8"))

    def test_chinese_first_mixed_product_name_passes(self) -> None:
        result, report = self.run_validator(
            """
1
00:00:00,000 --> 00:00:01,000
欢迎使用 Databricks 数据平台。
Welcome to Databricks Lakehouse.
"""
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        self.assertEqual(report["status"], "ok")
        self.assertFalse(report["coverage_checked"])
        self.assertTrue(report["warnings"])

    def test_non_english_source_metadata_fails_even_with_latin_source_text(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bilingual = root / "bilingual.srt"
            source = root / "source.srt"
            metadata = root / "source.metadata.json"
            report_path = root / "validation.json"
            write_srt(bilingual, "1\n00:00:00,000 --> 00:00:01,000\n你好\nHola")
            write_srt(source, "1\n00:00:00,000 --> 00:00:01,000\nHola")
            metadata.write_text(json.dumps({"source_language": "es"}), encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(VALIDATE_SCRIPT),
                    str(bilingual),
                    "--source-srt",
                    str(source),
                    "--source-metadata",
                    str(metadata),
                    "--output",
                    str(report_path),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self.assertEqual(result.returncode, 1)
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(report["reason"], "source_language_mismatch")
            self.assertIn("does not match required", report["message"])

    def test_stale_english_metadata_cannot_validate_unrelated_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bilingual = root / "bilingual.srt"
            source = root / "source.srt"
            unrelated = root / "unrelated.srt"
            metadata = root / "source.metadata.json"
            report_path = root / "validation.json"
            write_srt(bilingual, "1\n00:00:00,000 --> 00:00:01,000\n你好。\nHola.")
            write_srt(source, "1\n00:00:00,000 --> 00:00:01,000\nHola.")
            write_srt(unrelated, "1\n00:00:00,000 --> 00:00:01,000\nHello.")
            write_source_metadata(metadata, unrelated)
            result = subprocess.run(
                [
                    sys.executable,
                    str(VALIDATE_SCRIPT),
                    str(bilingual),
                    "--source-srt",
                    str(source),
                    "--source-metadata",
                    str(metadata),
                    "--output",
                    str(report_path),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self.assertEqual(result.returncode, 1)
            self.assertEqual(
                json.loads(report_path.read_text(encoding="utf-8"))["reason"],
                "source_metadata_mismatch",
            )

    def test_reviewed_source_binding_requires_explicit_review_and_exact_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "reviewed.srt"
            upstream_source = root / "baseline.srt"
            upstream_metadata = root / "upstream.metadata.json"
            audit = root / "audit.json"
            output = root / "reviewed.metadata.json"
            write_srt(source, "1\n00:00:00,000 --> 00:00:01,000\nHello, world.")
            write_srt(upstream_source, "1\n00:00:00,000 --> 00:00:01,000\nHello world.")
            write_source_metadata(upstream_metadata, upstream_source)
            audit.write_text(
                json.dumps(
                    {
                        "status": "review_required",
                        "before_path": str(upstream_source.resolve()),
                        "before_sha256": hashlib.sha256(upstream_source.read_bytes()).hexdigest(),
                        "after_path": str(source.resolve()),
                        "after_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                    }
                ),
                encoding="utf-8",
            )
            command = [
                sys.executable,
                str(BIND_METADATA_SCRIPT),
                "--source-srt",
                str(source),
                "--upstream-metadata",
                str(upstream_metadata),
                "--audit-report",
                str(audit),
                "--reviewed-by",
                "human-reviewer",
                "--review-note",
                "Audio and frame evidence checked.",
                "--output",
                str(output),
            ]
            blocked = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(blocked.returncode, 1)
            accepted = subprocess.run(
                [*command, "--accept-reviewed-changes"],
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self.assertEqual(accepted.returncode, 0, accepted.stderr or accepted.stdout)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload["source_language_origin"], "reviewed_source_handoff")
            self.assertEqual(payload["source_srt_sha256"], hashlib.sha256(source.read_bytes()).hexdigest())

    def test_reviewed_binding_rejects_unbound_or_unrelated_upstream_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "hola.srt"
            unrelated = root / "english.srt"
            audit = root / "audit.json"
            write_srt(source, "1\n00:00:00,000 --> 00:00:01,000\nHola.")
            write_srt(unrelated, "1\n00:00:00,000 --> 00:00:01,000\nHello.")
            source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
            audit.write_text(
                json.dumps(
                    {
                        "status": "ok",
                        "before_path": str(source.resolve()),
                        "before_sha256": source_hash,
                        "after_path": str(source.resolve()),
                        "after_sha256": source_hash,
                    }
                ),
                encoding="utf-8",
            )
            metadata_paths = []
            unbound = root / "unbound.json"
            unbound.write_text(
                json.dumps(
                    {
                        "source_language": "en",
                        "required_source_language": "en",
                        "source_language_origin": "asr_detection",
                        "source_language_probability": 1.0,
                    }
                ),
                encoding="utf-8",
            )
            metadata_paths.append(unbound)
            unrelated_metadata = root / "unrelated.json"
            write_source_metadata(unrelated_metadata, unrelated)
            metadata_paths.append(unrelated_metadata)
            for metadata in metadata_paths:
                with self.subTest(metadata=metadata.name):
                    result = subprocess.run(
                        [
                            sys.executable,
                            str(BIND_METADATA_SCRIPT),
                            "--source-srt",
                            str(source),
                            "--upstream-metadata",
                            str(metadata),
                            "--audit-report",
                            str(audit),
                            "--reviewed-by",
                            "reviewer",
                            "--review-note",
                            "checked",
                            "--output",
                            str(root / f"{metadata.stem}.handoff.json"),
                        ],
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                    )
                    self.assertEqual(result.returncode, 1, result.stdout)
                    self.assertEqual(
                        json.loads(result.stdout)["reason"],
                        "source_metadata_binding_failure",
                    )

    def test_reversed_mixed_language_lines_fail(self) -> None:
        result, report = self.run_validator(
            """
1
00:00:00,000 --> 00:00:01,000
Welcome to 数据湖 House.
欢迎使用 Lakehouse。
"""
        )
        self.assertEqual(result.returncode, 1, result.stderr or result.stdout)
        self.assertEqual(report["status"], "error")
        self.assertIn(
            "ambiguous_or_reversed_language_order",
            {issue["type"] for issue in report["issues"]},
        )

    def test_source_cue_loss_fails(self) -> None:
        result, report = self.run_validator(
            """
1
00:00:00,000 --> 00:00:01,000
你好
Hello
""",
            """
1
00:00:00,000 --> 00:00:01,000
Hello

2
00:00:01,500 --> 00:00:02,500
World
""",
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn(
            "source_cue_count_mismatch",
            {issue["type"] for issue in report["issues"]},
        )

    def test_source_timing_change_fails(self) -> None:
        result, report = self.run_validator(
            """
1
00:00:00,100 --> 00:00:01,100
你好
Hello
""",
            """
1
00:00:00,000 --> 00:00:01,000
Hello
""",
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn(
            "source_timing_mismatch",
            {issue["type"] for issue in report["issues"]},
        )

    def test_source_english_text_change_fails(self) -> None:
        result, report = self.run_validator(
            """
1
00:00:00,000 --> 00:00:01,000
欢迎使用 Databricks 数据平台。
Welcome to Snowflake Warehouse.
"""
        )
        self.assertEqual(result.returncode, 1, result.stderr or result.stdout)
        self.assertIn(
            "source_text_mismatch",
            {issue["type"] for issue in report["issues"]},
        )

    def test_extra_english_line_before_source_fails(self) -> None:
        result, report = self.run_validator(
            """
1
00:00:00,000 --> 00:00:01,000
欢迎使用 Databricks 数据平台。
This extra English line must not be hidden.
Welcome to Databricks Lakehouse.
"""
        )
        self.assertEqual(result.returncode, 1, result.stderr or result.stdout)
        self.assertIn(
            "unexpected_english_line_before_source",
            {issue["type"] for issue in report["issues"]},
        )

    def test_multiline_source_text_must_match_as_a_suffix(self) -> None:
        result, report = self.run_validator(
            """
1
00:00:00,000 --> 00:00:01,000
欢迎使用 Databricks 数据平台。
Welcome to Databricks
Lakehouse.
""",
            """
1
00:00:00,000 --> 00:00:01,000
Welcome to Databricks
Lakehouse.
""",
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        self.assertEqual(report["status"], "ok")

    def test_material_video_tail_gap_fails(self) -> None:
        result, report = self.run_validator(
            """
1
00:00:00,000 --> 00:00:01,000
你好
Hello
""",
            """
1
00:00:00,000 --> 00:00:01,000
Hello
""",
            "--duration",
            "3600",
        )
        self.assertEqual(result.returncode, 1)
        self.assertTrue(report["coverage_checked"])
        self.assertIn(
            "video_tail_coverage_gap",
            {issue["type"] for issue in report["issues"]},
        )
        self.assertIn(
            "targeted interval re-transcription",
            report["issues"][0]["suggested_fix"],
        )
        self.assertIn("Do not invent bilingual cues", report["issues"][0]["suggested_fix"])

    def test_non_finite_numeric_controls_fail_with_strict_json(self) -> None:
        cases = [
            ("--duration", "nan"),
            ("--duration", "inf"),
            ("--duration", "-1"),
            ("--duration-tolerance", "nan"),
            ("--duration-tolerance", "-1"),
            ("--timing-tolerance", "inf"),
            ("--timing-tolerance", "-1"),
            ("--max-head-gap-seconds", "nan"),
            ("--max-head-gap-seconds", "-1"),
            ("--max-tail-gap-seconds", "inf"),
            ("--max-tail-gap-seconds", "-1"),
        ]
        for flag, value in cases:
            with self.subTest(flag=flag, value=value):
                result, report = self.run_validator(
                    """
1
00:00:00,000 --> 00:00:01,000
欢迎使用 Databricks 数据平台。
Welcome to Databricks Lakehouse.
""",
                    None,
                    flag,
                    value,
                )
                self.assertEqual(result.returncode, 1)
                self.assertEqual(report["status"], "error")
                self.assertNotIn("NaN", result.stdout)
                self.assertNotIn("Infinity", result.stdout)

    def test_report_cannot_alias_any_input(self) -> None:
        for target in ("srt", "source", "metadata", "video"):
            with self.subTest(target=target):
                with tempfile.TemporaryDirectory() as temp_dir:
                    root = Path(temp_dir)
                    srt = root / "bilingual.srt"
                    source = root / "source.srt"
                    metadata = root / "source.metadata.json"
                    video = root / "video.mp4"
                    write_srt(srt, "1\n00:00:00,000 --> 00:00:01,000\n你好\nHello")
                    write_srt(source, "1\n00:00:00,000 --> 00:00:01,000\nHello")
                    write_source_metadata(metadata, source)
                    video.write_bytes(b"video")
                    output = {"srt": srt, "source": source, "metadata": metadata, "video": video}[target]
                    original = output.read_bytes()
                    result = subprocess.run(
                        [
                            sys.executable,
                            str(VALIDATE_SCRIPT),
                            str(srt),
                            "--source-srt",
                            str(source),
                            "--source-metadata",
                            str(metadata),
                            "--video",
                            str(video),
                            "--output",
                            str(output),
                        ],
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                    )
                    self.assertEqual(result.returncode, 1)
                    self.assertEqual(output.read_bytes(), original)
                    self.assertEqual(json.loads(result.stdout)["reason"], "path_collision")

    def test_source_srt_cannot_alias_bilingual_srt(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            srt = root / "same.srt"
            metadata = root / "source.metadata.json"
            write_srt(srt, "1\n00:00:00,000 --> 00:00:01,000\n你好\nHello")
            write_source_metadata(metadata, srt)
            original = srt.read_bytes()
            result = subprocess.run(
                [
                    sys.executable,
                    str(VALIDATE_SCRIPT),
                    str(srt),
                    "--source-srt",
                    str(srt),
                    "--source-metadata",
                    str(metadata),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self.assertEqual(result.returncode, 1)
            self.assertEqual(srt.read_bytes(), original)
            self.assertEqual(json.loads(result.stdout)["reason"], "path_collision")

    def test_legacy_code_page_stdout_is_safe(self) -> None:
        result, report = self.run_validator(
            """
1
00:00:00,000 --> 00:00:01,000
你好 😀
Hello 😀
""",
            """
1
00:00:00,000 --> 00:00:01,000
Hello 😀
""",
            env=CP936_ENV,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        self.assertEqual(report["status"], "ok")
        self.assertFalse(report["coverage_checked"])


class ReportChannelRegressionTests(unittest.TestCase):
    def test_output_reports_print_bounded_summaries(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            before = root / "before.srt"
            after = root / "after.srt"
            report = root / "audit.json"
            write_srt(before, "1\n00:00:00,000 --> 00:00:01,000\nAlpha")
            write_srt(after, "1\n00:00:00,000 --> 00:00:01,000\nBeta")
            result = subprocess.run(
                [sys.executable, str(AUDIT_SCRIPT), str(before), str(after), "--output", str(report)],
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self.assertEqual(result.returncode, 2)
            summary = json.loads(result.stdout)
            full = json.loads(report.read_text(encoding="utf-8"))
            self.assertNotIn("review_items", summary)
            self.assertIn("review_items", full)
            self.assertEqual(summary["report_path"], str(report.resolve()))

    def test_report_parent_file_returns_structured_failure_for_all_composite_scripts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            blocked_parent = root / "not-a-directory"
            blocked_parent.write_text("block", encoding="utf-8")
            report = blocked_parent / "report.json"
            source = root / "source.srt"
            bilingual = root / "bilingual.srt"
            after = root / "after.srt"
            metadata = root / "source.metadata.json"
            write_srt(source, "1\n00:00:00,000 --> 00:00:01,000\nHello")
            write_srt(bilingual, "1\n00:00:00,000 --> 00:00:01,000\n你好\nHello")
            write_srt(after, "1\n00:00:00,000 --> 00:00:01,000\nHello!")
            write_source_metadata(metadata, source)
            commands = (
                [sys.executable, str(AUDIT_SCRIPT), str(source), str(after), "--output", str(report)],
                [
                    sys.executable,
                    str(VALIDATE_SCRIPT),
                    str(bilingual),
                    "--source-srt",
                    str(source),
                    "--source-metadata",
                    str(metadata),
                    "--output",
                    str(report),
                ],
                [
                    sys.executable,
                    str(RENDER_SCRIPT),
                    "--input-video",
                    str(root / "missing.mp4"),
                    "--subtitle",
                    str(bilingual),
                    "--output",
                    str(root / "final.mp4"),
                    "--work-dir",
                    str(root / "render"),
                    "--report",
                    str(report),
                ],
            )
            for command in commands:
                with self.subTest(script=command[1]):
                    result = subprocess.run(
                        command,
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                    )
                    self.assertEqual(result.returncode, 1)
                    self.assertEqual(result.stderr, "")
                    self.assertEqual(json.loads(result.stdout)["reason"], "report_write_failure")

    def test_long_legal_report_component_uses_short_temporary_name(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            before = root / "before.srt"
            after = root / "after.srt"
            source = root / "source.srt"
            bilingual = root / "bilingual.srt"
            metadata = root / "source.metadata.json"
            write_srt(before, "1\n00:00:00,000 --> 00:00:01,000\nAlpha")
            write_srt(after, "1\n00:00:00,000 --> 00:00:01,000\nAlpha!")
            write_srt(source, "1\n00:00:00,000 --> 00:00:01,000\nHello")
            write_srt(bilingual, "1\n00:00:00,000 --> 00:00:01,000\n你好\nHello")
            write_source_metadata(metadata, source)
            commands = (
                [sys.executable, str(AUDIT_SCRIPT), str(before), str(after)],
                [
                    sys.executable,
                    str(VALIDATE_SCRIPT),
                    str(bilingual),
                    "--source-srt",
                    str(source),
                    "--source-metadata",
                    str(metadata),
                ],
                [
                    sys.executable,
                    str(RENDER_SCRIPT),
                    "--input-video",
                    str(root / "missing.mp4"),
                    "--subtitle",
                    str(bilingual),
                    "--output",
                    str(root / "final.mp4"),
                    "--work-dir",
                    str(root / "render"),
                ],
            )
            for index, command in enumerate(commands):
                with self.subTest(script=command[1]):
                    report = root / ((chr(ord("a") + index) * 225) + ".json")
                    flag = "--report" if command[1] == str(RENDER_SCRIPT) else "--output"
                    result = subprocess.run(
                        [*command, flag, str(report)],
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                    )
                    self.assertIn(result.returncode, {0, 1}, result.stderr or result.stdout)
                    self.assertTrue(report.is_file())
                    self.assertNotEqual(
                        json.loads(report.read_text(encoding="utf-8")).get("reason"),
                        "report_write_failure",
                    )

    def test_audit_and_validator_broken_pipe_preserve_business_exit_codes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            before = root / "before.srt"
            after = root / "after.srt"
            audit_report = root / "audit.json"
            source = root / "source.srt"
            bilingual = root / "bilingual.srt"
            metadata = root / "source.metadata.json"
            validation_report = root / "validation.json"
            write_srt(before, "1\n00:00:00,000 --> 00:00:01,000\nAlpha")
            write_srt(after, "1\n00:00:00,000 --> 00:00:01,000\nBeta")
            write_srt(source, "1\n00:00:00,000 --> 00:00:01,000\nHello")
            write_srt(bilingual, "1\n00:00:00,000 --> 00:00:01,000\n你好\nHello")
            write_source_metadata(metadata, source)
            commands = (
                (
                    [sys.executable, str(AUDIT_SCRIPT), str(before), str(after), "--output", str(audit_report)],
                    2,
                    audit_report,
                ),
                (
                    [
                        sys.executable,
                        str(VALIDATE_SCRIPT),
                        str(bilingual),
                        "--source-srt",
                        str(source),
                        "--source-metadata",
                        str(metadata),
                        "--output",
                        str(validation_report),
                    ],
                    0,
                    validation_report,
                ),
            )
            for command, expected_exit, report in commands:
                with self.subTest(script=command[1]):
                    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    assert process.stdout is not None
                    assert process.stderr is not None
                    process.stdout.close()
                    stderr = process.stderr.read().decode("utf-8", errors="replace")
                    process.stderr.close()
                    self.assertEqual(process.wait(timeout=10), expected_exit, stderr)
                    self.assertTrue(report.is_file())
                    self.assertNotIn("Exception ignored", stderr)


@unittest.skipUnless(os.name == "nt", "Windows device-prefix alias regression")
class WindowsDeviceAliasRegressionTests(unittest.TestCase):
    def test_device_prefix_report_aliases_cannot_overwrite_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source.srt"
            bilingual = root / "bilingual.srt"
            optimized = root / "optimized.srt"
            metadata = root / "source.metadata.json"
            write_srt(source, "1\n00:00:00,000 --> 00:00:01,000\nHello")
            write_srt(bilingual, "1\n00:00:00,000 --> 00:00:01,000\n你好\nHello")
            write_srt(optimized, "1\n00:00:00,000 --> 00:00:01,000\nHello!")
            write_source_metadata(metadata, source)

            cases = (
                (
                    [sys.executable, str(ATOMIC_CLI), "qc", str(source), "--output", "\\\\?\\" + str(source)],
                    source,
                ),
                (
                    [sys.executable, str(AUDIT_SCRIPT), str(source), str(optimized), "--output", "\\\\?\\" + str(source)],
                    source,
                ),
                (
                    [
                        sys.executable,
                        str(VALIDATE_SCRIPT),
                        str(bilingual),
                        "--source-srt",
                        str(source),
                        "--source-metadata",
                        str(metadata),
                        "--output",
                        "\\\\?\\" + str(bilingual),
                    ],
                    bilingual,
                ),
            )
            for command, protected in cases:
                with self.subTest(command=command[1]):
                    original = protected.read_bytes()
                    result = subprocess.run(
                        command,
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                    )
                    self.assertEqual(result.returncode, 1, result.stderr or result.stdout)
                    self.assertEqual(protected.read_bytes(), original)
                    self.assertEqual(json.loads(result.stdout)["reason" if command[1] != str(ATOMIC_CLI) else "error_type"], "path_collision")


class RenderPathRegressionTests(unittest.TestCase):
    def test_report_path_cannot_overwrite_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output = root / "final-😀.mp4"
            original = b"existing-video"
            output.write_bytes(original)

            result = subprocess.run(
                [
                    sys.executable,
                    str(RENDER_SCRIPT),
                    "--input-video",
                    str(root / "source.mp4"),
                    "--subtitle",
                    str(root / "subtitles.srt"),
                    "--output",
                    str(output),
                    "--work-dir",
                    str(root / "render"),
                    "--report",
                    str(output),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                env=CP936_ENV,
            )

            self.assertEqual(result.returncode, 1, result.stderr or result.stdout)
            self.assertEqual(output.read_bytes(), original)
            report = json.loads(result.stdout)
            self.assertEqual(report["status"], "error")
            self.assertIn("must all differ", report["message"])

    def test_all_render_input_and_output_paths_must_differ(self) -> None:
        cases = ("report_source", "report_subtitle", "output_source", "output_subtitle")
        for case in cases:
            with self.subTest(case=case):
                with tempfile.TemporaryDirectory() as temp_dir:
                    root = Path(temp_dir)
                    source = root / "source.mp4"
                    subtitle = root / "subtitle.srt"
                    output = root / "final.mp4"
                    report = root / "report.json"
                    source.write_bytes(b"source")
                    subtitle.write_bytes(b"subtitle")
                    if case == "report_source":
                        report = source
                    elif case == "report_subtitle":
                        report = subtitle
                    elif case == "output_source":
                        output = source
                    else:
                        output = subtitle
                    source_before = source.read_bytes()
                    subtitle_before = subtitle.read_bytes()
                    result = subprocess.run(
                        [
                            sys.executable,
                            str(RENDER_SCRIPT),
                            "--input-video",
                            str(source),
                            "--subtitle",
                            str(subtitle),
                            "--output",
                            str(output),
                            "--work-dir",
                            str(root / "work"),
                            "--report",
                            str(report),
                        ],
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                    )
                    self.assertEqual(result.returncode, 1)
                    self.assertEqual(source.read_bytes(), source_before)
                    self.assertEqual(subtitle.read_bytes(), subtitle_before)
                    payload = json.loads(result.stdout)
                    self.assertIn("must all differ", payload["message"])
                    self.assertEqual(payload["reason"], "path_collision")
                    if case in {"report_source", "report_subtitle"}:
                        continue
                    written = json.loads(Path(report).read_text(encoding="utf-8"))
                    self.assertEqual(written["status"], "error")
                    self.assertEqual(written["reason"], "path_collision")

    def test_output_source_collision_writes_default_report(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source.mp4"
            subtitle = root / "subtitle.srt"
            work_dir = root / "render"
            source.write_bytes(b"source")
            subtitle.write_bytes(b"subtitle")
            result = subprocess.run(
                [
                    sys.executable,
                    str(RENDER_SCRIPT),
                    "--input-video",
                    str(source),
                    "--subtitle",
                    str(subtitle),
                    "--output",
                    str(source),
                    "--work-dir",
                    str(work_dir),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self.assertEqual(result.returncode, 1)
            self.assertEqual(source.read_bytes(), b"source")
            report_path = work_dir / "render-report.json"
            written = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(written["status"], "error")
            self.assertEqual(written["reason"], "path_collision")

    @unittest.skipUnless(
        shutil.which("ffmpeg") and shutil.which("ffprobe"),
        "ffmpeg and ffprobe are required",
    )
    def test_apostrophe_in_subtitle_and_work_paths(self) -> None:
        encoders = subprocess.run(
            ["ffmpeg", "-hide_banner", "-encoders"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if "libx264" not in encoders.stdout:
            self.skipTest("libx264 is required")

        with tempfile.TemporaryDirectory() as temp_dir:
            job_dir = Path(temp_dir) / "author's [job], v1 😀"
            work_dir = job_dir / "render"
            job_dir.mkdir()
            source = job_dir / "source.mp4"
            subtitle = job_dir / "author's bilingual.srt"
            output = job_dir / "final.mp4"
            report_path = work_dir / "render-report.json"
            write_srt(
                subtitle,
                """
1
00:00:00,000 --> 00:00:00,800
你好
Hello
""",
            )
            source_result = subprocess.run(
                [
                    "ffmpeg",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-f",
                    "lavfi",
                    "-i",
                    "color=c=blue:s=320x180:r=10:d=1",
                    "-f",
                    "lavfi",
                    "-i",
                    "sine=frequency=1000:duration=1",
                    "-shortest",
                    "-c:v",
                    "mpeg4",
                    "-c:a",
                    "aac",
                    "-y",
                    str(source),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=CP936_ENV,
            )
            self.assertEqual(
                source_result.returncode,
                0,
                source_result.stderr or source_result.stdout,
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(RENDER_SCRIPT),
                    "--input-video",
                    str(source),
                    "--subtitle",
                    str(subtitle),
                    "--output",
                    str(output),
                    "--work-dir",
                    str(work_dir),
                    "--encoder",
                    "libx264",
                    "--report",
                    str(report_path),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=CP936_ENV,
            )

            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "ok")
            self.assertEqual(report["font_size"], 16.0)
            self.assertIn("audio", report["source_stream_types"])
            self.assertIn("audio", report["output_stream_types"])
            self.assertTrue(output.is_file())
            self.assertEqual(list(work_dir.glob(".render-subtitle-*.srt")), [])

    @unittest.skipUnless(
        shutil.which("ffmpeg") and shutil.which("ffprobe"),
        "ffmpeg and ffprobe are required",
    )
    def test_silent_source_is_rejected_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "silent.mp4"
            subtitle = root / "bilingual.srt"
            output = root / "final.mp4"
            work_dir = root / "render"
            write_srt(subtitle, "1\n00:00:00,000 --> 00:00:00,800\n你好\nHello")
            source_result = subprocess.run(
                [
                    "ffmpeg",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-f",
                    "lavfi",
                    "-i",
                    "color=c=blue:s=320x180:r=10:d=1",
                    "-c:v",
                    "mpeg4",
                    "-y",
                    str(source),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            self.assertEqual(source_result.returncode, 0, source_result.stderr)
            result = subprocess.run(
                [
                    sys.executable,
                    str(RENDER_SCRIPT),
                    "--input-video",
                    str(source),
                    "--subtitle",
                    str(subtitle),
                    "--output",
                    str(output),
                    "--work-dir",
                    str(work_dir),
                    "--encoder",
                    "libx264",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self.assertEqual(result.returncode, 1)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["reason"], "missing_audio_stream")
            self.assertIn("no audio stream", payload["message"])
            self.assertNotIn("pass --allow-silent", payload["message"].lower())
            self.assertIn("Ask the user", payload["suggested_fix"])
            self.assertFalse(output.exists())
            written = json.loads((work_dir / "render-report.json").read_text(encoding="utf-8"))
            self.assertEqual(written["reason"], "missing_audio_stream")

            allowed = subprocess.run(
                [
                    sys.executable,
                    str(RENDER_SCRIPT),
                    "--input-video",
                    str(source),
                    "--subtitle",
                    str(subtitle),
                    "--output",
                    str(output),
                    "--work-dir",
                    str(work_dir),
                    "--encoder",
                    "libx264",
                    "--allow-silent",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self.assertEqual(allowed.returncode, 0, allowed.stderr or allowed.stdout)
            allowed_report = json.loads(allowed.stdout)
            self.assertTrue(output.is_file())
            self.assertIn("intentionally silent", allowed_report["warnings"][0])


class WorkflowContractRegressionTests(unittest.TestCase):
    def test_final_english_qc_is_required_after_audit_and_before_translation(self) -> None:
        skill_text = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        workflow_text = (SKILL_ROOT / "references" / "workflow.md").read_text(
            encoding="utf-8"
        )

        audit_position = skill_text.index("**Audit optimization changes.**")
        final_qc_position = skill_text.index("**Re-run final English QC.**")
        translate_position = skill_text.index("**Translate.**")
        self.assertLess(audit_position, final_qc_position)
        self.assertLess(final_qc_position, translate_position)
        self.assertIn("exact downstream English SRT returns QC exit code `0`", workflow_text)
        self.assertIn("punctuation or case changes can create a new orphan", workflow_text)

    def test_default_job_root_and_english_language_handoff_are_explicit(self) -> None:
        skill_text = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        workflow_text = (SKILL_ROOT / "references" / "workflow.md").read_text(
            encoding="utf-8"
        )
        contracts = (SKILL_ROOT / "references" / "atomic-skill-contracts.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("<cwd>/<safe-title>-<video-id>-<id-digest>/", skill_text)
        self.assertIn("<cwd>/<safe-title>-<video-id>-<id-digest>/", workflow_text)
        self.assertIn("--require-language en", contracts)
        self.assertIn("--source-metadata", workflow_text)

    def test_job_dir_resolver_is_windows_safe_and_reuses_video_id_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = subprocess.run(
                [
                    sys.executable,
                    str(RESOLVE_JOB_DIR_SCRIPT),
                    "--root",
                    str(root),
                    "--title",
                    ("CON:" + "超长标题" * 80 + ". "),
                    "--video-id",
                    "aYfZN8t6AQs",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self.assertEqual(first.returncode, 0, first.stderr or first.stdout)
            first_payload = json.loads(first.stdout)
            job_dir = Path(first_payload["job_dir"])
            self.assertTrue(job_dir.is_dir())
            self.assertLessEqual(len(job_dir.name.encode("utf-8")), 255)
            second = subprocess.run(
                [
                    sys.executable,
                    str(RESOLVE_JOB_DIR_SCRIPT),
                    "--root",
                    str(root),
                    "--title",
                    "A renamed title",
                    "--video-id",
                    "aYfZN8t6AQs",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self.assertEqual(second.returncode, 0, second.stderr or second.stdout)
            second_payload = json.loads(second.stdout)
            self.assertEqual(second_payload["job_dir"], first_payload["job_dir"])
            self.assertTrue(second_payload["reused"])

    def test_job_dir_resolver_recovers_empty_candidate(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "resolve_job_dir_for_tests", RESOLVE_JOB_DIR_SCRIPT
        )
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            video_id = "aYfZN8t6AQs"
            title = "Recover me"
            candidate = root / module.deterministic_directory_name(
                module.safe_title(title), video_id
            )
            candidate.mkdir()
            recovered, reused = module.resolve_job_dir(root, title, video_id)
            self.assertEqual(recovered, candidate.resolve())
            self.assertFalse(reused)
            self.assertTrue((candidate / module.MANIFEST_NAME).is_file())

    def test_job_dir_resolver_rejects_partial_and_duplicate_manifests(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "resolve_job_dir_manifest_tests", RESOLVE_JOB_DIR_SCRIPT
        )
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            partial = root / "partial"
            partial.mkdir()
            (partial / module.MANIFEST_NAME).write_text(
                json.dumps({"video_id": "partial123"}), encoding="utf-8"
            )
            resolved, reused = module.resolve_job_dir(root, "Complete", "partial123")
            self.assertFalse(reused)
            self.assertNotEqual(resolved, partial.resolve())

            video_id = "duplicate123"
            for title in ("First", "Second"):
                safe_name = module.safe_title(title)
                directory_name = module.deterministic_directory_name(
                    safe_name, video_id
                )
                candidate = root / directory_name
                candidate.mkdir()
                (candidate / module.MANIFEST_NAME).write_text(
                    json.dumps(
                        {
                            "schema_version": module.MANIFEST_VERSION,
                            "video_id": video_id,
                            "original_title": title,
                            "safe_title": safe_name,
                            "directory_name": directory_name,
                        }
                    ),
                    encoding="utf-8",
                )
            with self.assertRaises(module.JobResolverError) as raised:
                module.resolve_job_dir(root, "Duplicate", video_id)
            self.assertEqual(raised.exception.reason, "duplicate_video_job")

    def test_job_dir_resolver_ignores_complete_manifest_in_wrong_directory(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "resolve_job_dir_wrong_directory_tests", RESOLVE_JOB_DIR_SCRIPT
        )
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            video_id = "unrelated123"
            title = "Unrelated"
            candidate = root / "arbitrary-unrelated-dir"
            candidate.mkdir()
            (candidate / module.MANIFEST_NAME).write_text(
                json.dumps(
                    {
                        "schema_version": module.MANIFEST_VERSION,
                        "video_id": video_id,
                        "original_title": title,
                        "safe_title": module.safe_title(title),
                        "directory_name": candidate.name,
                    }
                ),
                encoding="utf-8",
            )
            resolved, reused = module.resolve_job_dir(root, title, video_id)
            self.assertFalse(reused)
            self.assertNotEqual(resolved, candidate.resolve())

    def test_job_dir_resolver_recovers_empty_crash_lock(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "resolve_job_dir_empty_lock_tests", RESOLVE_JOB_DIR_SCRIPT
        )
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            video_id = "emptylock123"
            digest = hashlib.sha256(video_id.encode("ascii")).hexdigest()[:16]
            lock_path = root / f".bilingual-job-{digest}.lock"
            lock_path.touch()
            resolved, reused = module.resolve_job_dir(root, "Recover", video_id)
            self.assertFalse(reused)
            self.assertTrue(resolved.is_dir())
            self.assertEqual(lock_path.read_bytes(), b"0")

    def test_job_dir_resolver_lock_timeout_is_structured_and_retryable(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "resolve_job_dir_timeout_tests", RESOLVE_JOB_DIR_SCRIPT
        )
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            video_id = "timeout123"
            command = [
                sys.executable,
                str(RESOLVE_JOB_DIR_SCRIPT),
                "--root",
                str(root),
                "--title",
                "Timeout",
                "--video-id",
                video_id,
            ]
            with module.job_lock(root, video_id):
                result = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    timeout=10,
                )
            self.assertEqual(result.returncode, 1)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["reason"], "output_locked")
            self.assertTrue(payload["retryable"])

    def test_job_dir_resolver_distinguishes_case_only_video_ids(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "resolve_job_dir_case_tests", RESOLVE_JOB_DIR_SCRIPT
        )
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            upper, _ = module.resolve_job_dir(root, "Same title", "Abcdef12345")
            lower, _ = module.resolve_job_dir(root, "Same title", "abcdef12345")
            self.assertNotEqual(upper, lower)
            self.assertNotEqual(upper.name.casefold(), lower.name.casefold())

    def test_job_dir_resolver_rejects_hardlinked_lock_without_modifying_target(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "resolve_job_dir_hardlink_tests", RESOLVE_JOB_DIR_SCRIPT
        )
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as temp_dir, tempfile.TemporaryDirectory() as external_dir:
            root = Path(temp_dir)
            video_id = "hardlink123"
            external = Path(external_dir) / "external.txt"
            external.write_bytes(b"unchanged")
            digest = hashlib.sha256(video_id.encode("ascii")).hexdigest()[:16]
            lock_path = root / f".bilingual-job-{digest}.lock"
            try:
                os.link(external, lock_path)
            except OSError as exc:
                self.skipTest(f"hard links unavailable: {exc}")
            with self.assertRaises(module.JobResolverError) as raised:
                module.resolve_job_dir(root, "Safe", video_id)
            self.assertEqual(raised.exception.reason, "unsafe_lock_path")
            self.assertEqual(external.read_bytes(), b"unchanged")

    def test_concurrent_job_dir_resolvers_wait_and_reuse(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            command = [
                sys.executable,
                str(RESOLVE_JOB_DIR_SCRIPT),
                "--root",
                temp_dir,
                "--title",
                "Concurrent",
                "--video-id",
                "concurrent123",
            ]
            processes = [
                subprocess.Popen(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                )
                for _ in range(2)
            ]
            results = [process.communicate(timeout=10) for process in processes]
            self.assertEqual([process.returncode for process in processes], [0, 0])
            payloads = [json.loads(stdout) for stdout, _ in results]
            self.assertEqual(payloads[0]["job_dir"], payloads[1]["job_dir"])
            self.assertEqual(sorted(payload["reused"] for payload in payloads), [False, True])

    def test_job_dir_resolver_ignores_escape_symlink(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "resolve_job_dir_symlink_tests", RESOLVE_JOB_DIR_SCRIPT
        )
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as temp_dir, tempfile.TemporaryDirectory() as external_dir:
            root = Path(temp_dir)
            external = Path(external_dir)
            escape_manifest = external / module.MANIFEST_NAME
            escape_manifest.write_text(
                json.dumps({"video_id": "escape123"}), encoding="utf-8"
            )
            escape_link = root / "escape-link"
            try:
                escape_link.symlink_to(external, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"directory symlink unavailable: {exc}")
            resolved, _ = module.resolve_job_dir(root, "Safe", "escape123")
            self.assertEqual(resolved.parent, root.resolve())
            self.assertNotEqual(resolved, external.resolve())

    @unittest.skipUnless(os.name == "nt", "Windows junction regression")
    def test_job_dir_resolver_ignores_escape_junction(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "resolve_job_dir_junction_tests", RESOLVE_JOB_DIR_SCRIPT
        )
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as temp_dir, tempfile.TemporaryDirectory() as external_dir:
            root = Path(temp_dir)
            external = Path(external_dir)
            (external / module.MANIFEST_NAME).write_text(
                json.dumps({"video_id": "escape456"}), encoding="utf-8"
            )
            junction = root / "escape-junction"
            created = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(junction), str(external)],
                capture_output=True,
            )
            if created.returncode != 0:
                self.skipTest("directory junction unavailable")
            resolved, _ = module.resolve_job_dir(root, "Safe", "escape456")
            self.assertEqual(resolved.parent, root.resolve())
            self.assertNotEqual(resolved, external.resolve())


class RenderStyleRegressionTests(unittest.TestCase):
    def test_force_style_allows_automatic_chinese_wrapping(self) -> None:
        spec = importlib.util.spec_from_file_location("render_bilingual_video_for_tests", RENDER_SCRIPT)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        style = module.subtitle_filter(Path("subtitles.srt"), "Arial", 16, 8, 1.2)
        self.assertNotIn("WrapStyle=2", style)
        self.assertIn("FontSize=16", style)

    def test_same_output_cannot_be_locked_twice(self) -> None:
        spec = importlib.util.spec_from_file_location("render_bilingual_video_lock_tests", RENDER_SCRIPT)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "final.mp4"
            with module.output_lock(output):
                with self.assertRaises(module.RenderError) as raised:
                    with module.output_lock(output):
                        self.fail("second lock unexpectedly succeeded")
            self.assertEqual(raised.exception.reason, "output_locked")

    @unittest.skipUnless(os.name == "nt", "Windows paths are case-insensitive")
    def test_output_lock_normalizes_windows_path_case(self) -> None:
        spec = importlib.util.spec_from_file_location("render_bilingual_video_case_lock_tests", RENDER_SCRIPT)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as temp_dir:
            lower = Path(temp_dir) / "final.mp4"
            upper = Path(temp_dir) / "FINAL.MP4"
            with module.output_lock(lower):
                with self.assertRaises(module.RenderError) as raised:
                    with module.output_lock(upper):
                        self.fail("case-alias lock unexpectedly succeeded")
            self.assertEqual(raised.exception.reason, "output_locked")

    @unittest.skipUnless(os.name == "nt", "Windows paths use Win32 aliases")
    def test_windows_file_identity_normalizes_alias_forms(self) -> None:
        spec = importlib.util.spec_from_file_location("render_bilingual_video_alias_tests", RENDER_SCRIPT)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "final.mp4"
            aliases = (
                Path(str(output) + "."),
                Path(str(output) + " "),
                Path("\\\\?\\" + str(output)),
            )
            expected = module.file_identity(output)
            for alias in aliases:
                with self.subTest(alias=str(alias)):
                    self.assertEqual(module.file_identity(alias), expected)
                    with module.output_lock(output):
                        with self.assertRaises(module.RenderError):
                            with module.output_lock(alias):
                                self.fail("Windows alias lock unexpectedly succeeded")

    def test_render_run_ids_are_collision_resistant(self) -> None:
        spec = importlib.util.spec_from_file_location("render_bilingual_video_id_tests", RENDER_SCRIPT)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        first = module.render_run_id()
        second = module.render_run_id()
        self.assertNotEqual(first, second)
        self.assertIn(str(os.getpid()), first)


if __name__ == "__main__":
    unittest.main()
