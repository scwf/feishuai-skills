"""Subtitle optimization module."""

import atexit
import difflib
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Dict, List, Optional, Tuple, Union

import json_repair

from .alignment import SubtitleAligner
from .data import ASRData, ASRDataSeg
from .llm import call_llm
from .prompts import get_prompt
from .utils import count_words, setup_logger


logger = setup_logger("subtitle_optimizer")

MAX_STEPS = 2


class SubtitleOptimizer:
    def __init__(
        self,
        thread_num: int,
        batch_num: int,
        model: str,
        custom_prompt: str,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        update_callback: Optional[Callable] = None,
    ):
        self.thread_num = thread_num
        self.batch_num = batch_num
        self.model = model
        self.custom_prompt = custom_prompt
        self.api_key = api_key
        self.base_url = base_url
        self.update_callback = update_callback
        self.is_running = True
        self.executor: Optional[ThreadPoolExecutor] = None
        self._init_thread_pool()

    def _init_thread_pool(self) -> None:
        self.executor = ThreadPoolExecutor(max_workers=self.thread_num)
        atexit.register(self.stop)

    def optimize_subtitle(self, subtitle_data: Union[str, ASRData]) -> ASRData:
        try:
            if isinstance(subtitle_data, str):
                if subtitle_data.lower().endswith(".srt"):
                    with open(subtitle_data, "r", encoding="utf-8") as f:
                        asr_data = ASRData.from_srt(f.read())
                else:
                    raise NotImplementedError("Only SRT file path or ASRData object is supported")
            else:
                asr_data = subtitle_data

            subtitle_dict = {str(i): seg.text for i, seg in enumerate(asr_data.segments, 1)}
            chunks = self._split_chunks(subtitle_dict)
            optimized_dict = self._parallel_optimize(chunks)
            new_segments = self._create_segments(asr_data.segments, optimized_dict)
            return ASRData(new_segments)
        except Exception as e:
            logger.error(f"Optimization failed: {str(e)}")
            raise RuntimeError(f"Optimization failed: {str(e)}")

    def _split_chunks(self, subtitle_dict: Dict[str, str]) -> List[Dict[str, str]]:
        items = list(subtitle_dict.items())
        return [dict(items[i : i + self.batch_num]) for i in range(0, len(items), self.batch_num)]

    def _parallel_optimize(self, chunks: List[Dict[str, str]]) -> Dict[str, str]:
        if not self.executor:
            raise ValueError("Thread pool not initialized")

        futures = []
        optimized_dict: Dict[str, str] = {}

        for chunk in chunks:
            future = self.executor.submit(self._optimize_chunk, chunk)
            futures.append((future, chunk))

        for future, chunk in futures:
            if not self.is_running:
                break
            try:
                result = future.result()
                optimized_dict.update(result)
            except Exception as e:
                logger.error(f"Batch optimization failed: {str(e)}")
                optimized_dict.update(chunk)

        return optimized_dict

    def _optimize_chunk(self, subtitle_chunk: Dict[str, str]) -> Dict[str, str]:
        start_idx = next(iter(subtitle_chunk))
        end_idx = next(reversed(subtitle_chunk))
        logger.info(f"Optimizing subtitles: {start_idx} - {end_idx}")
        try:
            return self.agent_loop(subtitle_chunk)
        except Exception as e:
            logger.error(f"Optimization failed: {str(e)}")
            return subtitle_chunk

    def agent_loop(self, subtitle_chunk: Dict[str, str]) -> Dict[str, str]:
        user_prompt = (
            "Correct the following subtitles. Keep the original language, do not translate:\n"
            f"<input_subtitle>{str(subtitle_chunk)}</input_subtitle>"
        )
        if self.custom_prompt:
            user_prompt += f"\nReference content:\n<reference>{self.custom_prompt}</reference>"

        messages = [
            {"role": "system", "content": get_prompt("optimize/subtitle")},
            {"role": "user", "content": user_prompt},
        ]

        last_result = None

        for step in range(MAX_STEPS):
            response = call_llm(
                messages=messages,
                model=self.model,
                temperature=0.2,
                api_key=self.api_key,
                base_url=self.base_url,
            )
            result_text = response.choices[0].message.content
            if not result_text:
                raise ValueError("LLM returned empty result")

            parsed_result = json_repair.loads(result_text)
            if not isinstance(parsed_result, dict):
                raise ValueError(f"LLM returned wrong type, expected dict, got {type(parsed_result)}")

            result_dict: Dict[str, str] = parsed_result
            last_result = result_dict

            is_valid, error_message = self._validate_optimization_result(
                original_chunk=subtitle_chunk, optimized_chunk=result_dict
            )

            if is_valid:
                return self._repair_subtitle(subtitle_chunk, result_dict)

            logger.warning(f"Optimization validation failed, retrying (Step {step + 1}): {error_message}")
            messages.append({"role": "assistant", "content": result_text})
            messages.append(
                {
                    "role": "user",
                    "content": (
                        f"Validation failed: {error_message}\n"
                        "Please fix the errors and output ONLY a valid JSON dictionary."
                    ),
                }
            )

        logger.warning(f"Reached max attempts ({MAX_STEPS}), returning last result")
        return self._repair_subtitle(subtitle_chunk, last_result) if last_result else subtitle_chunk

    def _validate_optimization_result(
        self, original_chunk: Dict[str, str], optimized_chunk: Dict[str, str]
    ) -> Tuple[bool, str]:
        expected_keys = set(original_chunk.keys())
        actual_keys = set(optimized_chunk.keys())

        if expected_keys != actual_keys:
            missing = expected_keys - actual_keys
            extra = actual_keys - expected_keys
            error_parts = []
            if missing:
                error_parts.append(f"Missing keys: {sorted(missing)}")
            if extra:
                error_parts.append(f"Extra keys: {sorted(extra)}")

            error_msg = (
                "\n".join(error_parts) + f"\nRequired keys: {sorted(expected_keys)}\n"
                f"Please return the COMPLETE optimized dictionary with ALL {len(expected_keys)} keys."
            )
            return False, error_msg

        excessive_changes = []
        for key in expected_keys:
            original_text = original_chunk[key]
            optimized_text = optimized_chunk.get(key, "")
            original_cleaned = re.sub(r"\s+", " ", original_text).strip()
            optimized_cleaned = re.sub(r"\s+", " ", optimized_text).strip()
            matcher = difflib.SequenceMatcher(None, original_cleaned, optimized_cleaned)
            similarity = matcher.ratio()
            similarity_threshold = 0.3 if count_words(original_text) <= 10 else 0.7
            if similarity < similarity_threshold:
                excessive_changes.append(
                    f"Key '{key}': similarity {similarity:.1%} < {similarity_threshold:.0%}. "
                    f"Original: '{original_text}' -> Optimized: '{optimized_text}' "
                )

        if excessive_changes:
            error_msg = ";\n".join(excessive_changes)
            error_msg += (
                "\n\nYour optimizations changed the text too much. "
                "Keep high similarity (>=70% for normal text) by making MINIMAL changes: "
                "only fix recognition errors and improve clarity, "
                "but preserve the original wording, length and structure as much as possible."
            )
            return False, error_msg

        return True, ""

    @staticmethod
    def _repair_subtitle(original: Dict[str, str], optimized: Dict[str, str]) -> Dict[str, str]:
        try:
            aligner = SubtitleAligner()
            original_list = list(original.values())
            optimized_list = list(optimized.values())
            aligned_source, aligned_target = aligner.align_texts(original_list, optimized_list)

            if len(aligned_source) != len(aligned_target):
                logger.warning("Alignment length mismatch, returning original optimized result")
                return optimized

            start_id = next(iter(original.keys()))
            return {str(int(start_id) + i): text for i, text in enumerate(aligned_target)}
        except Exception as e:
            logger.error(f"Alignment failed: {str(e)}, returning original optimized result")
            return optimized

    @staticmethod
    def _create_segments(original_segments: List[ASRDataSeg], optimized_dict: Dict[str, str]) -> List[ASRDataSeg]:
        return [
            ASRDataSeg(
                text=optimized_dict.get(str(i), seg.text),
                start_time=seg.start_time,
                end_time=seg.end_time,
                translated_text=seg.translated_text,
                words=list(seg.words),
            )
            for i, seg in enumerate(original_segments, 1)
        ]

    def stop(self) -> None:
        if not self.is_running:
            return
        self.is_running = False
        if self.executor:
            try:
                self.executor.shutdown(wait=False, cancel_futures=True)
            except Exception:
                pass
            finally:
                self.executor = None
