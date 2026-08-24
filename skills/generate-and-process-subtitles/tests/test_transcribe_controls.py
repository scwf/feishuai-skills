from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


SKILL_ROOT = Path(__file__).resolve().parents[1]
CLI_PATH = SKILL_ROOT / "scripts" / "generate_and_process_subtitles.py"
VALIDATE_SCRIPT = (
    SKILL_ROOT.parent
    / "youtube-to-bilingual-video"
    / "scripts"
    / "validate_bilingual_srt.py"
)
if str(SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILL_ROOT))

CLI_SPEC = importlib.util.spec_from_file_location("subtitle_cli_for_tests", CLI_PATH)
assert CLI_SPEC and CLI_SPEC.loader
CLI = importlib.util.module_from_spec(CLI_SPEC)
CLI_SPEC.loader.exec_module(CLI)

from subtitle_tools import ASRData, ASRDataSeg, core  # noqa: E402
from subtitle_tools.asr.faster_whisper import FasterWhisperASR  # noqa: E402
from subtitle_tools.config import TranscribeConfig  # noqa: E402


class TranscribeControlTests(unittest.TestCase):
    def test_parser_accepts_targeted_no_vad_controls(self) -> None:
        args = CLI.build_parser().parse_args(
            [
                "transcribe",
                "input.mp4",
                "--language",
                "en",
                "--start-seconds",
                "12.5",
                "--end-seconds",
                "18",
                "--no-vad",
            ]
        )

        self.assertEqual(CLI.resolve_clip_timestamps(args), [12.5, 18.0])
        self.assertTrue(args.no_vad)

    def test_incomplete_or_inverted_interval_is_rejected(self) -> None:
        parser = CLI.build_parser()
        cases = [
            ["transcribe", "input.mp4", "--start-seconds", "12.5"],
            [
                "transcribe",
                "input.mp4",
                "--start-seconds",
                "18",
                "--end-seconds",
                "12.5",
            ],
        ]
        for command in cases:
            with self.subTest(command=command):
                with self.assertRaises(CLI.SubtitleSkillError):
                    CLI.resolve_clip_timestamps(parser.parse_args(command))

    def test_repair_controls_must_be_used_as_a_group(self) -> None:
        parser = CLI.build_parser()
        cases = [
            ["transcribe", "input.mp4", "--no-vad"],
            [
                "transcribe",
                "input.mp4",
                "--language",
                "en",
                "--start-seconds",
                "12.5",
                "--end-seconds",
                "18",
            ],
            [
                "transcribe",
                "input.mp4",
                "--start-seconds",
                "12.5",
                "--end-seconds",
                "18",
                "--no-vad",
            ],
        ]
        for command in cases:
            with self.subTest(command=command):
                with self.assertRaises(CLI.SubtitleSkillError):
                    CLI.resolve_clip_timestamps(parser.parse_args(command))

    def test_repair_outputs_are_distinct_atomic_and_non_overwriting(self) -> None:
        class FakeASRData:
            def save(self, path: str, subtitle_format: str) -> None:
                target = Path(path)
                if target.suffix == ".srt":
                    target.write_text(
                        "1\n00:00:12,500 --> 00:00:13,000\nhello\n",
                        encoding="utf-8",
                    )
                else:
                    target.write_text("hello\n", encoding="utf-8")

        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            baseline = output_dir / "source.srt"
            baseline.write_text("immutable baseline", encoding="utf-8")
            base_name = CLI.targeted_repair_base_name("source", [12.5, 18.0])

            outputs = CLI.save_repair_outputs(
                FakeASRData(), output_dir, base_name
            )

            self.assertEqual(baseline.read_text(encoding="utf-8"), "immutable baseline")
            self.assertEqual(
                outputs["srt"].name,
                "source.repair-0000012500-0000018000.srt",
            )
            self.assertTrue(outputs["srt"].is_file())
            self.assertTrue(outputs["txt"].is_file())
            original_repair = outputs["srt"].read_bytes()
            with self.assertRaises(CLI.SubtitleSkillError):
                CLI.save_repair_outputs(FakeASRData(), output_dir, base_name)
            self.assertEqual(outputs["srt"].read_bytes(), original_repair)
            self.assertEqual(list(output_dir.glob(".*.tmp")), [])

    def test_repair_temp_cleanup_failure_does_not_leave_srt_only_result(self) -> None:
        class FakeASRData:
            def save(self, path: str, subtitle_format: str) -> None:
                target = Path(path)
                if target.suffix == ".srt":
                    target.write_text(
                        "1\n00:00:12,500 --> 00:00:13,000\nhello\n",
                        encoding="utf-8",
                    )
                else:
                    target.write_text("hello\n", encoding="utf-8")

        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            base_name = CLI.targeted_repair_base_name("source", [12.5, 18.0])
            original_unlink = CLI.unlink_with_retries

            def keep_locked_repair_temps(
                path: Path, *, suppress_errors: bool = False
            ) -> None:
                if path.name.startswith(".repair-"):
                    return
                original_unlink(path, suppress_errors=suppress_errors)

            with patch.object(
                CLI, "unlink_with_retries", side_effect=keep_locked_repair_temps
            ):
                outputs = CLI.save_repair_outputs(FakeASRData(), output_dir, base_name)

            self.assertTrue(outputs["srt"].exists())
            self.assertTrue(outputs["txt"].exists())
            self.assertEqual(len(list(output_dir.glob(".repair-*"))), 0)

    def test_repair_output_and_temp_names_are_component_safe(self) -> None:
        class FakeASRData:
            def save(self, path: str, subtitle_format: str) -> None:
                target = Path(path)
                if target.suffix == ".srt":
                    target.write_text(
                        "1\n00:00:12,500 --> 00:00:13,000\nhello\n",
                        encoding="utf-8",
                    )
                else:
                    target.write_text("hello\n", encoding="utf-8")

        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            base_name = CLI.targeted_repair_base_name("a" * 190, [12.5, 18.0])
            outputs = CLI.save_repair_outputs(FakeASRData(), output_dir, base_name)

            self.assertTrue(outputs["srt"].is_file())
            self.assertTrue(outputs["txt"].is_file())
            self.assertLessEqual(len(outputs["srt"].name.encode("utf-8")), 255)
            self.assertLessEqual(len(outputs["txt"].name.encode("utf-8")), 255)
            self.assertEqual(list(output_dir.glob(".repair-*")), [])

    def test_invalid_repair_output_is_not_promoted(self) -> None:
        class InvalidASRData:
            def save(self, path: str, subtitle_format: str) -> None:
                Path(path).write_text("invalid", encoding="utf-8")

        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            base_name = CLI.targeted_repair_base_name("source", [12.5, 18.0])
            expected = CLI.output_paths(output_dir, base_name)
            with self.assertRaises(CLI.SubtitleSkillError):
                CLI.save_repair_outputs(InvalidASRData(), output_dir, base_name)
            self.assertFalse(expected["srt"].exists())
            self.assertFalse(expected["txt"].exists())
            self.assertEqual(list(output_dir.glob(".*.tmp")), [])

    def test_main_outputs_are_pair_atomic_non_overwriting_and_archived_on_replace(self) -> None:
        data = ASRData([ASRDataSeg("Hello.", 0, 1000)])
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            paths = CLI.save_main_outputs(
                data,
                output_dir,
                "baseline",
                action="normalize",
            )
            original = {key: path.read_bytes() for key, path in paths.items()}
            with self.assertRaises(CLI.SubtitleSkillError) as raised:
                CLI.save_main_outputs(
                    data,
                    output_dir,
                    "baseline",
                    action="normalize",
                )
            self.assertEqual(raised.exception.error_type, "output_exists")
            self.assertEqual({key: path.read_bytes() for key, path in paths.items()}, original)

            replacement = ASRData([ASRDataSeg("Replacement.", 0, 1000)])
            replaced = CLI.save_main_outputs(
                replacement,
                output_dir,
                "baseline",
                action="normalize",
                replace_existing=True,
            )
            self.assertIn("Replacement.", paths["srt"].read_text(encoding="utf-8"))
            archived = list((output_dir / "_subtitle_work" / "archive").iterdir())
            self.assertEqual(len(archived), 2)
            self.assertTrue(replaced["archived_srt"].is_file())
            self.assertTrue(replaced["archived_txt"].is_file())

    def test_main_output_second_promotion_failure_rolls_back_pair(self) -> None:
        data = ASRData([ASRDataSeg("Hello.", 0, 1000)])
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            paths = CLI.output_paths(output_dir, "baseline")
            original_promote = CLI.promote_temp_file
            calls = 0

            def fail_second(source: Path, target: Path) -> None:
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("simulated TXT publish failure")
                original_promote(source, target)

            with patch.object(CLI, "promote_temp_file", side_effect=fail_second):
                with self.assertRaises(CLI.SubtitleSkillError) as raised:
                    CLI.save_main_outputs(
                        data,
                        output_dir,
                        "baseline",
                        action="normalize",
                    )
            self.assertEqual(raised.exception.error_type, "publish_failure")
            self.assertFalse(paths["srt"].exists())
            self.assertFalse(paths["txt"].exists())

    def test_main_output_failed_replacement_restores_archived_pair(self) -> None:
        original_data = ASRData([ASRDataSeg("Original.", 0, 1000)])
        replacement = ASRData([ASRDataSeg("Replacement.", 0, 1000)])
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            paths = CLI.save_main_outputs(
                original_data,
                output_dir,
                "baseline",
                action="normalize",
            )
            original = {key: path.read_bytes() for key, path in paths.items()}
            original_promote = CLI.promote_temp_file
            calls = 0

            def fail_second(source: Path, target: Path) -> None:
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("simulated replacement failure")
                original_promote(source, target)

            with patch.object(CLI, "promote_temp_file", side_effect=fail_second):
                with self.assertRaises(CLI.SubtitleSkillError) as raised:
                    CLI.save_main_outputs(
                        replacement,
                        output_dir,
                        "baseline",
                        action="normalize",
                        replace_existing=True,
                    )
            self.assertEqual(raised.exception.error_type, "publish_failure")
            self.assertEqual({key: path.read_bytes() for key, path in paths.items()}, original)

    def test_pair_validation_rejects_srt_txt_from_different_serializations(self) -> None:
        class MismatchedData:
            def save(self, path: str, subtitle_format: str) -> None:
                target = Path(path)
                target.write_text(
                    (
                        "1\n00:00:00,000 --> 00:00:01,000\nHello.\n"
                        if target.suffix == ".srt"
                        else "stale text"
                    ),
                    encoding="utf-8",
                )

            def to_srt(self, subtitle_format: str) -> str:
                return "1\n00:00:00,000 --> 00:00:01,000\nHello.\n"

            def to_txt(self, subtitle_format: str) -> str:
                return "Hello."

        with tempfile.TemporaryDirectory() as temp_dir:
            paths = CLI.output_paths(Path(temp_dir), "baseline")
            with self.assertRaises(CLI.SubtitleSkillError) as raised:
                CLI.save_main_outputs(
                    MismatchedData(),
                    Path(temp_dir),
                    "baseline",
                    action="normalize",
                )
            self.assertEqual(raised.exception.error_type, "output_pair_mismatch")
            self.assertFalse(paths["srt"].exists())
            self.assertFalse(paths["txt"].exists())

    def test_targeted_repair_second_promotion_and_locked_rollback_never_leave_srt(self) -> None:
        data = ASRData([ASRDataSeg("Repair.", 0, 1000)])
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = CLI.output_paths(root, "repair")
            original_promote = CLI.promote_temp_file
            calls = 0

            def fail_second(source: Path, target: Path) -> None:
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("simulated second promotion failure")
                original_promote(source, target)

            def locked_unlink(path: Path, *, suppress_errors: bool = False) -> None:
                if path == paths["txt"]:
                    raise PermissionError("simulated persistent lock")
                path.unlink(missing_ok=True)

            with (
                patch.object(CLI, "promote_temp_file", side_effect=fail_second),
                patch.object(CLI, "unlink_with_retries", side_effect=locked_unlink),
            ):
                with self.assertRaises(CLI.SubtitleSkillError) as raised:
                    CLI.save_repair_outputs(data, root, "repair")
            self.assertEqual(raised.exception.error_type, "rollback_failure")
            self.assertFalse(paths["srt"].exists())

    def test_normalize_work_failure_happens_before_final_pair(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source.srt"
            source.write_text(
                "1\n00:00:00,000 --> 00:00:01,000\nHello.\n",
                encoding="utf-8",
            )
            output_dir = root / "out"
            args = CLI.build_parser().parse_args(
                ["normalize", str(source), "--output-dir", str(output_dir)]
            )
            with patch.object(CLI, "copy_file_atomic", side_effect=OSError("blocked work copy")):
                with self.assertRaises(OSError):
                    CLI.run_normalize(args)
            self.assertEqual(list(output_dir.glob("*.srt")), [])
            self.assertEqual(list(output_dir.glob("*.txt")), [])

    def test_existing_outputs_fail_before_any_llm_call(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source.srt"
            source.write_text(
                "1\n00:00:00,000 --> 00:00:01,000\nHello.\n",
                encoding="utf-8",
            )
            split_input = root / "source.json"
            split_input.write_text("{}", encoding="utf-8")
            data = ASRData([ASRDataSeg("Hello.", 0, 1000)])
            cases = (
                (
                    "optimize",
                    CLI.build_parser().parse_args(
                        [
                            "optimize",
                            str(source),
                            "--output-dir",
                            str(root / "optimize"),
                            "--api-key",
                            "test",
                        ]
                    ),
                    root / "optimize" / "source_optimized.srt",
                    "optimize_subtitle",
                    None,
                ),
                (
                    "translate",
                    CLI.build_parser().parse_args(
                        [
                            "translate",
                            str(source),
                            "--output-dir",
                            str(root / "translate"),
                            "--target-language",
                            "zh-Hans",
                            "--api-key",
                            "test",
                        ]
                    ),
                    root / "translate" / "source_zh-Hans.srt",
                    "translate_subtitle",
                    None,
                ),
                (
                    "split",
                    CLI.build_parser().parse_args(
                        [
                            "split",
                            str(split_input),
                            "--output-dir",
                            str(root / "split"),
                            "--api-key",
                            "test",
                        ]
                    ),
                    root / "split" / "source.srt",
                    "split_subtitle",
                    data,
                ),
            )
            for action, args, existing, llm_name, parsed_data in cases:
                with self.subTest(action=action):
                    existing.parent.mkdir(parents=True, exist_ok=True)
                    existing.write_text("preserve", encoding="utf-8")
                    llm = Mock(return_value=data)
                    patches = [patch.object(CLI, llm_name, llm)]
                    if parsed_data is not None:
                        patches.append(
                            patch.object(
                                CLI.ASRData,
                                "from_whisper_json",
                                return_value=parsed_data,
                            )
                        )
                    with patches[0]:
                        if len(patches) == 2:
                            with patches[1]:
                                with self.assertRaises(CLI.SubtitleSkillError):
                                    args.func(args)
                        else:
                            with self.assertRaises(CLI.SubtitleSkillError):
                                args.func(args)
                    llm.assert_not_called()

    def test_required_source_language_rejects_non_english_asr_detection(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            media = root / "source.wav"
            media.touch()
            args = CLI.build_parser().parse_args(
                [
                    "transcribe",
                    str(media),
                    "--require-language",
                    "en",
                    "--output-dir",
                    str(root / "out"),
                ]
            )

            def fake_process(*_args: object, **kwargs: object) -> ASRData:
                kwargs["asr_metadata_out"].update(
                    {"language": "es", "language_probability": 0.99}
                )
                return ASRData([ASRDataSeg("Hola.", 0, 1000)])

            with patch.object(CLI, "process_media", side_effect=fake_process):
                with self.assertRaises(CLI.SubtitleSkillError) as raised:
                    CLI.run_transcribe(args)
            self.assertEqual(raised.exception.error_type, "source_language_mismatch")
            self.assertEqual(list((root / "out").glob("*.srt")), [])

    def test_conflicting_fixed_and_required_languages_fail_before_asr(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            media = Path(temp_dir) / "source.wav"
            media.touch()
            args = CLI.build_parser().parse_args(
                [
                    "transcribe",
                    str(media),
                    "--language",
                    "es",
                    "--require-language",
                    "en",
                ]
            )
            with patch.object(CLI, "process_media") as process_media:
                with self.assertRaises(CLI.SubtitleSkillError) as raised:
                    CLI.run_transcribe(args)
            process_media.assert_not_called()
            self.assertEqual(
                raised.exception.error_type,
                "conflicting_language_controls",
            )

    def test_required_english_manual_track_is_recorded_in_handoff_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            manual = root / "manual.en.srt"
            manual.write_text(
                "1\n00:00:00,000 --> 00:00:01,000\nHello.\n",
                encoding="utf-8",
            )
            video_metadata = {
                "id": "abc",
                "title": "Example",
                "channel": "Channel",
                "description": "",
                "subtitles": {"en": [{"ext": "srt"}], "es": [{"ext": "srt"}]},
            }
            args = CLI.build_parser().parse_args(
                [
                    "transcribe",
                    "https://www.youtube.com/watch?v=abc",
                    "--require-language",
                    "en",
                    "--output-dir",
                    str(root / "out"),
                ]
            )
            with (
                patch.object(CLI, "fetch_video_metadata", return_value=video_metadata),
                patch.object(
                    CLI,
                    "download_manual_subtitles",
                    return_value=(manual, video_metadata, "en"),
                ),
            ):
                result = CLI.run_transcribe(args)
            metadata = json.loads(Path(result["metadata"]).read_text(encoding="utf-8"))
            self.assertEqual(metadata["source_language"], "en")
            self.assertEqual(metadata["required_source_language"], "en")
            self.assertEqual(metadata["source_language_origin"], "manual_subtitle_track")
            self.assertTrue(metadata["used_manual_subtitles"])

    def test_manual_metadata_failure_does_not_publish_final_pair(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output_dir = root / "out"
            manual = root / "manual.en.srt"
            manual.write_text(
                "1\n00:00:00,000 --> 00:00:01,000\nHello.\n",
                encoding="utf-8",
            )
            video_metadata = {
                "id": "abc",
                "title": "Example",
                "channel": "Channel",
                "description": "",
                "subtitles": {"en": [{"ext": "srt"}]},
            }
            args = CLI.build_parser().parse_args(
                [
                    "transcribe",
                    "https://www.youtube.com/watch?v=abc",
                    "--require-language",
                    "en",
                    "--output-dir",
                    str(output_dir),
                ]
            )
            original_write_json = CLI.write_json_atomic

            def fail_metadata(path: Path, payload: dict[str, object]) -> None:
                if path.name.endswith(".metadata.json"):
                    raise OSError("simulated metadata write failure")
                original_write_json(path, payload)

            with (
                patch.object(CLI, "fetch_video_metadata", return_value=video_metadata),
                patch.object(
                    CLI,
                    "download_manual_subtitles",
                    return_value=(manual, video_metadata, "en"),
                ),
                patch.object(CLI, "write_json_atomic", side_effect=fail_metadata),
            ):
                with self.assertRaises(OSError):
                    CLI.run_transcribe(args)
            self.assertEqual(list(output_dir.glob("*.srt")), [])
            self.assertEqual(list(output_dir.glob("*.txt")), [])

    def test_split_and_qc_limits_must_be_positive(self) -> None:
        parser = CLI.build_parser()
        cases = [
            ["transcribe", "input.mp4", "--split-max-chars-cjk", "0"],
            ["transcribe", "input.mp4", "--split-max-words-en", "0"],
            ["transcribe", "input.mp4", "--split-max-chars-en", "0"],
            ["transcribe", "input.mp4", "--split-chunk-word-limit", "0"],
            ["transcribe", "input.mp4", "--split-max-retries", "0"],
            ["split", "raw.json", "--split-max-words-en", "-1"],
            ["qc", "input.srt", "--max-words-en", "0"],
            ["qc", "input.srt", "--max-display-chars-en", "0"],
        ]
        for command in cases:
            with self.subTest(command=command):
                with self.assertRaises(SystemExit) as raised:
                    parser.parse_args(command)
                self.assertEqual(raised.exception.code, 1)

    def test_non_positive_limit_returns_structured_argument_error(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                str(CLI_PATH),
                "qc",
                "unused.srt",
                "--max-words-en",
                "0",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["error_type"], "invalid_arguments")
        self.assertEqual(payload["step"], "parse_arguments")

    def test_reverse_whisper_json_returns_structured_invalid_srt(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            raw_json = root / "reverse.json"
            output_dir = root / "output"
            raw_json.write_text(
                json.dumps(
                    {
                        "segments": [
                            {
                                "text": "Later.",
                                "start": 10.0,
                                "end": 11.0,
                                "words": [
                                    {
                                        "word": "Later.",
                                        "start": 10.0,
                                        "end": 11.0,
                                    }
                                ],
                            },
                            {
                                "text": "Earlier.",
                                "start": 0.0,
                                "end": 1.0,
                                "words": [
                                    {
                                        "word": "Earlier.",
                                        "start": 0.0,
                                        "end": 1.0,
                                    }
                                ],
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(CLI_PATH),
                    "split",
                    str(raw_json),
                    "--output-dir",
                    str(output_dir),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
            )

            self.assertEqual(result.returncode, 1)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["error_type"], "invalid_srt")
            self.assertEqual(payload["step"], "validate_output")
            self.assertFalse(output_dir.exists())

    def test_process_media_propagates_clip_and_vad_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            media = root / "source.wav"
            media.touch()
            expected = object()
            fake_asr = Mock()
            fake_asr.run.return_value = expected

            with patch.object(core, "create_asr", return_value=fake_asr) as create_asr:
                result = core.process_media(
                    str(media),
                    str(root / "work"),
                    language="en",
                    vad_filter=False,
                    clip_timestamps=[12.5, 18.0],
                )

            self.assertIs(result, expected)
            config = create_asr.call_args.args[1]
            self.assertFalse(config.vad_filter)
            self.assertEqual(config.clip_timestamps, [12.5, 18.0])

    def test_youtube_semantic_split_uses_asr_instead_of_manual_subtitles(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            args = CLI.build_parser().parse_args(
                [
                    "transcribe",
                    "https://www.youtube.com/watch?v=abc",
                    "--semantic-split",
                    "--api-key",
                    "test-key",
                    "--output-dir",
                    temp_dir,
                ]
            )
            split_result = ASRData(
                [ASRDataSeg("Complete sentence.", 0, 1000)]
            )
            metadata = {
                "id": "abc",
                "title": "Example",
                "channel": "Channel",
                "description": "",
                "subtitles": {"en": [{"ext": "srt"}]},
            }

            with (
                patch.object(CLI, "fetch_video_metadata", return_value=metadata),
                patch.object(CLI, "download_manual_subtitles") as download_manual,
                patch.object(CLI, "process_media", return_value=split_result) as process_media,
            ):
                result = CLI.run_transcribe(args)

            download_manual.assert_not_called()
            self.assertTrue(process_media.call_args.kwargs["split_enabled"])
            self.assertEqual(result["status"], "ok")
            seams_path = Path(result["seam_times_path"])
            self.assertTrue(seams_path.is_file())
            self.assertEqual(
                json.loads(seams_path.read_text(encoding="utf-8")),
                {"seam_times_ms": [], "seam_repair_failures": []},
            )

    def test_semantic_split_zero_duration_is_structured_and_leaves_no_final_srt(self) -> None:
        cases = {
            "zero-duration": ASRData([ASRDataSeg("No duration.", 1000, 1000)]),
            "overlap": ASRData(
                [
                    ASRDataSeg("First cue.", 0, 2000),
                    ASRDataSeg("Second cue.", 1500, 3000),
                ]
            ),
        }
        for name, split_result in cases.items():
            with self.subTest(name=name):
                with tempfile.TemporaryDirectory() as temp_dir:
                    root = Path(temp_dir)
                    media = root / "source.wav"
                    media.touch()
                    args = CLI.build_parser().parse_args(
                        [
                            "transcribe",
                            str(media),
                            "--semantic-split",
                            "--api-key",
                            "test-key",
                            "--output-dir",
                            str(root / "out"),
                        ]
                    )
                    with patch.object(CLI, "process_media", return_value=split_result):
                        with self.assertRaises(CLI.SubtitleSkillError) as raised:
                            CLI.run_transcribe(args)
                    self.assertEqual(raised.exception.error_type, "invalid_srt")
                    self.assertEqual(raised.exception.step, "validate_output")
                    self.assertEqual(list((root / "out").glob("*.srt")), [])
                    self.assertEqual(
                        list((root / "out").rglob("*.semantic-orphan-qc.json")),
                        [],
                    )
                    self.assertEqual(
                        list((root / "out").rglob("*.chunk-seams.json")),
                        [],
                    )

    def test_semantic_split_blank_line_cue_does_not_write_final_srt(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            media = root / "source.wav"
            media.touch()
            args = CLI.build_parser().parse_args(
                [
                    "transcribe",
                    str(media),
                    "--semantic-split",
                    "--api-key",
                    "test-key",
                    "--output-dir",
                    str(root / "out"),
                ]
            )
            split_result = ASRData([ASRDataSeg("Hello\n\nWorld", 0, 1000)])
            with patch.object(CLI, "process_media", return_value=split_result):
                with self.assertRaises(CLI.SubtitleSkillError) as raised:
                    CLI.run_transcribe(args)
            self.assertEqual(raised.exception.error_type, "invalid_srt")
            self.assertEqual(raised.exception.action, "transcribe")
            self.assertEqual(raised.exception.step, "validate_output")
            self.assertEqual(list((root / "out").glob("*.srt")), [])
            self.assertEqual(list((root / "out").rglob("*.semantic-orphan-qc.json")), [])
            self.assertEqual(list((root / "out").rglob("*.chunk-seams.json")), [])

    def test_normalize_rejects_zero_duration_and_malformed_later_cue(self) -> None:
        cases = (
            "1\n00:00:00,000 --> 00:00:00,000\nZero\n",
            (
                "1\n00:00:00,000 --> 00:00:01,000\nFirst\n\n"
                "2\nNOT A TIMESTAMP\nSecond\n"
            ),
        )
        for srt_text in cases:
            with self.subTest(srt_text=srt_text):
                with tempfile.TemporaryDirectory() as temp_dir:
                    root = Path(temp_dir)
                    source = root / "source.srt"
                    source.write_text(srt_text, encoding="utf-8")
                    args = CLI.build_parser().parse_args(
                        ["normalize", str(source), "--output-dir", str(root / "out")]
                    )
                    with self.assertRaises(CLI.SubtitleSkillError) as raised:
                        CLI.run_normalize(args)
                    self.assertEqual(raised.exception.error_type, "invalid_srt")
                    self.assertEqual(list((root / "out").glob("*.srt")), [])

    def test_replace_existing_rejects_directory_target(self) -> None:
        data = ASRData([ASRDataSeg("Hello.", 0, 1000)])
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "baseline.srt").mkdir()
            (root / "baseline.srt" / "important.txt").write_text(
                "preserve", encoding="utf-8"
            )
            with self.assertRaises(CLI.SubtitleSkillError) as raised:
                CLI.save_main_outputs(
                    data,
                    root,
                    "baseline",
                    action="normalize",
                    replace_existing=True,
                )
            self.assertEqual(raised.exception.error_type, "invalid_output_target")
            self.assertTrue((root / "baseline.srt" / "important.txt").is_file())

    def test_pair_lock_rejects_overlapping_publisher(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = CLI.output_paths(Path(temp_dir), "same")
            with CLI.output_pair_lock(paths, "normalize"):
                with self.assertRaises(CLI.SubtitleSkillError) as raised:
                    with CLI.output_pair_lock(paths, "normalize"):
                        pass
            self.assertEqual(raised.exception.error_type, "output_locked")

    def test_losing_normalize_publisher_leaves_no_work_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source.srt"
            source.write_text(
                "1\n00:00:00,000 --> 00:00:01,000\nHello.\n",
                encoding="utf-8",
            )
            output_dir = root / "out"
            output_dir.mkdir()
            paths = CLI.output_paths(output_dir, "source")
            args = CLI.build_parser().parse_args(
                ["normalize", str(source), "--output-dir", str(output_dir)]
            )
            with CLI.output_pair_lock(paths, "normalize"):
                with self.assertRaises(CLI.SubtitleSkillError) as raised:
                    CLI.run_normalize(args)
            self.assertEqual(raised.exception.error_type, "output_locked")
            work_dir = output_dir / "_subtitle_work"
            self.assertEqual(list(work_dir.glob("*.source.srt")), [])
            self.assertEqual(list(work_dir.glob("*.normalize.json")), [])
            self.assertEqual(list(output_dir.glob("source.*")), [])

    def test_normalize_has_no_fallible_validation_after_srt_commit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source.srt"
            source.write_text(
                "1\n00:00:00,000 --> 00:00:01,000\nHello.\n",
                encoding="utf-8",
            )
            output_dir = root / "out"
            args = CLI.build_parser().parse_args(
                ["normalize", str(source), "--output-dir", str(output_dir)]
            )
            original_validate = CLI.validate_main_outputs
            calls = 0

            def fail_second_validation(*call_args: object, **call_kwargs: object) -> None:
                nonlocal calls
                calls += 1
                if calls > 1:
                    raise OSError("injected post-commit validation failure")
                original_validate(*call_args, **call_kwargs)

            with patch.object(
                CLI, "validate_main_outputs", side_effect=fail_second_validation
            ):
                result = CLI.run_normalize(args)
            self.assertTrue(result["ok"])
            self.assertEqual(calls, 1)
            self.assertTrue((output_dir / "source.srt").is_file())
            self.assertTrue((output_dir / "source.txt").is_file())

    def test_publish_failure_rolls_back_new_work_and_preserves_existing_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source.srt"
            source.write_text(
                "1\n00:00:00,000 --> 00:00:01,000\nHello.\n",
                encoding="utf-8",
            )
            output_dir = root / "out"
            work_dir = CLI.get_work_dir(output_dir)
            asr_data = CLI.require_strict_srt_input(source, "normalize")
            work_json = CLI.work_json_output_path(
                asr_data, work_dir, "source", "normalize"
            )
            work_json.write_bytes(b"preexisting-evidence")
            args = CLI.build_parser().parse_args(
                ["normalize", str(source), "--output-dir", str(output_dir)]
            )
            original_promote = CLI.promote_temp_file
            calls = 0

            def fail_srt_promotion(source_path: Path, target_path: Path) -> None:
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("injected SRT promotion failure")
                original_promote(source_path, target_path)

            with patch.object(
                CLI, "promote_temp_file", side_effect=fail_srt_promotion
            ):
                with self.assertRaises(CLI.SubtitleSkillError) as raised:
                    CLI.run_normalize(args)
            self.assertEqual(raised.exception.error_type, "publish_failure")
            self.assertFalse((output_dir / "source.srt").exists())
            self.assertFalse((output_dir / "source.txt").exists())
            self.assertEqual(work_json.read_bytes(), b"preexisting-evidence")
            self.assertEqual(list(work_dir.glob("*.source.srt")), [])

    def test_low_confidence_required_language_does_not_publish(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            media = root / "source.wav"
            media.touch()
            args = CLI.build_parser().parse_args(
                [
                    "transcribe",
                    str(media),
                    "--require-language",
                    "en",
                    "--output-dir",
                    str(root / "out"),
                ]
            )

            def fake_process(*_args: object, **kwargs: object) -> ASRData:
                kwargs["asr_metadata_out"].update(
                    {"language": "en", "language_probability": 0.01}
                )
                return ASRData([ASRDataSeg("Hello.", 0, 1000)])

            with patch.object(CLI, "process_media", side_effect=fake_process):
                with self.assertRaises(CLI.SubtitleSkillError) as raised:
                    CLI.run_transcribe(args)
            self.assertEqual(raised.exception.error_type, "source_language_unreliable")
            self.assertEqual(list((root / "out").glob("*.srt")), [])

    def test_atomic_transcribe_metadata_validates_exact_emitted_srt_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            media = root / "source.wav"
            media.touch()
            args = CLI.build_parser().parse_args(
                [
                    "transcribe",
                    str(media),
                    "--require-language",
                    "en",
                    "--output-dir",
                    str(root / "out"),
                ]
            )

            def fake_process(*_args: object, **kwargs: object) -> ASRData:
                kwargs["asr_metadata_out"].update(
                    {"language": "en", "language_probability": 1.0}
                )
                return ASRData([ASRDataSeg("Hello.", 0, 1000)])

            with patch.object(CLI, "process_media", side_effect=fake_process):
                result = CLI.run_transcribe(args)
            source = Path(result["outputs"]["srt"])
            metadata = Path(result["metadata"])
            metadata_payload = json.loads(metadata.read_text(encoding="utf-8"))
            self.assertEqual(metadata_payload["source_srt_path"], str(source))
            self.assertEqual(
                metadata_payload["source_srt_sha256"],
                CLI.sha256_bytes(source.read_bytes()),
            )
            self.assertNotIn(b"\r\n", source.read_bytes())

            bilingual = root / "bilingual.srt"
            bilingual.write_text(
                "1\n00:00:00,000 --> 00:00:01,000\n你好。\nHello.\n",
                encoding="utf-8",
                newline="\n",
            )
            validated = subprocess.run(
                [
                    sys.executable,
                    str(VALIDATE_SCRIPT),
                    str(bilingual),
                    "--source-srt",
                    str(source),
                    "--source-metadata",
                    str(metadata),
                    "--duration",
                    "1",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self.assertEqual(validated.returncode, 0, validated.stderr or validated.stdout)

    def test_faster_whisper_receives_clip_and_no_vad(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            media = root / "source.wav"
            media.touch()
            model = Mock()
            word = SimpleNamespace(word=" hello", start=12.5, end=13.0)
            segment = SimpleNamespace(
                id=0,
                start=12.5,
                end=13.0,
                text="hello",
                words=[word],
            )
            info = SimpleNamespace(
                language="en",
                language_probability=1.0,
                duration=20.0,
            )
            model.transcribe.return_value = (iter([segment]), info)
            config = TranscribeConfig(
                output_dir=str(root / "work"),
                language="en",
                vad_filter=False,
                clip_timestamps=[12.5, 18.0],
            )
            asr = FasterWhisperASR(str(media), config)
            fake_module = types.ModuleType("faster_whisper")
            fake_module.WhisperModel = object

            with (
                patch.dict(sys.modules, {"faster_whisper": fake_module}),
                patch.object(
                    asr,
                    "_load_model_with_fallback",
                    return_value=(model, "cpu", "int8"),
                ),
            ):
                result = asr.run()

            self.assertTrue(result.has_word_timestamps())
            kwargs = model.transcribe.call_args.kwargs
            self.assertFalse(kwargs["vad_filter"])
            self.assertEqual(kwargs["clip_timestamps"], [12.5, 18.0])


if __name__ == "__main__":
    unittest.main()
