from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
AUDIT_SCRIPT = SKILL_ROOT / "scripts" / "audit_subtitle_changes.py"
RENDER_SCRIPT = SKILL_ROOT / "scripts" / "render_bilingual_video.py"


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


class RenderPathRegressionTests(unittest.TestCase):
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
            job_dir = Path(temp_dir) / "author's [job], v1"
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
            )

            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "ok")
            self.assertEqual(report["font_size"], 16.0)
            self.assertTrue(output.is_file())
            self.assertEqual(list(work_dir.glob("render-subtitle-*.srt")), [])


if __name__ == "__main__":
    unittest.main()
