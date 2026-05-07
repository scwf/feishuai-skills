import sys
import unittest
from pathlib import Path
from unittest import mock


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import youtube_channel_meta


class YoutubeChannelMetaTests(unittest.TestCase):
    def test_feed_candidates_prefers_channel_rss_then_playlist_fallbacks(self):
        candidates = youtube_channel_meta.feed_candidates("UCabcdef")

        self.assertEqual(
            candidates,
            [
                (
                    "channel_id",
                    "https://www.youtube.com/feeds/videos.xml?channel_id=UCabcdef",
                ),
                (
                    "uploads_playlist",
                    "https://www.youtube.com/feeds/videos.xml?playlist_id=UUabcdef",
                ),
                (
                    "videos_playlist",
                    "https://www.youtube.com/feeds/videos.xml?playlist_id=UULFabcdef",
                ),
                (
                    "shorts_playlist",
                    "https://www.youtube.com/feeds/videos.xml?playlist_id=UUSHabcdef",
                ),
            ],
        )

    def test_fetch_feed_records_failed_channel_attempt_before_playlist_success(self):
        calls = []

        def fake_fetch(url, timeout):
            calls.append((url, timeout))
            if "channel_id=" in url:
                raise youtube_channel_meta.FetchTextError(
                    url,
                    [{"client": "test", "attempt": 1, "error": "HTTP 404"}],
                )
            return "<feed />", [{"client": "test", "attempt": 1, "status_code": 200}]

        with mock.patch.object(youtube_channel_meta, "fetch_text_with_attempts", fake_fetch):
            rss_url, xml_text, feed_fetch = youtube_channel_meta.fetch_feed("UCabcdef", 12)

        self.assertEqual(xml_text, "<feed />")
        self.assertEqual(
            rss_url,
            "https://www.youtube.com/feeds/videos.xml?playlist_id=UUabcdef",
        )
        self.assertEqual(feed_fetch["selected_feed_type"], "uploads_playlist")
        self.assertEqual(len(feed_fetch["failures"]), 1)
        self.assertEqual(feed_fetch["failures"][0]["feed_type"], "channel_id")
        self.assertEqual(feed_fetch["failures"][0]["attempts"][0]["error"], "HTTP 404")
        self.assertEqual(len(calls), 2)

    def test_fetch_feed_error_keeps_all_failed_candidate_attempts(self):
        def fake_fetch(url, timeout):
            raise youtube_channel_meta.FetchTextError(
                url,
                [{"client": "test", "attempt": 1, "error": "HTTP 404"}],
            )

        with mock.patch.object(youtube_channel_meta, "fetch_text_with_attempts", fake_fetch):
            with self.assertRaises(youtube_channel_meta.FeedFetchError) as exc:
                youtube_channel_meta.fetch_feed("UCabcdef", 12)

        self.assertEqual(exc.exception.channel_id, "UCabcdef")
        self.assertEqual(len(exc.exception.failures), 4)
        self.assertEqual(
            [failure["feed_type"] for failure in exc.exception.failures],
            ["channel_id", "uploads_playlist", "videos_playlist", "shorts_playlist"],
        )
        self.assertTrue(
            all(failure["attempts"][0]["error"] == "HTTP 404" for failure in exc.exception.failures)
        )


if __name__ == "__main__":
    unittest.main()
