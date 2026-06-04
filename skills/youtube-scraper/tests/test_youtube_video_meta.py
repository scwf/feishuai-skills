import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import youtube_video_meta


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


if __name__ == "__main__":
    unittest.main()
