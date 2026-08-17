import json
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import youtube_batch_meta


class YoutubeBatchMetaTests(unittest.TestCase):
    def test_read_targets_file_supports_text_comments_and_blank_lines(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "targets.txt"
            path.write_text("\n# comment\nYT_OpenAI\n @OpenAI \n\n", encoding="utf-8")

            self.assertEqual(
                youtube_batch_meta.read_targets_file(path),
                ["YT_OpenAI", "@OpenAI"],
            )

    def test_read_targets_file_supports_json_list_and_object(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            list_path = Path(temp_dir) / "targets.json"
            list_path.write_text(json.dumps(["YT_OpenAI", " @OpenAI "]), encoding="utf-8")
            object_path = Path(temp_dir) / "targets_object.json"
            object_path.write_text(json.dumps({"targets": ["UCabc"]}), encoding="utf-8")

            self.assertEqual(
                youtube_batch_meta.read_targets_file(list_path),
                ["YT_OpenAI", "@OpenAI"],
            )
            self.assertEqual(youtube_batch_meta.read_targets_file(object_path), ["UCabc"])

    def test_read_alias_targets_supports_default_catalog_shape(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "aliases.json"
            path.write_text(
                json.dumps(
                    [
                        {"alias": "YT_OpenAI", "channel_id": "UCabc"},
                        {"alias": "YT_claude", "channel_id": "UCdef"},
                    ]
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                youtube_batch_meta.read_alias_targets(path),
                ["YT_OpenAI", "YT_claude"],
            )

    def test_collect_targets_can_include_all_configured_aliases(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "aliases.json"
            path.write_text(json.dumps({"YT_OpenAI": "UCabc", "YT_claude": "UCdef"}), encoding="utf-8")

            self.assertEqual(
                youtube_batch_meta.collect_targets(["@OpenAI"], None, True, str(path)),
                ["@OpenAI", "YT_OpenAI", "YT_claude"],
            )

    def test_collect_targets_deduplicates_while_preserving_order(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            targets_path = Path(temp_dir) / "targets.txt"
            targets_path.write_text("YT_OpenAI\nYT_claude\nYT_OpenAI\n", encoding="utf-8")
            aliases_path = Path(temp_dir) / "aliases.json"
            aliases_path.write_text(json.dumps({"YT_claude": "UCdef", "YT_LangChain": "UCghi"}), encoding="utf-8")

            self.assertEqual(
                youtube_batch_meta.collect_targets(
                    ["YT_OpenAI", "YT_OpenAI"],
                    str(targets_path),
                    True,
                    str(aliases_path),
                ),
                ["YT_OpenAI", "YT_claude", "YT_LangChain"],
            )

    def test_build_child_command_forwards_shared_options(self):
        args = Namespace(
            alias_file="aliases.json",
            limit=5,
            days_lookback=7,
            since_date=None,
            until_date="2026-05-09",
            request_timeout=12,
            skip_duration=True,
        )

        command = youtube_batch_meta.build_child_command(args, "YT_OpenAI", Path("out"))

        self.assertIn("youtube_channel_meta.py", command[1])
        self.assertEqual(command[2:5], ["YT_OpenAI", "--output-dir", "out"])
        self.assertIn("--alias-file", command)
        self.assertIn("aliases.json", command)
        self.assertIn("--limit", command)
        self.assertIn("5", command)
        self.assertIn("--days-lookback", command)
        self.assertIn("7", command)
        self.assertIn("--until-date", command)
        self.assertIn("2026-05-09", command)
        self.assertIn("--request-timeout", command)
        self.assertIn("12", command)
        self.assertIn("--skip-duration", command)

    def test_summarize_status_reports_partial_failure_and_warnings(self):
        self.assertEqual(
            youtube_batch_meta.summarize_status(
                [
                    {"ok": True, "payload": {"status": "ok"}},
                    {"ok": False, "payload": {"status": "error"}},
                ]
            ),
            "partial_failure",
        )
        self.assertEqual(
            youtube_batch_meta.summarize_status(
                [{"ok": True, "payload": {"status": "ok_with_warnings"}}]
            ),
            "ok_with_warnings",
        )
        self.assertEqual(
            youtube_batch_meta.summarize_status([{"ok": True, "payload": {"status": "ok"}}]),
            "ok",
        )

    def test_console_summary_excludes_per_target_results(self):
        summary = {
            "status": "partial_failure",
            "target_count": 100,
            "attempted_count": 100,
            "success_count": 0,
            "failure_count": 100,
            "output_dir": "out",
            "batch_json_path": "out/summary.json",
            "batch_markdown_path": "out/summary.md",
            "results": [
                {
                    "target": f"target-{index}",
                    "stderr_tail": "x" * 4000,
                    "payload": {"message": "y" * 1000},
                }
                for index in range(100)
            ],
        }
        console = youtube_batch_meta.build_console_summary(summary)
        self.assertNotIn("results", console)
        self.assertEqual(console["failure_count"], 100)
        self.assertLess(len(json.dumps(console)), 1000)

    def test_success_stdout_is_rejected_when_child_artifacts_are_missing(self):
        args = Namespace(
            alias_file=None,
            limit=None,
            days_lookback=None,
            since_date=None,
            until_date=None,
            request_timeout=None,
            skip_duration=False,
        )
        stdout = json.dumps(
            {
                "status": "ok",
                "json_path": "missing.json",
                "markdown_path": "missing.md",
            }
        )
        completed = CompletedProcess([], 0, stdout=stdout, stderr="")

        with patch.object(youtube_batch_meta.subprocess, "run", return_value=completed):
            result = youtube_batch_meta.run_one_target(args, "YT_Test", Path("out"))

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["payload"]["error_type"], "missing_child_artifact")

    def test_disk_json_status_is_authoritative_for_child_success(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            json_path = root / "child.json"
            markdown_path = root / "child.md"
            json_path.write_text(json.dumps({"status": "error"}), encoding="utf-8")
            markdown_path.write_text("# child\n", encoding="utf-8")
            child, error = youtube_batch_meta.read_child_artifacts(
                {
                    "status": "ok",
                    "json_path": str(json_path),
                    "markdown_path": str(markdown_path),
                }
            )

            self.assertIsNone(child)
            self.assertEqual(error["error_type"], "child_artifact_not_successful")

    def test_valid_disk_artifacts_override_stale_stdout_error(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            json_path = root / "child.json"
            markdown_path = root / "child.md"
            validation = {"ok": True, "warnings": []}
            json_path.write_text(
                json.dumps(
                    {
                        "status": "ok",
                        "query_target": "YT_Test",
                        "resolved_channel_id": "DISK",
                        "resolved_alias": "disk-alias",
                        "resolution_source": "alias",
                        "since_date": "2026-08-01",
                        "until_date": "2026-08-15",
                        "effective_limit": 1,
                        "include_duration": True,
                        "video_count": 1,
                        "items": [{"video_id": "disk-video"}],
                        "rss_fetch": {
                            "selected_feed_type": "channel",
                            "selected_feed_url": "https://disk.example/rss",
                        },
                        "validation": validation,
                    }
                ),
                encoding="utf-8",
            )
            markdown_path.write_text("# child\n", encoding="utf-8")
            args = Namespace(
                alias_file=None,
                limit=None,
                days_lookback=None,
                since_date=None,
                until_date=None,
                request_timeout=None,
                skip_duration=False,
            )
            stdout = json.dumps(
                {
                    "status": "error",
                    "resolved_channel_id": "STDOUT",
                    "video_count": 999,
                    "json_path": str(json_path),
                    "markdown_path": str(markdown_path),
                }
            )
            completed = CompletedProcess([], 0, stdout=stdout, stderr="")

            with patch.object(youtube_batch_meta.subprocess, "run", return_value=completed):
                result = youtube_batch_meta.run_one_target(args, "YT_Test", root)

            self.assertTrue(result["ok"])
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["payload"]["validation"], validation)
            self.assertEqual(result["payload"]["resolved_channel_id"], "DISK")
            self.assertEqual(result["payload"]["video_count"], 1)
            self.assertNotIn("items", result["payload"])


if __name__ == "__main__":
    unittest.main()
