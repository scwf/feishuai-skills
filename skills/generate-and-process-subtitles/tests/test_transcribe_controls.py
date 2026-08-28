from __future__ import annotations

import importlib.util
import hashlib
import json
import os
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

from subtitle_tools import ASRData, ASRDataSeg, ASRWord, core  # noqa: E402
from subtitle_tools import publishing as PUBLISHING  # noqa: E402
from subtitle_tools import transcribe_command as TRANSCRIBE  # noqa: E402
from subtitle_tools.asr.faster_whisper import (  # noqa: E402
    FasterWhisperASR,
    TimestampRepairLimitError,
)
from subtitle_tools.config import TranscribeConfig  # noqa: E402


class TranscribeControlTests(unittest.TestCase):
    def test_parser_exposes_packed_timestamp_repair_limits(self) -> None:
        args = CLI.build_parser().parse_args(
            [
                "transcribe",
                "input.mp4",
                "--max-packed-word-repairs-per-10k",
                "25",
                "--max-packed-cluster-size",
                "3",
            ]
        )

        self.assertEqual(args.max_packed_word_repairs_per_10k, 25)
        self.assertEqual(args.max_packed_cluster_size, 3)

    def test_raw_asr_evidence_is_content_addressed_and_hash_bound(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            media = root / "source.wav"
            media.touch()

            def run_fixture(text: str) -> tuple[Path, str]:
                model = Mock()
                segment = SimpleNamespace(
                    id=0,
                    start=0.0,
                    end=0.5,
                    text=text,
                    words=[SimpleNamespace(word=f" {text}", start=0.0, end=0.5)],
                )
                info = SimpleNamespace(
                    language="en", language_probability=1.0, duration=0.5
                )
                model.transcribe.return_value = (iter([segment]), info)
                asr = FasterWhisperASR(
                    str(media),
                    TranscribeConfig(output_dir=str(root / "work"), language="en"),
                )
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
                    asr.run()
                return (
                    Path(asr.result_metadata["raw_asr_json"]),
                    asr.result_metadata["raw_asr_sha256"],
                )

            first_path, first_hash = run_fixture("hello")
            first_bytes = first_path.read_bytes()
            second_path, second_hash = run_fixture("world")

            self.assertNotEqual(first_path, second_path)
            self.assertEqual(first_path.read_bytes(), first_bytes)
            self.assertEqual(hashlib.sha256(first_bytes).hexdigest(), first_hash)
            self.assertEqual(
                hashlib.sha256(second_path.read_bytes()).hexdigest(), second_hash
            )
            self.assertIn(first_hash[:12], first_path.name)
            self.assertIn(second_hash[:12], second_path.name)

    def test_run_asr_wraps_timestamp_repair_block_with_raw_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            media = root / "source.wav"
            media.touch()
            raw_path = root / "source.asr.json"
            raw_path.write_text("{}", encoding="utf-8")
            args = CLI.build_parser().parse_args(["transcribe", str(media)])
            repair_summary = {
                "status": "blocked",
                "blocked_reasons": ["fixture limit"],
            }

            with patch.object(
                TRANSCRIBE,
                "process_media",
                side_effect=TimestampRepairLimitError(
                    "packed zero-duration ASR repair was blocked: fixture limit",
                    raw_asr_path=raw_path,
                    raw_asr_sha256="0" * 64,
                    repair_summary=repair_summary,
                ),
            ):
                with self.assertRaises(CLI.SubtitleSkillError) as raised:
                    TRANSCRIBE.run_asr(
                        args,
                        work_dir=root,
                        effective_vad_filter=True,
                        clip_timestamps=None,
                    )

            self.assertEqual(raised.exception.error_type, "timestamp_repair_blocked")
            self.assertEqual(raised.exception.details["raw_asr_json"], str(raw_path))
            self.assertEqual(raised.exception.details["raw_asr_sha256"], "0" * 64)
            self.assertEqual(
                raised.exception.details["timestamp_repair_summary"], repair_summary
            )

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
            original_unlink = PUBLISHING.unlink_with_retries

            def keep_locked_repair_temps(
                path: Path, *, suppress_errors: bool = False
            ) -> None:
                if path.name.startswith(".repair-"):
                    return
                original_unlink(path, suppress_errors=suppress_errors)

            with patch.object(
                PUBLISHING, "unlink_with_retries", side_effect=keep_locked_repair_temps
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
            original_promote = PUBLISHING.promote_temp_file
            calls = 0

            def fail_second(source: Path, target: Path) -> None:
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("simulated TXT publish failure")
                original_promote(source, target)

            with patch.object(PUBLISHING, "promote_temp_file", side_effect=fail_second):
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
            original_promote = PUBLISHING.promote_temp_file
            calls = 0

            def fail_second(source: Path, target: Path) -> None:
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("simulated replacement failure")
                original_promote(source, target)

            with patch.object(PUBLISHING, "promote_temp_file", side_effect=fail_second):
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

    def test_main_output_missing_archive_is_reported_as_rollback_failure(self) -> None:
        original_data = ASRData([ASRDataSeg("Original.", 0, 1000)])
        replacement = ASRData([ASRDataSeg("Replacement.", 0, 1000)])
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            paths = CLI.save_main_outputs(
                original_data, output_dir, "baseline", action="normalize"
            )
            original_promote = PUBLISHING.promote_temp_file
            calls = 0

            def lose_archive_then_fail(source: Path, target: Path) -> None:
                nonlocal calls
                calls += 1
                if calls == 2:
                    archive_dir = output_dir / "_subtitle_work" / "archive"
                    next(archive_dir.glob("*.srt")).unlink()
                    raise OSError("simulated replacement failure")
                original_promote(source, target)

            with patch.object(
                PUBLISHING, "promote_temp_file", side_effect=lose_archive_then_fail
            ):
                with self.assertRaises(CLI.SubtitleSkillError) as raised:
                    CLI.save_main_outputs(
                        replacement,
                        output_dir,
                        "baseline",
                        action="normalize",
                        replace_existing=True,
                    )
            self.assertEqual(raised.exception.error_type, "rollback_failure")
            self.assertIn("expected archive is missing", str(raised.exception))
            archive_evidence = raised.exception.details["archived_outputs"]
            self.assertIsNone(archive_evidence["srt"])
            self.assertTrue(Path(archive_evidence["txt"]).is_file())
            self.assertEqual(raised.exception.details["unavailable_archives"], ["srt"])
            self.assertFalse(paths["srt"].exists())

    def test_main_output_restore_error_is_reported_as_rollback_failure(self) -> None:
        original_data = ASRData([ASRDataSeg("Original.", 0, 1000)])
        replacement = ASRData([ASRDataSeg("Replacement.", 0, 1000)])
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            CLI.save_main_outputs(
                original_data, output_dir, "baseline", action="normalize"
            )
            original_promote = PUBLISHING.promote_temp_file
            calls = 0

            def fail_second(source: Path, target: Path) -> None:
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("simulated replacement failure")
                original_promote(source, target)

            with (
                patch.object(PUBLISHING, "promote_temp_file", side_effect=fail_second),
                patch.object(
                    PUBLISHING,
                    "restore_archived_pair_member",
                    side_effect=OSError("simulated restore failure"),
                ),
            ):
                with self.assertRaises(CLI.SubtitleSkillError) as raised:
                    CLI.save_main_outputs(
                        replacement,
                        output_dir,
                        "baseline",
                        action="normalize",
                        replace_existing=True,
                    )
            self.assertEqual(raised.exception.error_type, "rollback_failure")
            self.assertIn("simulated restore failure", str(raised.exception))
            archived = raised.exception.details["archived_outputs"]
            self.assertTrue(all(Path(path).exists() for path in archived.values()))

    def test_archive_digest_capture_failure_preserves_canonical_pair(self) -> None:
        original_data = ASRData([ASRDataSeg("Original.", 0, 1000)])
        replacement = ASRData([ASRDataSeg("Replacement.", 0, 1000)])
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            paths = CLI.save_main_outputs(
                original_data, output_dir, "baseline", action="normalize"
            )
            original = {key: path.read_bytes() for key, path in paths.items()}
            original_read_bytes = Path.read_bytes

            def fail_canonical_srt_read(path: Path) -> bytes:
                if path == paths["srt"]:
                    raise OSError("simulated archive digest read failure")
                return original_read_bytes(path)

            with patch.object(Path, "read_bytes", new=fail_canonical_srt_read):
                with self.assertRaises(CLI.SubtitleSkillError) as raised:
                    CLI.save_main_outputs(
                        replacement,
                        output_dir,
                        "baseline",
                        action="normalize",
                        replace_existing=True,
                    )
            self.assertEqual(raised.exception.error_type, "publish_failure")
            self.assertEqual(
                {key: original_read_bytes(path) for key, path in paths.items()}, original
            )

    def test_tampered_archive_is_preserved_and_reported(self) -> None:
        original_data = ASRData([ASRDataSeg("Original.", 0, 1000)])
        replacement = ASRData([ASRDataSeg("Replacement.", 0, 1000)])
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            CLI.save_main_outputs(
                original_data, output_dir, "baseline", action="normalize"
            )
            original_promote = PUBLISHING.promote_temp_file
            calls = 0

            def tamper_archive_then_fail(source: Path, target: Path) -> None:
                nonlocal calls
                calls += 1
                if calls == 2:
                    next((output_dir / "_subtitle_work" / "archive").glob("*.srt")).write_bytes(
                        b"tampered"
                    )
                    raise OSError("simulated replacement failure")
                original_promote(source, target)

            with patch.object(
                PUBLISHING, "promote_temp_file", side_effect=tamper_archive_then_fail
            ):
                with self.assertRaises(CLI.SubtitleSkillError) as raised:
                    CLI.save_main_outputs(
                        replacement,
                        output_dir,
                        "baseline",
                        action="normalize",
                        replace_existing=True,
                    )
            self.assertEqual(raised.exception.error_type, "rollback_failure")
            archive_path = Path(raised.exception.details["archived_outputs"]["srt"])
            self.assertTrue(archive_path.is_file())
            self.assertEqual(archive_path.read_bytes(), b"tampered")

    def test_youtube_context_is_content_addressed_and_metadata_bound(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            work_dir = Path(temp_dir) / "_subtitle_work"
            work_dir.mkdir()
            first_source = {
                "id": "video-1",
                "title": "Same title",
                "channel": "Channel",
                "description": "First description.",
            }
            second_source = {
                "id": "video-2",
                "title": "Same title",
                "channel": "Channel",
                "description": "Second description.",
            }
            args = SimpleNamespace(
                input="https://youtu.be/example",
                model="large-v2",
                device="auto",
                compute_type="auto",
                no_vad=False,
                semantic_split=False,
            )

            first_context = TRANSCRIBE.write_youtube_context(work_dir, first_source)
            assert first_context is not None
            first_bytes = first_context.read_bytes()
            first_metadata = TRANSCRIBE.initial_transcribe_metadata(
                args,
                effective_vad_filter=True,
                clip_timestamps=None,
                video_metadata=first_source,
                context_path=first_context,
            )
            source_srt_hash = "a" * 64
            first_metadata_path = PUBLISHING.metadata_output_path(
                work_dir,
                "Same title",
                source_srt_hash,
                PUBLISHING.sha256_bytes(PUBLISHING.json_payload_bytes(first_metadata)),
            )
            PUBLISHING.write_immutable_json_atomic(
                first_metadata_path, first_metadata, action="transcribe"
            )

            second_context = TRANSCRIBE.write_youtube_context(work_dir, second_source)
            assert second_context is not None
            second_metadata = TRANSCRIBE.initial_transcribe_metadata(
                args,
                effective_vad_filter=True,
                clip_timestamps=None,
                video_metadata=second_source,
                context_path=second_context,
            )
            second_metadata_path = PUBLISHING.metadata_output_path(
                work_dir,
                "Same title",
                source_srt_hash,
                PUBLISHING.sha256_bytes(PUBLISHING.json_payload_bytes(second_metadata)),
            )
            PUBLISHING.write_immutable_json_atomic(
                second_metadata_path, second_metadata, action="transcribe"
            )

            persisted_first = json.loads(first_metadata_path.read_text(encoding="utf-8"))
            self.assertNotEqual(first_context, second_context)
            self.assertNotEqual(first_metadata_path, second_metadata_path)
            self.assertEqual(Path(persisted_first["context_file"]).read_bytes(), first_bytes)
            self.assertEqual(
                persisted_first["context_sha256"],
                PUBLISHING.sha256_bytes(first_bytes),
            )
            self.assertEqual(len(list(work_dir.glob("context-*.txt"))), 2)

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
            original_promote = PUBLISHING.promote_temp_file
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
                patch.object(PUBLISHING, "promote_temp_file", side_effect=fail_second),
                patch.object(PUBLISHING, "unlink_with_retries", side_effect=locked_unlink),
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

            with patch.object(TRANSCRIBE, "process_media", side_effect=fake_process):
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
            with patch.object(TRANSCRIBE, "process_media") as process_media:
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
                patch.object(TRANSCRIBE, "fetch_video_metadata", return_value=video_metadata),
                patch.object(
                    TRANSCRIBE,
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

    def test_two_same_title_videos_preserve_distinct_metadata_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output_dir = root / "out"
            manual = root / "manual.en.srt"
            manual.write_text(
                "1\n00:00:00,000 --> 00:00:01,000\nHello.\n",
                encoding="utf-8",
            )
            first_video = {
                "id": "video-1",
                "title": "Same title",
                "channel": "Channel",
                "description": "First description.",
                "subtitles": {"en": [{"ext": "srt"}]},
            }
            second_video = {
                "id": "video-2",
                "title": "Same title",
                "channel": "Channel",
                "description": "Second description.",
                "subtitles": {"en": [{"ext": "srt"}]},
            }

            def run_video(url: str, metadata: dict[str, object], *, replace: bool):
                command = [
                    "transcribe",
                    url,
                    "--require-language",
                    "en",
                    "--output-dir",
                    str(output_dir),
                ]
                if replace:
                    command.append("--replace-existing")
                args = CLI.build_parser().parse_args(command)
                with (
                    patch.object(
                        TRANSCRIBE, "fetch_video_metadata", return_value=metadata
                    ),
                    patch.object(
                        TRANSCRIBE,
                        "download_manual_subtitles",
                        return_value=(manual, metadata, "en"),
                    ),
                ):
                    return CLI.run_transcribe(args)

            first_result = run_video(
                "https://www.youtube.com/watch?v=video-1", first_video, replace=False
            )
            first_metadata_path = Path(first_result["metadata"])
            first_metadata_bytes = first_metadata_path.read_bytes()
            first_payload = json.loads(first_metadata_bytes)

            second_result = run_video(
                "https://www.youtube.com/watch?v=video-2", second_video, replace=True
            )
            second_metadata_path = Path(second_result["metadata"])

            self.assertNotEqual(first_metadata_path, second_metadata_path)
            self.assertEqual(first_metadata_path.read_bytes(), first_metadata_bytes)
            self.assertEqual(first_payload["video_metadata"]["id"], "video-1")
            self.assertEqual(
                Path(first_payload["context_file"]).read_text(encoding="utf-8"),
                "Title: Same title\nChannel: Channel\nDescription:\nFirst description.\n",
            )
            self.assertEqual(
                json.loads(second_metadata_path.read_text(encoding="utf-8"))[
                    "video_metadata"
                ]["id"],
                "video-2",
            )

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
            with (
                patch.object(TRANSCRIBE, "fetch_video_metadata", return_value=video_metadata),
                patch.object(
                    TRANSCRIBE,
                    "download_manual_subtitles",
                    return_value=(manual, video_metadata, "en"),
                ),
                patch.object(
                    TRANSCRIBE,
                    "write_immutable_json_atomic",
                    side_effect=OSError("simulated metadata write failure"),
                ),
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
            ["transcribe", "input.mp4", "--max-packed-word-repairs-per-10k", "0"],
            ["transcribe", "input.mp4", "--max-packed-cluster-size", "-1"],
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

    def test_invalid_packed_repair_environment_limits_are_structured(self) -> None:
        cases = [
            ("SUBTITLE_MAX_PACKED_WORD_REPAIRS_PER_10K", "0"),
            ("SUBTITLE_MAX_PACKED_CLUSTER_SIZE", "not-an-int"),
        ]
        for name, value in cases:
            with self.subTest(name=name, value=value):
                environment = os.environ.copy()
                environment[name] = value
                result = subprocess.run(
                    [sys.executable, str(CLI_PATH), "transcribe", "unused.mp4"],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    env=environment,
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
                patch.object(TRANSCRIBE, "fetch_video_metadata", return_value=metadata),
                patch.object(TRANSCRIBE, "download_manual_subtitles") as download_manual,
                patch.object(TRANSCRIBE, "process_media", return_value=split_result) as process_media,
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
                    with patch.object(TRANSCRIBE, "process_media", return_value=split_result):
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
            with patch.object(TRANSCRIBE, "process_media", return_value=split_result):
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

    def test_pair_lock_rejects_hardlink_without_modifying_target(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = CLI.output_paths(root, "same")
            lock_key = "|".join(
                sorted(CLI.file_identity(path) for path in paths.values())
            )
            digest = CLI.hashlib.sha256(lock_key.encode("utf-8")).hexdigest()[:16]
            lock_path = root / f".subtitle-pair-{digest}.lock"
            victim = root / "important.txt"
            victim.write_bytes(b"preserve-me")
            try:
                os.link(victim, lock_path)
            except OSError as exc:
                self.skipTest(f"hardlinks unavailable: {exc}")

            with self.assertRaises(CLI.SubtitleSkillError) as raised:
                with CLI.output_pair_lock(paths, "normalize"):
                    self.fail("unsafe hardlinked lock unexpectedly opened")

            self.assertEqual(raised.exception.error_type, "unsafe_lock_path")
            self.assertEqual(victim.read_bytes(), b"preserve-me")

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
            original_validate = PUBLISHING.validate_main_outputs
            calls = 0

            def fail_second_validation(*call_args: object, **call_kwargs: object) -> None:
                nonlocal calls
                calls += 1
                if calls > 1:
                    raise OSError("injected post-commit validation failure")
                original_validate(*call_args, **call_kwargs)

            with patch.object(
                PUBLISHING, "validate_main_outputs", side_effect=fail_second_validation
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
            original_promote = PUBLISHING.promote_temp_file
            calls = 0

            def fail_srt_promotion(source_path: Path, target_path: Path) -> None:
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("injected SRT promotion failure")
                original_promote(source_path, target_path)

            with patch.object(
                PUBLISHING, "promote_temp_file", side_effect=fail_srt_promotion
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

            with patch.object(TRANSCRIBE, "process_media", side_effect=fake_process):
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

            with patch.object(TRANSCRIBE, "process_media", side_effect=fake_process):
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

            source_qc = root / "final-english-qc.json"
            qc_args = CLI.build_parser().parse_args(
                ["qc", str(source), "--output", str(source_qc)]
            )
            qc_result = CLI.run_qc(qc_args)
            self.assertEqual(qc_result["exit_code"], 0)

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
                    "--source-qc-report",
                    str(source_qc),
                    "--duration",
                    "1",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self.assertEqual(validated.returncode, 0, validated.stderr or validated.stdout)

    def test_semantic_transcribe_reports_and_binds_checkpoint_progress(self) -> None:
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
                    "test",
                    "--output-dir",
                    str(root / "out"),
                ]
            )
            data = ASRData(
                [
                    ASRDataSeg(
                        "Hello.",
                        0,
                        1000,
                        words=[ASRWord("Hello.", 0, 1000)],
                    )
                ]
            )
            expected_progress = {
                "checkpoint_path": str(root / "checkpoint.json"),
                "chunk_count": 1,
                "resumed_chunk_count": 0,
                "completed_chunk_count": 1,
            }

            def fake_process(*_args: object, **kwargs: object) -> ASRData:
                kwargs["asr_metadata_out"].update(
                    {"language": "en", "language_probability": 1.0}
                )
                kwargs["split_progress_out"].update(expected_progress)
                return data

            with patch.object(TRANSCRIBE, "process_media", side_effect=fake_process):
                result = CLI.run_transcribe(args)

            self.assertEqual(result["semantic_split_progress"], expected_progress)
            metadata = json.loads(Path(result["metadata"]).read_text(encoding="utf-8"))
            self.assertEqual(metadata["semantic_split_progress"], expected_progress)

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

    def test_faster_whisper_repairs_zero_duration_word_with_auditable_interval(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            media = root / "source.wav"
            media.touch()
            model = Mock()
            words = [
                SimpleNamespace(word=" hello", start=0.0, end=0.5),
                SimpleNamespace(word=" And", start=1.0, end=1.0),
                SimpleNamespace(word=" so", start=1.0, end=1.2),
            ]
            segment = SimpleNamespace(
                id=0,
                start=0.0,
                end=1.2,
                text="hello And so",
                words=words,
            )
            info = SimpleNamespace(
                language="en",
                language_probability=1.0,
                duration=1.2,
            )
            model.transcribe.return_value = (iter([segment]), info)
            config = TranscribeConfig(output_dir=str(root / "work"), language="en")
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

            repaired_word = result.words[1]
            self.assertEqual((repaired_word.start_time, repaired_word.end_time), (999, 1000))
            raw_path = next((root / "work").glob("source-*.asr.json"))
            raw_payload = json.loads(raw_path.read_text(encoding="utf-8"))
            self.assertEqual(len(raw_payload["timestamp_repairs"]), 1)
            repair = raw_payload["timestamp_repairs"][0]
            self.assertEqual(repair["word"], " And")
            self.assertEqual(repair["method"], "bounded_1ms_before_reported_time")
            self.assertEqual(repair["original_start"], repair["original_end"])

    def test_faster_whisper_repairs_zero_duration_word_forward_when_needed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            media = root / "source.wav"
            media.touch()
            model = Mock()
            segment = SimpleNamespace(
                id=0,
                start=0.0,
                end=1.0,
                text="And then",
                words=[
                    SimpleNamespace(word=" And", start=0.0, end=0.0),
                    SimpleNamespace(word=" then", start=0.5, end=1.0),
                ],
            )
            info = SimpleNamespace(language="en", language_probability=1.0, duration=1.0)
            model.transcribe.return_value = (iter([segment]), info)
            asr = FasterWhisperASR(
                str(media),
                TranscribeConfig(output_dir=str(root / "work"), language="en"),
            )
            fake_module = types.ModuleType("faster_whisper")
            fake_module.WhisperModel = object

            with (
                patch.dict(sys.modules, {"faster_whisper": fake_module}),
                patch.object(asr, "_load_model_with_fallback", return_value=(model, "cpu", "int8")),
            ):
                result = asr.run()

            self.assertEqual((result.words[0].start_time, result.words[0].end_time), (0, 1))

    def test_faster_whisper_repairs_packed_word_and_audits_donor(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            media = root / "source.wav"
            media.touch()
            model = Mock()
            segment = SimpleNamespace(
                id=0,
                start=0.0,
                end=2.0,
                text="before zero after",
                words=[
                    SimpleNamespace(word=" before", start=0.0, end=1.0),
                    SimpleNamespace(word=" zero", start=1.0, end=1.0),
                    SimpleNamespace(word=" after", start=1.0, end=2.0),
                ],
            )
            info = SimpleNamespace(language="en", language_probability=1.0, duration=2.0)
            model.transcribe.return_value = (iter([segment]), info)
            asr = FasterWhisperASR(
                str(media),
                TranscribeConfig(output_dir=str(root / "work"), language="en"),
            )
            fake_module = types.ModuleType("faster_whisper")
            fake_module.WhisperModel = object

            with (
                patch.dict(sys.modules, {"faster_whisper": fake_module}),
                patch.object(asr, "_load_model_with_fallback", return_value=(model, "cpu", "int8")),
            ):
                result = asr.run()

            self.assertEqual(
                [(word.start_time, word.end_time) for word in result.words],
                [(0, 1000), (1000, 1001), (1001, 2000)],
            )
            raw_payload = json.loads(
                next((root / "work").glob("source-*.asr.json")).read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(
                [repair["method"] for repair in raw_payload["timestamp_repairs"]],
                [
                    "packed_cluster_redistribution",
                    "packed_cluster_right_donor_adjustment",
                ],
            )
            self.assertEqual(
                raw_payload["timestamp_repair_summary"]["packed_word_repairs"], 1
            )
            self.assertEqual(
                raw_payload["timestamp_repair_summary"]["donor_adjustments"], 1
            )

    def test_faster_whisper_repairs_segment_boundaries_within_each_segment(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            media = root / "source.wav"
            media.touch()
            model = Mock()
            segments = [
                SimpleNamespace(
                    id=0,
                    start=0.0,
                    end=0.08,
                    text="I do",
                    words=[
                        SimpleNamespace(word=" I", start=0.0, end=0.0),
                        SimpleNamespace(word=" do", start=0.0, end=0.08),
                    ],
                ),
                SimpleNamespace(
                    id=1,
                    start=1.0,
                    end=1.08,
                    text="before And",
                    words=[
                        SimpleNamespace(word=" before", start=1.0, end=1.08),
                        SimpleNamespace(word=" And", start=1.08, end=1.08),
                    ],
                ),
            ]
            info = SimpleNamespace(language="en", language_probability=1.0, duration=1.08)
            model.transcribe.return_value = (iter(segments), info)
            asr = FasterWhisperASR(
                str(media),
                TranscribeConfig(output_dir=str(root / "work"), language="en"),
            )
            fake_module = types.ModuleType("faster_whisper")
            fake_module.WhisperModel = object

            with (
                patch.dict(sys.modules, {"faster_whisper": fake_module}),
                patch.object(asr, "_load_model_with_fallback", return_value=(model, "cpu", "int8")),
            ):
                result = asr.run()

            self.assertEqual(
                [(word.start_time, word.end_time) for word in result.words],
                [(0, 1), (1, 80), (1000, 1079), (1079, 1080)],
            )

    def test_faster_whisper_repairs_four_word_cluster(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            media = root / "source.wav"
            media.touch()
            model = Mock()
            segment = SimpleNamespace(
                id=0,
                start=1.0,
                end=1.24,
                text="before not exercising the code after",
                words=[
                    SimpleNamespace(word=" before", start=1.0, end=1.2),
                    SimpleNamespace(word=" not", start=1.2, end=1.2),
                    SimpleNamespace(word=" exercising", start=1.2, end=1.2),
                    SimpleNamespace(word=" the", start=1.2, end=1.2),
                    SimpleNamespace(word=" code", start=1.2, end=1.2),
                    SimpleNamespace(word=" after", start=1.2, end=1.24),
                ],
            )
            info = SimpleNamespace(language="en", language_probability=1.0, duration=1.24)
            model.transcribe.return_value = (iter([segment]), info)
            asr = FasterWhisperASR(
                str(media),
                TranscribeConfig(output_dir=str(root / "work"), language="en"),
            )
            fake_module = types.ModuleType("faster_whisper")
            fake_module.WhisperModel = object

            with (
                patch.dict(sys.modules, {"faster_whisper": fake_module}),
                patch.object(asr, "_load_model_with_fallback", return_value=(model, "cpu", "int8")),
            ):
                result = asr.run()

            self.assertTrue(result.has_word_timestamps())
            self.assertTrue(
                all(word.end_time > word.start_time for word in result.words)
            )
            raw_payload = json.loads(
                next((root / "work").glob("source-*.asr.json")).read_text(
                    encoding="utf-8"
                )
            )
            summary = raw_payload["timestamp_repair_summary"]
            self.assertEqual(summary["packed_cluster_count"], 1)
            self.assertEqual(summary["packed_word_repairs"], 4)
            self.assertEqual(summary["max_observed_cluster_size"], 4)
            self.assertEqual(summary["donor_adjustments"], 1)
            self.assertTrue(summary["review_recommended"])

    def test_faster_whisper_repairs_allowed_cluster_using_outer_gaps_as_one_unit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            media = root / "source.wav"
            media.touch()
            model = Mock()
            segment = SimpleNamespace(
                id=0,
                start=0.0,
                end=2.0,
                text="before one two three four after",
                words=[
                    SimpleNamespace(word=" before", start=0.0, end=0.99),
                    SimpleNamespace(word=" one", start=1.0, end=1.0),
                    SimpleNamespace(word=" two", start=1.0, end=1.0),
                    SimpleNamespace(word=" three", start=1.0, end=1.0),
                    SimpleNamespace(word=" four", start=1.0, end=1.0),
                    SimpleNamespace(word=" after", start=1.01, end=2.0),
                ],
            )
            info = SimpleNamespace(language="en", language_probability=1.0, duration=2.0)
            model.transcribe.return_value = (iter([segment]), info)
            asr = FasterWhisperASR(
                str(media),
                TranscribeConfig(output_dir=str(root / "work"), language="en"),
            )
            fake_module = types.ModuleType("faster_whisper")
            fake_module.WhisperModel = object

            with (
                patch.dict(sys.modules, {"faster_whisper": fake_module}),
                patch.object(asr, "_load_model_with_fallback", return_value=(model, "cpu", "int8")),
            ):
                result = asr.run()

            repaired = result.words[1:5]
            self.assertTrue(all(word.end_time > word.start_time for word in repaired))
            self.assertTrue(
                all(
                    repaired[index].end_time <= repaired[index + 1].start_time
                    for index in range(len(repaired) - 1)
                )
            )
            summary = asr.result_metadata["timestamp_repair_summary"]
            self.assertEqual(summary["gap_repairs"], 0)
            self.assertEqual(summary["packed_word_repairs"], 4)
            self.assertEqual(summary["donor_adjustments"], 0)
            self.assertEqual(summary["borrowed_ms"], 0)

    def test_faster_whisper_preserves_raw_evidence_when_packed_repair_exceeds_limit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            media = root / "source.wav"
            media.touch()
            model = Mock()
            segment = SimpleNamespace(
                id=0,
                start=0.0,
                end=1.0,
                text="one two after",
                words=[
                    SimpleNamespace(word=" one", start=0.0, end=0.0),
                    SimpleNamespace(word=" two", start=0.0, end=0.0),
                    SimpleNamespace(word=" after", start=0.0, end=1.0),
                ],
            )
            info = SimpleNamespace(language="en", language_probability=1.0, duration=1.0)
            model.transcribe.return_value = (iter([segment]), info)
            asr = FasterWhisperASR(
                str(media),
                TranscribeConfig(
                    output_dir=str(root / "work"),
                    language="en",
                    max_packed_word_repairs_per_10k=1,
                    max_packed_cluster_size=1,
                ),
            )
            fake_module = types.ModuleType("faster_whisper")
            fake_module.WhisperModel = object

            with (
                patch.dict(sys.modules, {"faster_whisper": fake_module}),
                patch.object(asr, "_load_model_with_fallback", return_value=(model, "cpu", "int8")),
            ):
                with self.assertRaisesRegex(
                    TimestampRepairLimitError, "packed zero-duration"
                ) as raised:
                    asr.run()

            self.assertTrue(raised.exception.raw_asr_path.exists())
            self.assertEqual(
                hashlib.sha256(raised.exception.raw_asr_path.read_bytes()).hexdigest(),
                raised.exception.raw_asr_sha256,
            )
            raw_payload = json.loads(
                raised.exception.raw_asr_path.read_text(encoding="utf-8")
            )
            self.assertEqual(raw_payload["timestamp_repair_summary"]["status"], "blocked")
            self.assertEqual(raw_payload["timestamp_repairs"], [])

    def test_faster_whisper_blocks_original_cluster_before_gap_repair_can_peel_it(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            media = root / "source.wav"
            media.touch()
            model = Mock()
            words = [SimpleNamespace(word=" before", start=0.0, end=1.0)]
            words.extend(
                SimpleNamespace(word=f" zero-{index}", start=1.0, end=1.0)
                for index in range(5)
            )
            words.append(SimpleNamespace(word=" after", start=1.01, end=2.0))
            segment = SimpleNamespace(
                id=0,
                start=0.0,
                end=2.0,
                text="original five-word collapse",
                words=words,
            )
            info = SimpleNamespace(language="en", language_probability=1.0, duration=2.0)
            model.transcribe.return_value = (iter([segment]), info)
            asr = FasterWhisperASR(
                str(media),
                TranscribeConfig(output_dir=str(root / "work"), language="en"),
            )
            fake_module = types.ModuleType("faster_whisper")
            fake_module.WhisperModel = object

            with (
                patch.dict(sys.modules, {"faster_whisper": fake_module}),
                patch.object(asr, "_load_model_with_fallback", return_value=(model, "cpu", "int8")),
            ):
                with self.assertRaises(TimestampRepairLimitError) as raised:
                    asr.run()

            summary = raised.exception.repair_summary
            self.assertEqual(summary["status"], "blocked")
            self.assertEqual(summary["max_observed_cluster_size"], 5)
            self.assertEqual(summary["gap_repairs"], 0)
            self.assertIn("cluster size 5", "; ".join(summary["blocked_reasons"]))

    def test_faster_whisper_blocks_staggered_contiguous_zero_duration_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            media = root / "source.wav"
            media.touch()
            model = Mock()
            words = [SimpleNamespace(word=" before", start=0.0, end=1.0)]
            words.extend(
                SimpleNamespace(
                    word=f" zero-{index}",
                    start=1.001 + index * 0.001,
                    end=1.001 + index * 0.001,
                )
                for index in range(5)
            )
            words.append(SimpleNamespace(word=" after", start=1.01, end=2.0))
            segment = SimpleNamespace(
                id=0,
                start=0.0,
                end=2.0,
                text="staggered five-word collapse",
                words=words,
            )
            info = SimpleNamespace(language="en", language_probability=1.0, duration=2.0)
            model.transcribe.return_value = (iter([segment]), info)
            asr = FasterWhisperASR(
                str(media),
                TranscribeConfig(output_dir=str(root / "work"), language="en"),
            )
            fake_module = types.ModuleType("faster_whisper")
            fake_module.WhisperModel = object

            with (
                patch.dict(sys.modules, {"faster_whisper": fake_module}),
                patch.object(asr, "_load_model_with_fallback", return_value=(model, "cpu", "int8")),
            ):
                with self.assertRaises(TimestampRepairLimitError) as raised:
                    asr.run()

            summary = raised.exception.repair_summary
            self.assertEqual(summary["max_observed_cluster_size"], 5)
            self.assertEqual(summary["gap_repairs"], 0)
            self.assertEqual(summary["cluster_samples"][0]["timestamp_ms"], 1001)
            self.assertEqual(summary["cluster_samples"][0]["end_timestamp_ms"], 1005)

    def test_faster_whisper_blocks_non_monotonic_zero_run_with_raw_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            media = root / "source.wav"
            media.touch()
            model = Mock()
            segment = SimpleNamespace(
                id=0,
                start=0.0,
                end=2.0,
                text="left a b right",
                words=[
                    SimpleNamespace(word=" left", start=0.0, end=1.0),
                    SimpleNamespace(word=" a", start=1.002, end=1.002),
                    SimpleNamespace(word=" b", start=1.001, end=1.001),
                    SimpleNamespace(word=" right", start=1.002, end=2.0),
                ],
            )
            info = SimpleNamespace(language="en", language_probability=1.0, duration=2.0)
            model.transcribe.return_value = (iter([segment]), info)
            asr = FasterWhisperASR(
                str(media),
                TranscribeConfig(output_dir=str(root / "work"), language="en"),
            )
            fake_module = types.ModuleType("faster_whisper")
            fake_module.WhisperModel = object

            with (
                patch.dict(sys.modules, {"faster_whisper": fake_module}),
                patch.object(asr, "_load_model_with_fallback", return_value=(model, "cpu", "int8")),
            ):
                with self.assertRaises(TimestampRepairLimitError) as raised:
                    asr.run()

            summary = raised.exception.repair_summary
            self.assertEqual(summary["status"], "blocked")
            self.assertEqual(summary["gap_repairs"], 0)
            self.assertEqual(summary["packed_word_repairs"], 0)
            self.assertIn("non-monotonic", "; ".join(summary["blocked_reasons"]))
            sample = summary["cluster_samples"][0]
            self.assertFalse(sample["timestamps_monotonic"])
            self.assertEqual(sample["timestamp_ms_samples"], [1002, 1001])
            raw_payload = json.loads(
                raised.exception.raw_asr_path.read_text(encoding="utf-8")
            )
            self.assertEqual(raw_payload["timestamp_repairs"], [])
            self.assertEqual(
                hashlib.sha256(raised.exception.raw_asr_path.read_bytes()).hexdigest(),
                raised.exception.raw_asr_sha256,
            )

    def test_faster_whisper_blocks_mixed_same_time_and_staggered_reverse_zero_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            media = root / "source.wav"
            media.touch()
            model = Mock()
            segment = SimpleNamespace(
                id=0,
                start=0.0,
                end=2.0,
                text="left a b c right",
                words=[
                    SimpleNamespace(word=" left", start=0.0, end=1.0),
                    SimpleNamespace(word=" a", start=1.002, end=1.002),
                    SimpleNamespace(word=" b", start=1.002, end=1.002),
                    SimpleNamespace(word=" c", start=1.001, end=1.001),
                    SimpleNamespace(word=" right", start=1.002, end=2.0),
                ],
            )
            info = SimpleNamespace(language="en", language_probability=1.0, duration=2.0)
            model.transcribe.return_value = (iter([segment]), info)
            asr = FasterWhisperASR(
                str(media),
                TranscribeConfig(output_dir=str(root / "work"), language="en"),
            )
            fake_module = types.ModuleType("faster_whisper")
            fake_module.WhisperModel = object

            with (
                patch.dict(sys.modules, {"faster_whisper": fake_module}),
                patch.object(asr, "_load_model_with_fallback", return_value=(model, "cpu", "int8")),
            ):
                with self.assertRaises(TimestampRepairLimitError) as raised:
                    asr.run()

            summary = raised.exception.repair_summary
            self.assertEqual(summary["status"], "blocked")
            self.assertEqual(summary["gap_repairs"], 0)
            self.assertEqual(summary["packed_word_repairs"], 0)
            self.assertIn("non-monotonic", "; ".join(summary["blocked_reasons"]))
            self.assertEqual(
                summary["cluster_samples"][0]["timestamp_ms_samples"],
                [1002, 1002, 1001],
            )

    def test_faster_whisper_bounds_blocked_cluster_samples(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            media = root / "source.wav"
            media.touch()
            model = Mock()
            long_token = " x" * 500
            segment = SimpleNamespace(
                id=0,
                start=0.0,
                end=2.0,
                text="large collapsed cluster",
                words=[
                    SimpleNamespace(
                        word=f"{long_token}-{index}", start=1.0, end=1.0
                    )
                    for index in range(100)
                ],
            )
            info = SimpleNamespace(language="en", language_probability=1.0, duration=2.0)
            model.transcribe.return_value = (iter([segment]), info)
            asr = FasterWhisperASR(
                str(media),
                TranscribeConfig(output_dir=str(root / "work"), language="en"),
            )
            fake_module = types.ModuleType("faster_whisper")
            fake_module.WhisperModel = object

            with (
                patch.dict(sys.modules, {"faster_whisper": fake_module}),
                patch.object(asr, "_load_model_with_fallback", return_value=(model, "cpu", "int8")),
            ):
                with self.assertRaises(TimestampRepairLimitError) as raised:
                    asr.run()

            summary = raised.exception.repair_summary
            sample = summary["cluster_samples"][0]
            self.assertNotIn("words", sample)
            self.assertLessEqual(len(sample["word_samples"]), 5)
            self.assertTrue(sample["word_samples_truncated"])
            self.assertTrue(
                all(len(item["word"]) <= 40 for item in sample["word_samples"])
            )
            self.assertLess(len(json.dumps(summary, ensure_ascii=True)), 5000)

    def test_faster_whisper_blocks_packed_word_without_safe_donor(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            media = root / "source.wav"
            media.touch()
            model = Mock()
            segment = SimpleNamespace(
                id=0,
                start=0.0,
                end=0.02,
                text="left zero right",
                words=[
                    SimpleNamespace(word=" left", start=0.0, end=0.01),
                    SimpleNamespace(word=" zero", start=0.01, end=0.01),
                    SimpleNamespace(word=" right", start=0.01, end=0.02),
                ],
            )
            info = SimpleNamespace(language="en", language_probability=1.0, duration=0.02)
            model.transcribe.return_value = (iter([segment]), info)
            asr = FasterWhisperASR(
                str(media),
                TranscribeConfig(output_dir=str(root / "work"), language="en"),
            )
            fake_module = types.ModuleType("faster_whisper")
            fake_module.WhisperModel = object

            with (
                patch.dict(sys.modules, {"faster_whisper": fake_module}),
                patch.object(asr, "_load_model_with_fallback", return_value=(model, "cpu", "int8")),
            ):
                with self.assertRaises(TimestampRepairLimitError) as raised:
                    asr.run()

            self.assertIn(
                "safely provide only 0 ms",
                "; ".join(raised.exception.repair_summary["blocked_reasons"]),
            )

    def test_faster_whisper_rolls_back_planned_gap_repairs_when_later_cluster_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            media = root / "source.wav"
            media.touch()
            model = Mock()
            original_words = [
                SimpleNamespace(word=" first", start=0.0, end=0.5),
                SimpleNamespace(word=" isolated", start=0.6, end=0.6),
                SimpleNamespace(word=" bridge", start=0.6, end=0.61),
                SimpleNamespace(word=" packed", start=0.61, end=0.61),
                SimpleNamespace(word=" last", start=0.61, end=0.62),
            ]
            segment = SimpleNamespace(
                id=0,
                start=0.0,
                end=0.62,
                text="first isolated bridge packed last",
                words=original_words,
            )
            info = SimpleNamespace(language="en", language_probability=1.0, duration=0.62)
            model.transcribe.return_value = (iter([segment]), info)
            asr = FasterWhisperASR(
                str(media),
                TranscribeConfig(output_dir=str(root / "work"), language="en"),
            )
            fake_module = types.ModuleType("faster_whisper")
            fake_module.WhisperModel = object

            with (
                patch.dict(sys.modules, {"faster_whisper": fake_module}),
                patch.object(asr, "_load_model_with_fallback", return_value=(model, "cpu", "int8")),
            ):
                with self.assertRaises(TimestampRepairLimitError) as raised:
                    asr.run()

            summary = raised.exception.repair_summary
            self.assertEqual(summary["status"], "blocked")
            self.assertEqual(summary["gap_repairs"], 0)
            self.assertEqual(summary["packed_word_repairs"], 0)
            self.assertEqual(summary["total_repair_records"], 0)
            raw_payload = json.loads(
                raised.exception.raw_asr_path.read_text(encoding="utf-8")
            )
            self.assertEqual(raw_payload["timestamp_repairs"], [])
            self.assertEqual(
                [
                    (word["start"], word["end"])
                    for word in raw_payload["segments"][0]["words"]
                ],
                [
                    (word.start, word.end)
                    for word in original_words
                ],
            )

    def test_faster_whisper_does_not_repair_reverse_timestamp(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            media = root / "source.wav"
            media.touch()
            model = Mock()
            segment = SimpleNamespace(
                id=0,
                start=0.0,
                end=3.0,
                text="bad timestamps",
                words=[SimpleNamespace(word=" bad", start=2.0, end=1.0)],
            )
            info = SimpleNamespace(language="en", language_probability=1.0, duration=3.0)
            model.transcribe.return_value = (iter([segment]), info)
            asr = FasterWhisperASR(
                str(media),
                TranscribeConfig(output_dir=str(root / "work"), language="en"),
            )
            fake_module = types.ModuleType("faster_whisper")
            fake_module.WhisperModel = object

            with (
                patch.dict(sys.modules, {"faster_whisper": fake_module}),
                patch.object(asr, "_load_model_with_fallback", return_value=(model, "cpu", "int8")),
            ):
                with self.assertRaisesRegex(ValueError, "non-positive duration"):
                    asr.run()


if __name__ == "__main__":
    unittest.main()
