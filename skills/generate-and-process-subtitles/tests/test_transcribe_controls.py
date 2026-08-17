from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


SKILL_ROOT = Path(__file__).resolve().parents[1]
CLI_PATH = SKILL_ROOT / "scripts" / "generate_and_process_subtitles.py"
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
