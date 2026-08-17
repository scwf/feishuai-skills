import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import BytesIO, StringIO, TextIOWrapper
from pathlib import Path
from unittest import mock


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import youtube_video_meta
import youtube_download


class FakeYoutubeDL:
    def __init__(self, opts):
        self.opts = opts

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def extract_info(self, url, download):
        self.url = url
        self.download = download
        return {
            "id": "abc123",
            "title": "Demo Video",
            "upload_date": "20260604",
            "channel": "Demo Channel",
            "channel_id": "UCdemo",
            "duration": 125,
            "description": "Line one\nLine two",
            "thumbnail": "https://example.com/thumb.jpg",
            "webpage_url": url,
            "extractor": "youtube",
        }


class YoutubeVideoMetaTests(unittest.TestCase):
    def test_normalize_url_accepts_video_url_forms(self):
        self.assertEqual(
            youtube_video_meta.normalize_url(" https://www.youtube.com/watch?v=abc "),
            "https://www.youtube.com/watch?v=abc",
        )
        self.assertEqual(
            youtube_video_meta.normalize_url("https://youtu.be/abc"),
            "https://youtu.be/abc",
        )
        self.assertEqual(
            youtube_video_meta.normalize_url("https://www.youtube.com/shorts/abc"),
            "https://www.youtube.com/shorts/abc",
        )

    def test_normalize_url_rejects_channel_url(self):
        with self.assertRaises(ValueError):
            youtube_video_meta.normalize_url("https://www.youtube.com/@OpenAI")

    def test_collect_payload_maps_description_and_duration(self):
        payload = youtube_video_meta.collect_payload(
            "https://youtu.be/abc",
            {
                "id": "abc",
                "title": "Title",
                "upload_date": "20260604",
                "channel": "Channel",
                "channel_id": "UCabc",
                "duration": "65",
                "description": "Description",
                "thumbnails": [{"url": "small"}, {"url": "large"}],
            },
            Path("out.json"),
            Path("out.md"),
        )

        self.assertEqual(payload["mode"], "single_video_metadata")
        self.assertEqual(payload["published_at"], "2026-06-04")
        self.assertEqual(payload["description"], "Description")
        self.assertEqual(payload["duration_seconds"], 65)
        self.assertEqual(payload["duration_text"], "1:05")
        self.assertEqual(payload["thumbnail_url"], "large")

    def test_main_extracts_metadata_without_download(self):
        fake_module = type("FakeModule", (), {"YoutubeDL": FakeYoutubeDL})

        with tempfile.TemporaryDirectory() as temp_dir:
            with mock.patch.object(youtube_video_meta, "get_yt_dlp_module", return_value=fake_module):
                with mock.patch(
                    "sys.argv",
                    [
                        "youtube_video_meta.py",
                        "https://www.youtube.com/watch?v=abc123",
                        "--output-dir",
                        temp_dir,
                    ],
                ):
                    with redirect_stdout(StringIO()):
                        self.assertEqual(youtube_video_meta.main(), 0)

            outputs = list(Path(temp_dir).glob("abc123_*.json"))
            self.assertEqual(len(outputs), 1)
            payload = outputs[0].read_text(encoding="utf-8")
            self.assertIn('"status": "ok"', payload)
            self.assertIn("Line one", payload)
            self.assertEqual(len(list(Path(temp_dir).glob("abc123_*.md"))), 1)

    def test_unicode_description_is_written_even_on_legacy_console(self) -> None:
        description = "中文简介\u00a0“quotes”—dash"
        title = "发布：AI — 更新"

        class UnicodeFakeYoutubeDL(FakeYoutubeDL):
            def extract_info(self, url, download):
                info = super().extract_info(url, download)
                info["title"] = title
                info["description"] = description
                return info

        fake_module = type("FakeModule", (), {"YoutubeDL": UnicodeFakeYoutubeDL})
        with tempfile.TemporaryDirectory() as temp_dir:
            stdout = StringIO()
            with mock.patch.object(youtube_video_meta, "get_yt_dlp_module", return_value=fake_module):
                with mock.patch(
                    "sys.argv",
                    [
                        "youtube_video_meta.py",
                        "https://www.youtube.com/watch?v=abc123",
                        "--output-dir",
                        temp_dir,
                    ],
                ):
                    with redirect_stdout(stdout):
                        self.assertEqual(youtube_video_meta.main(), 0)

            printed = json.loads(stdout.getvalue())
            self.assertEqual(printed["status"], "ok")
            self.assertEqual(printed["mode"], "single_video_metadata")
            self.assertNotIn("description", printed)
            self.assertNotIn("title", printed)
            self.assertTrue(printed["json_path"])

            outputs = list(Path(temp_dir).glob("abc123_*.json"))
            self.assertEqual(len(outputs), 1)
            on_disk = json.loads(outputs[0].read_text(encoding="utf-8"))
            self.assertEqual(on_disk["description"], description)
            self.assertIn("\u00a0", outputs[0].read_text(encoding="utf-8"))
            self.assertIn("中文简介", outputs[0].read_text(encoding="utf-8"))

    def test_console_summaries_exclude_large_metadata_fields(self) -> None:
        payload = {
            "status": "ok",
            "mode": "single_video_metadata",
            "video_id": "abc",
            "title": "Large title",
            "description": "Large description",
            "json_path": "result.json",
            "markdown_path": "result.md",
            "validation": {"ok": True},
        }
        summary = youtube_video_meta.build_console_summary(payload)
        self.assertNotIn("title", summary)
        self.assertNotIn("description", summary)
        self.assertEqual(summary["json_path"], "result.json")

        download_summary = youtube_download.build_console_summary(
            {
                "status": "ok",
                "mode": "video",
                "video_id": "abc",
                "title": "Large title",
                "description": "Large description",
                "output_path": "video.mp4",
                "sidecar_path": "video.download.json",
            }
        )
        self.assertNotIn("title", download_summary)
        self.assertNotIn("description", download_summary)
        self.assertEqual(download_summary["output_path"], "video.mp4")

    def test_console_encode_failure_does_not_fail_after_files_exist(self) -> None:
        class RaisingStdout:
            encoding = "gbk"
            closed = False

            def write(self, _s: str) -> int:
                raise UnicodeEncodeError("gbk", "x", 0, 1, "strict")

            def flush(self) -> None:
                return None

        fake_module = type("FakeModule", (), {"YoutubeDL": FakeYoutubeDL})
        with tempfile.TemporaryDirectory() as temp_dir:
            with mock.patch.object(youtube_video_meta, "get_yt_dlp_module", return_value=fake_module):
                with mock.patch(
                    "sys.argv",
                    [
                        "youtube_video_meta.py",
                        "https://www.youtube.com/watch?v=abc123",
                        "--output-dir",
                        temp_dir,
                    ],
                ):
                    with mock.patch("sys.stdout", RaisingStdout()):
                        self.assertEqual(youtube_video_meta.main(), 0)
            self.assertTrue(list(Path(temp_dir).glob("abc123_*.json")))
            self.assertTrue(list(Path(temp_dir).glob("abc123_*.md")))


class ConsoleOutputTests(unittest.TestCase):
    def test_gbk_stdout_accepts_cjk_nbsp_quotes_and_dash(self) -> None:
        import console_output

        payload = {"description": "中文简介\u00a0“quotes”—dash"}
        buffer = BytesIO()
        stream = TextIOWrapper(buffer, encoding="gbk", errors="strict", newline="\n")
        with mock.patch("sys.stdout", stream):
            console_output.emit_stdout_json(payload)
        stream.flush()
        printed = json.loads(buffer.getvalue().decode("gbk"))
        self.assertEqual(printed["description"], payload["description"])

    def test_closed_stdout_does_not_raise(self) -> None:
        import console_output

        class ClosedStdout:
            encoding = "utf-8"

            def write(self, _text: str) -> int:
                raise BrokenPipeError("pipe closed")

            def flush(self) -> None:
                raise BrokenPipeError("pipe closed")

        with mock.patch("sys.stdout", ClosedStdout()):
            console_output.emit_stdout_json({"status": "ok"})
            replacement = sys.stdout
        if hasattr(replacement, "close"):
            replacement.close()

    def test_broken_pipe_process_still_exits_zero(self) -> None:
        code = (
            "import sys,time;"
            f"sys.path.insert(0,{str(SCRIPT_DIR)!r});"
            "from console_output import emit_stdout_json;"
            "time.sleep(0.2);"
            "emit_stdout_json({'status':'ok'})"
        )
        process = subprocess.Popen(
            [sys.executable, "-c", code],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        assert process.stdout is not None
        assert process.stderr is not None
        process.stdout.close()
        stderr = process.stderr.read().decode("utf-8", errors="replace")
        process.stderr.close()
        returncode = process.wait(timeout=5)
        self.assertEqual(returncode, 0, stderr)
        self.assertNotIn("Exception ignored", stderr)


if __name__ == "__main__":
    unittest.main()
