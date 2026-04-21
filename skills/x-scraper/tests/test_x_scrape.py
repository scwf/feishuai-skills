import argparse
import io
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
import x_scrape_env
import x_scrape_export


class XScrapeTests(unittest.TestCase):
    def make_args(self, **overrides):
        values = {
            "target": "X_OpenAI",
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
        }
        values.update(overrides)
        return argparse.Namespace(**values)

    def test_load_default_env_prefers_file_values_over_environment(self):
        original = {key: os.environ.get(key) for key in x_scrape_env.ENV_KEYS}
        try:
            for key in x_scrape_env.ENV_KEYS:
                os.environ.pop(key, None)
            os.environ["TWITTER_AUTH_TOKEN"] = "from-env"

            env_file = Path(__file__).resolve().parent / "fake.env"
            with mock.patch.object(Path, "exists", return_value=True):
                with mock.patch.object(
                    x_scrape_env,
                    "parse_env_file",
                    return_value={
                        "TWITTER_AUTH_TOKEN": "from-file",
                        "TWITTER_CT0": "ct0-from-file",
                    },
                ):
                    loaded = x_scrape_env.load_default_env(env_file)

            self.assertEqual(os.environ["TWITTER_AUTH_TOKEN"], "from-file")
            self.assertEqual(os.environ["TWITTER_CT0"], "ct0-from-file")
            self.assertEqual(loaded["TWITTER_AUTH_TOKEN"], "from-file")
            self.assertEqual(loaded["TWITTER_CT0"], "ct0-from-file")
        finally:
            for key, value in original.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    def test_load_default_env_builds_multi_account_credentials_from_numbered_pairs(self):
        original = {key: os.environ.get(key) for key in x_scrape_env.ENV_KEYS}
        try:
            for key in x_scrape_env.ENV_KEYS:
                os.environ.pop(key, None)

            env_file = Path(__file__).resolve().parent / "fake.env"
            with mock.patch.object(Path, "exists", return_value=True):
                with mock.patch.object(
                    x_scrape_env,
                    "parse_env_file",
                    return_value={
                        "TWITTER_AUTH_TOKEN_1": "token-1",
                        "TWITTER_CT0_1": "ct0-1",
                        "TWITTER_AUTH_TOKEN_2": "token-2",
                        "TWITTER_CT0_2": "ct0-2",
                    },
                ):
                    loaded = x_scrape_env.load_default_env(env_file)

            self.assertEqual(
                os.environ["X_AUTH_CREDENTIALS"],
                "token-1:ct0-1|token-2:ct0-2",
            )
            self.assertEqual(
                loaded["X_AUTH_CREDENTIALS"],
                "token-1:ct0-1|token-2:ct0-2",
            )
        finally:
            for key, value in original.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    def test_validate_args_rejects_inverted_date_range(self):
        args = self.make_args(since_date="2026-03-10", until_date="2026-03-01")
        with self.assertRaises(SystemExit) as exc:
            x_scrape.validate_args(args)
        self.assertIn("--since-date must be on or before --until-date.", str(exc.exception))

    def test_validate_args_rejects_invalid_page_delay_bounds(self):
        args = self.make_args(page_delay_min=6.0, page_delay_max=2.0)
        with self.assertRaises(SystemExit) as exc:
            x_scrape.validate_args(args)
        self.assertIn("--page-delay-min must be <= --page-delay-max.", str(exc.exception))

    def test_load_target_accounts_requires_object_entries(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            alias_file = Path(tmpdir) / "aliases.json"
            alias_file.write_text('{"X_OpenAI":"OpenAI"}', encoding="utf-8")

            with self.assertRaises(ValueError) as exc:
                x_scrape.load_target_accounts(alias_file)

        self.assertIn("must be an object with username/categories", str(exc.exception))

    def test_load_target_accounts_parses_username_and_categories(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            alias_file = Path(tmpdir) / "aliases.json"
            alias_file.write_text(
                '{"X_OpenAI":{"username":"OpenAI","categories":["model_vendor","devtools_agent"]}}',
                encoding="utf-8",
            )

            accounts = x_scrape.load_target_accounts(alias_file)
            alias_map = x_scrape.load_alias_map(alias_file)

        self.assertEqual(
            accounts,
            {
                "X_OpenAI": {
                    "username": "OpenAI",
                    "categories": ["model_vendor", "devtools_agent"],
                }
            },
        )
        self.assertEqual(alias_map, {"X_OpenAI": "OpenAI"})

    def test_compute_since_date_mode_limit_and_max_fetch_for_days_lookback_args(self):
        args = self.make_args(days_lookback=7, limit=30)
        real_datetime = x_scrape.datetime

        with mock.patch.object(x_scrape, "datetime") as datetime_mock:
            datetime_mock.now.return_value = real_datetime(2026, 3, 24, tzinfo=x_scrape.timezone.utc)
            datetime_mock.strptime = real_datetime.strptime
            since_date = x_scrape.compute_since_date(args)

        mode = x_scrape.compute_mode(args)
        limit = x_scrape.compute_limit(args, mode)
        max_fetch = x_scrape.compute_max_fetch(args, mode)

        self.assertEqual(since_date, "2026-03-17")
        self.assertEqual(mode, "time_range")
        self.assertEqual(limit, 30)
        self.assertEqual(max_fetch, 500)

    def test_compute_default_limit_and_max_fetch_for_count_mode(self):
        args = self.make_args(limit=None)

        mode = x_scrape.compute_mode(args)
        limit = x_scrape.compute_limit(args, mode)
        max_fetch = x_scrape.compute_max_fetch(args, mode)

        self.assertEqual(mode, "count")
        self.assertEqual(limit, 20)
        self.assertEqual(max_fetch, 20)

    def test_compute_default_limit_and_max_fetch_for_time_range_mode(self):
        args = self.make_args(limit=None, days_lookback=7)

        mode = x_scrape.compute_mode(args)
        limit = x_scrape.compute_limit(args, mode)
        max_fetch = x_scrape.compute_max_fetch(args, mode)

        self.assertEqual(mode, "time_range")
        self.assertIsNone(limit)
        self.assertEqual(max_fetch, 500)

    def test_get_user_tweets_all_reports_partial_success(self):
        pool = x_scrape.AccountPool([("auth", "ct0")])
        client = x_scrape.XClient(pool)

        first_tweet = x_scrape.TweetRecord(
            id="1",
            text="hello",
            username="OpenAI",
            display_name="OpenAI",
        )
        calls = {"count": 0}

        def fake_get_user_tweets(*, user_id, count, cursor, include_replies):
            calls["count"] += 1
            if calls["count"] == 1:
                return [first_tweet], "cursor-1"
            raise x_scrape.XClientError("rate limited mid-run")

        client.get_user_tweets = fake_get_user_tweets  # type: ignore[method-assign]

        result = client.get_user_tweets_all(
            user_id="123",
            max_fetch=10,
            since_date=None,
            include_replies=False,
            retweet_mode="include",
            page_delay=(0.0, 0.0),
        )

        self.assertEqual(result.status, "partial_success")
        self.assertEqual(result.pages_fetched, 1)
        self.assertEqual(result.partial_failure_reason, "rate limited mid-run")
        self.assertEqual(len(result.tweets), 1)

    def test_request_with_retry_is_fail_fast_on_rate_limit(self):
        pool = x_scrape.AccountPool([("auth", "ct0")])
        client = x_scrape.XClient(pool, max_retries=3)
        calls = {"count": 0}

        def fake_make_request(url, params, account):
            calls["count"] += 1
            raise x_scrape.RateLimitError(900)

        client._make_request = fake_make_request  # type: ignore[method-assign]

        with self.assertRaises(x_scrape.RateLimitError):
            client._request_with_retry("https://x.com/i/api/graphql/test/endpoint", {})

        self.assertEqual(calls["count"], 1)

    def test_request_with_retry_retries_timeout_once_on_same_account(self):
        pool = x_scrape.AccountPool([("auth", "ct0"), ("auth2", "ct02")])
        client = x_scrape.XClient(pool, max_retries=1)
        seen_accounts = []
        calls = {"count": 0}

        def fake_make_request(url, params, account):
            calls["count"] += 1
            seen_accounts.append(account.index)
            if calls["count"] == 1:
                raise x_scrape.RequestTimeoutError("temporary timeout")
            return {"ok": True}

        client._make_request = fake_make_request  # type: ignore[method-assign]

        with mock.patch.object(x_scrape.time, "sleep") as sleep_mock:
            result = client._request_with_retry("https://x.com/i/api/graphql/test/endpoint", {})

        self.assertEqual(result, {"ok": True})
        self.assertEqual(calls["count"], 2)
        self.assertEqual(seen_accounts, [0, 0])
        sleep_mock.assert_called_once_with(x_scrape.RETRYABLE_BACKOFF_SECONDS)

    def test_request_with_retry_stops_after_retry_budget_for_network_error(self):
        pool = x_scrape.AccountPool([("auth", "ct0"), ("auth2", "ct02")])
        client = x_scrape.XClient(pool, max_retries=1)
        seen_accounts = []
        calls = {"count": 0}

        def fake_make_request(url, params, account):
            calls["count"] += 1
            seen_accounts.append(account.index)
            raise x_scrape.NetworkError("temporary network failure")

        client._make_request = fake_make_request  # type: ignore[method-assign]

        with mock.patch.object(x_scrape.time, "sleep") as sleep_mock:
            with self.assertRaises(x_scrape.NetworkError):
                client._request_with_retry("https://x.com/i/api/graphql/test/endpoint", {})

        self.assertEqual(calls["count"], 2)
        self.assertEqual(seen_accounts, [0, 0])
        sleep_mock.assert_called_once_with(x_scrape.RETRYABLE_BACKOFF_SECONDS)

    def test_build_run_metadata_includes_run_status_fields(self):
        args = self.make_args(target="@OpenAI", until_date="2026-03-24")
        run_result = x_scrape.FetchRunResult(
            tweets=[],
            status="partial_success",
            pages_fetched=2,
            partial_failure_reason="temporary error",
        )
        metadata = x_scrape_export.build_run_metadata(
            args=args,
            resolved_username="OpenAI",
            resolved_alias="X_OpenAI",
            mode="time_range",
            limit=20,
            max_fetch=500,
            since_date="2026-03-01",
            run_result=run_result,
            exports=[],
            env_file_used=True,
        )

        self.assertEqual(metadata["mode"], "time_range")
        self.assertEqual(metadata["limit"], 20)
        self.assertEqual(metadata["max_fetch"], 500)
        self.assertEqual(metadata["run_status"], "partial_success")
        self.assertEqual(metadata["pages_fetched"], 2)
        self.assertEqual(metadata["partial_failure_reason"], "temporary error")
        self.assertTrue(metadata["env_file_used"])

    def test_build_output_paths_creates_timestamped_run_directory(self):
        with mock.patch.object(x_scrape_export, "datetime") as datetime_mock:
            datetime_mock.now.return_value = x_scrape.datetime(2026, 4, 3, 11, 30, 0)
            json_path, md_path = x_scrape_export.build_output_paths(Path("."), "OpenAI")

        self.assertEqual(json_path, Path("x-posts-20260403-113000") / "OpenAI.json")
        self.assertEqual(md_path, Path("x-posts-20260403-113000") / "OpenAI.md")

    def test_get_user_tweets_all_stops_after_consecutive_no_progress_pages(self):
        pool = x_scrape.AccountPool([("auth", "ct0")])
        client = x_scrape.XClient(pool)
        calls = {"count": 0}

        kept_tweet = x_scrape.TweetRecord(
            id="1",
            text="hello",
            username="OpenAI",
            display_name="OpenAI",
        )
        duplicate_tweet = x_scrape.TweetRecord(
            id="1",
            text="hello",
            username="OpenAI",
            display_name="OpenAI",
        )

        def fake_get_user_tweets(*, user_id, count, cursor, include_replies):
            calls["count"] += 1
            if calls["count"] == 1:
                return [kept_tweet], "cursor-1"
            return [duplicate_tweet], f"cursor-{calls['count']}"

        client.get_user_tweets = fake_get_user_tweets  # type: ignore[method-assign]

        result = client.get_user_tweets_all(
            user_id="123",
            max_fetch=10,
            since_date=None,
            include_replies=False,
            retweet_mode="include",
            page_delay=(0.0, 0.0),
        )

        self.assertEqual(result.status, "success")
        self.assertEqual(len(result.tweets), 1)
        self.assertEqual(calls["count"], 4)

    def test_main_cli_smoke_test_for_failed_fetch_without_network(self):
        args = self.make_args(alias_file="aliases.json", output_dir="out")
        fake_stdout = io.StringIO()

        with mock.patch.object(x_scrape, "parse_args", return_value=args):
            with mock.patch.object(x_scrape, "validate_args"):
                with mock.patch.object(x_scrape, "load_alias_map", return_value={"X_OpenAI": "OpenAI"}):
                    with mock.patch.object(x_scrape, "resolve_target", return_value=("OpenAI", "X_OpenAI")):
                        with mock.patch.object(x_scrape, "compute_since_date", return_value=None):
                            with mock.patch.object(x_scrape, "compute_mode", return_value="count"):
                                with mock.patch.object(x_scrape, "compute_limit", return_value=20):
                                    with mock.patch.object(x_scrape, "compute_max_fetch", return_value=20):
                                        with mock.patch.object(x_scrape.Path, "mkdir"):
                                            with mock.patch.object(x_scrape, "load_default_env", return_value={}):
                                                with mock.patch.object(
                                                    x_scrape.AccountPool,
                                                    "from_env",
                                                    return_value=mock.Mock(accounts=[]),
                                                ):
                                                    with mock.patch.object(
                                                        x_scrape.XClient,
                                                        "get_user_id",
                                                        return_value="123",
                                                    ):
                                                        with mock.patch.object(
                                                            x_scrape.XClient,
                                                            "get_user_tweets_all",
                                                            return_value=x_scrape.FetchRunResult(
                                                                tweets=[],
                                                                status="failed",
                                                                pages_fetched=0,
                                                                partial_failure_reason="missing credentials",
                                                            ),
                                                        ):
                                                            with mock.patch.object(
                                                                x_scrape_export,
                                                                "build_output_paths",
                                                                return_value=(Path("a.json"), Path("a.md")),
                                                            ):
                                                                with mock.patch("builtins.print") as print_mock:
                                                                    with mock.patch("pathlib.Path.open", mock.mock_open()):
                                                                        exit_code = x_scrape.main()

        self.assertEqual(exit_code, 1)
        printed = " ".join(str(call.args[0]) for call in print_mock.call_args_list if call.args)
        self.assertIn("Run status: failed", printed)
        self.assertIn("Partial failure reason: missing credentials", printed)


if __name__ == "__main__":
    unittest.main()
