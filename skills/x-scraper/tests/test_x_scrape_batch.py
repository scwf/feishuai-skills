import argparse
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import x_scrape
import x_scrape_batch


class XScrapeBatchTests(unittest.TestCase):
    def make_args(self, **overrides):
        values = {
            "targets": "X_OpenAI,X_Anthropic",
            "alias_file": "aliases.json",
            "limit": 20,
            "max_fetch": 500,
            "days_lookback": None,
            "since_date": None,
            "until_date": None,
            "output_dir": ".",
            "retweet_mode": "include",
            "include_replies": False,
            "request_timeout": 30,
            "max_retries": 3,
            "page_delay_min": 2.0,
            "page_delay_max": 5.0,
            "batch_size": 10,
            "target_delay_min": 10.0,
            "target_delay_max": 30.0,
            "batch_delay_min": 60.0,
            "batch_delay_max": 120.0,
        }
        values.update(overrides)
        return argparse.Namespace(**values)

    def test_parse_targets_supports_comma_separated_values(self):
        targets = x_scrape_batch.parse_targets("X_OpenAI, X_Anthropic, karpathy")
        self.assertEqual(targets, ["X_OpenAI", "X_Anthropic", "karpathy"])

    def test_parse_targets_supports_text_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "targets.txt"
            path.write_text("X_OpenAI\n# note\n\nX_Anthropic\n", encoding="utf-8")
            targets = x_scrape_batch.parse_targets(str(path))
        self.assertEqual(targets, ["X_OpenAI", "X_Anthropic"])

    def test_build_batch_output_dir_uses_timestamp(self):
        with mock.patch.object(x_scrape_batch, "datetime") as datetime_mock:
            datetime_mock.now.return_value = x_scrape.datetime(2026, 4, 3, 14, 30, 0)
            output_dir = x_scrape_batch.build_batch_output_dir(Path("."))
        self.assertEqual(output_dir, Path("x-posts-batch-20260403-143000"))

    def test_build_batch_category_index_uses_absolute_raw_root_and_grouped_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            raw_root = Path(tmpdir) / "raw"
            raw_root.mkdir()
            index = x_scrape_batch.build_batch_category_index(
                [
                    {
                        "categories": ["super_agent", "research_org"],
                        "relative_json_path": "NousResearch.json",
                    },
                    {
                        "categories": ["super_agent"],
                        "relative_json_path": "openclaw.json",
                    },
                ],
                raw_root,
            )

        self.assertEqual(index["raw_root"], str(raw_root.resolve()))
        self.assertEqual(index["categories"]["super_agent"], ["NousResearch.json", "openclaw.json"])
        self.assertEqual(index["categories"]["research_org"], ["NousResearch.json"])

    def test_render_agent_readme_includes_batch_category_index_path(self):
        readme = x_scrape_batch.render_agent_readme(
            category_index_path=Path("C:/tmp/x-posts-batch/batch_category_index.json")
        )

        self.assertIn("batch_category_index.json", readme)
        self.assertIn("Do not scan the whole `raw/` directory", readme)

    def test_render_summary_markdown_does_not_include_batch_category_index_path(self):
        markdown = x_scrape_batch.render_summary_markdown(
            {
                "run_status": "success",
                "total_targets": 1,
                "completed_targets": 1,
                "successful_targets": 1,
                "partial_targets": 0,
                "failed_targets": 0,
                "batch_size": 10,
                "target_delay_min": 10.0,
                "target_delay_max": 30.0,
                "batch_delay_min": 60.0,
                "batch_delay_max": 120.0,
                "targets": [],
            }
        )

        self.assertNotIn("Batch Category Index", markdown)
        self.assertNotIn("batch_category_index.json", markdown)

    def test_main_stops_after_first_rate_limit(self):
        args = self.make_args(targets="X_OpenAI,X_Anthropic,X_DeepSeek")
        with tempfile.TemporaryDirectory() as tmpdir:
            args.output_dir = tmpdir

            artifacts = [
                x_scrape.ScrapeArtifacts(
                    resolved_username="OpenAI",
                    resolved_alias="X_OpenAI",
                    mode="count",
                    limit=20,
                    max_fetch=20,
                    since_date=None,
                    run_result=x_scrape.FetchRunResult(
                        tweets=[],
                        status="success",
                        pages_fetched=1,
                        partial_failure_reason=None,
                    ),
                    exports=[{"id": "1"}],
                    json_path=Path(tmpdir) / "x-posts-batch-20260403-143000" / "OpenAI.json",
                    md_path=Path(tmpdir) / "x-posts-batch-20260403-143000" / "OpenAI.md",
                ),
                x_scrape.ScrapeArtifacts(
                    resolved_username="AnthropicAI",
                    resolved_alias="X_Anthropic",
                    mode="count",
                    limit=20,
                    max_fetch=20,
                    since_date=None,
                    run_result=x_scrape.FetchRunResult(
                        tweets=[],
                        status="failed",
                        pages_fetched=0,
                        partial_failure_reason="Rate limited for 900s",
                    ),
                    exports=[],
                    json_path=Path(tmpdir) / "x-posts-batch-20260403-143000" / "AnthropicAI.json",
                    md_path=Path(tmpdir) / "x-posts-batch-20260403-143000" / "AnthropicAI.md",
                ),
            ]

            with mock.patch.object(x_scrape_batch, "parse_args", return_value=args):
                with mock.patch.object(x_scrape_batch, "build_batch_output_dir", return_value=Path(tmpdir) / "x-posts-batch-20260403-143000"):
                    with mock.patch.object(x_scrape_batch, "sleep_with_log") as sleep_mock:
                        with mock.patch.object(x_scrape_batch, "load_default_env", return_value={}):
                            with mock.patch.object(
                                x_scrape,
                                "load_target_accounts",
                                return_value={
                                    "X_OpenAI": {
                                        "username": "OpenAI",
                                        "categories": ["model_vendor"],
                                    },
                                    "X_Anthropic": {
                                        "username": "AnthropicAI",
                                        "categories": ["model_vendor"],
                                    },
                                },
                            ):
                                with mock.patch.object(
                                    x_scrape.AccountPool,
                                    "from_env",
                                    return_value=mock.Mock(accounts=[]),
                                ):
                                    with mock.patch.object(x_scrape_batch, "json") as json_mock:
                                        json_mock.dump.side_effect = lambda data, handle, ensure_ascii, indent: handle.write("{}")
                                        with mock.patch.object(
                                            x_scrape,
                                            "scrape_target_to_files",
                                            side_effect=artifacts,
                                        ) as scrape_mock:
                                            with mock.patch("builtins.print") as print_mock:
                                                exit_code = x_scrape_batch.main()

        self.assertEqual(exit_code, 1)
        self.assertEqual(scrape_mock.call_count, 2)
        sleep_mock.assert_called_once()
        printed = " ".join(str(call.args[0]) for call in print_mock.call_args_list if call.args)
        self.assertIn("Stopped on target: X_Anthropic", printed)
        self.assertIn("Next target: X_DeepSeek", printed)
        self.assertIn("Saved batch category index:", printed)
        self.assertIn("Saved agent README:", printed)


if __name__ == "__main__":
    unittest.main()
