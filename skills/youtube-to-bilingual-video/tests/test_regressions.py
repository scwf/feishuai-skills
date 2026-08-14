from __future__ import annotations

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
CP936_ENV = {
    **os.environ,
    "PYTHONUTF8": "0",
    "PYTHONIOENCODING": "cp936",
}


def write_srt(path: Path, text: str) -> None:
    path.write_text(text.strip() + "\n", encoding="utf-8")


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

    def test_unicode_letter_and_symbol_changes_require_review(self) -> None:
        cases = [
            ("Use α and x ≥ 4.", "Use β and x > 4."),
            ("The café is open.", "The cafè is open."),
            ("The temperature is -5 C.", "The temperature is 5 C."),
            ("Utilization is 5%.", "Utilization is 5."),
            ("Version v1.2 costs $5.", "Version v12 costs 5."),
            ("Follow #DataAI.", "Follow DataAI."),
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
        result = subprocess.run(
            [
                sys.executable,
                str(VALIDATE_SCRIPT),
                str(srt),
                "--source-srt",
                str(source),
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

    def test_material_video_tail_gap_fails(self) -> None:
        result, report = self.run_validator(
            """
1
00:00:00,000 --> 00:00:01,000
你好
Hello
""",
            None,
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

    def test_report_cannot_alias_any_input(self) -> None:
        for target in ("srt", "source", "video"):
            with self.subTest(target=target):
                with tempfile.TemporaryDirectory() as temp_dir:
                    root = Path(temp_dir)
                    srt = root / "bilingual.srt"
                    source = root / "source.srt"
                    video = root / "video.mp4"
                    write_srt(srt, "1\n00:00:00,000 --> 00:00:01,000\n你好\nHello")
                    write_srt(source, "1\n00:00:00,000 --> 00:00:01,000\nHello")
                    video.write_bytes(b"video")
                    output = {"srt": srt, "source": source, "video": video}[target]
                    original = output.read_bytes()
                    result = subprocess.run(
                        [
                            sys.executable,
                            str(VALIDATE_SCRIPT),
                            str(srt),
                            "--source-srt",
                            str(source),
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
            write_srt(srt, "1\n00:00:00,000 --> 00:00:01,000\n你好\nHello")
            original = srt.read_bytes()
            result = subprocess.run(
                [
                    sys.executable,
                    str(VALIDATE_SCRIPT),
                    str(srt),
                    "--source-srt",
                    str(srt),
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
            None,
            env=CP936_ENV,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        self.assertEqual(report["status"], "ok")
        self.assertFalse(report["coverage_checked"])


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
            self.assertEqual(list(work_dir.glob("render-subtitle-*.srt")), [])

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


if __name__ == "__main__":
    unittest.main()
