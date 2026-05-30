"""Subtitle translation module."""

import atexit
import json
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Dict, List, Optional, Tuple, Union

import json_repair

from .data import ASRData, ASRDataSeg
from .llm import call_llm
from .prompts import get_prompt
from .utils import setup_logger


logger = setup_logger("subtitle_translator")

MAX_STEPS = 3


class SubtitleTranslator:
    def __init__(
        self,
        thread_num: int,
        batch_num: int,
        model: str,
        custom_prompt: str,
        target_language: str,
        is_reflect: bool = False,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        update_callback: Optional[Callable] = None,
    ):
        self.thread_num = thread_num
        self.batch_num = batch_num
        self.model = model
        self.custom_prompt = custom_prompt
        self.target_language = target_language
        self.is_reflect = is_reflect
        self.api_key = api_key
        self.base_url = base_url
        self.update_callback = update_callback
        self.is_running = True
        self.executor: Optional[ThreadPoolExecutor] = None
        self._init_thread_pool()

    def _init_thread_pool(self) -> None:
        self.executor = ThreadPoolExecutor(max_workers=self.thread_num)
        atexit.register(self.stop)

    def translate_subtitle(self, subtitle_data: Union[str, ASRData]) -> ASRData:
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
            translated_dict = self._parallel_translate(chunks)
            new_segments = self._create_segments(asr_data.segments, translated_dict)
            return ASRData(new_segments)
        except Exception as e:
            logger.error(f"Translation failed: {str(e)}")
            raise RuntimeError(f"Translation failed: {str(e)}")

    def _split_chunks(self, subtitle_dict: Dict[str, str]) -> List[Dict[str, str]]:
        items = list(subtitle_dict.items())
        return [dict(items[i : i + self.batch_num]) for i in range(0, len(items), self.batch_num)]

    def _parallel_translate(self, chunks: List[Dict[str, str]]) -> Dict[str, str]:
        if not self.executor:
            raise ValueError("Thread pool not initialized")

        futures = []
        translated_dict: Dict[str, str] = {}

        for chunk in chunks:
            future = self.executor.submit(self._translate_chunk, chunk)
            futures.append((future, chunk))

        for future, _chunk in futures:
            if not self.is_running:
                break
            result = future.result()
            translated_dict.update(result)

        return translated_dict

    def _translate_chunk(self, subtitle_chunk: Dict[str, str]) -> Dict[str, str]:
        start_idx = next(iter(subtitle_chunk))
        end_idx = next(reversed(subtitle_chunk))
        logger.info(f"Translating subtitles: {start_idx} - {end_idx} ...")

        prompt_name = "translate/reflect" if self.is_reflect else "translate/standard"
        system_prompt = get_prompt(
            prompt_name,
            target_language=self.target_language,
            custom_prompt=self.custom_prompt or "None.",
        )

        return self.agent_loop(system_prompt, subtitle_chunk)

    @staticmethod
    def _build_batch_input(subtitle_chunk: Dict[str, str]) -> str:
        payload = {
            "task": "Translate each subtitle item independently while preserving the same ids.",
            "items": [{"id": key, "text": value} for key, value in subtitle_chunk.items()],
        }
        return json.dumps(payload, ensure_ascii=False)

    @staticmethod
    def _build_repair_message(error_message: str, subtitle_chunk: Dict[str, str]) -> str:
        expected_keys = list(subtitle_chunk.keys())
        expected_key_list = ", ".join(expected_keys)
        return (
            f"Error: {error_message}\n\n"
            "Rebuild the ENTIRE batch as a valid JSON dictionary.\n"
            f"Required keys: {expected_key_list}\n"
            "Rules:\n"
            "- Keep exactly the same keys.\n"
            "- Every key must map to a non-empty translated string.\n"
            "- Translate only the text from that key.\n"
            "- Do not move meaning from one key to another.\n"
            "- If a subtitle is a fragment, keep it a fragment.\n"
            "- Output ONLY the corrected JSON dictionary.\n"
        )

    def agent_loop(
        self,
        system_prompt: str,
        subtitle_chunk: Dict[str, str],
    ) -> Dict[str, str]:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": self._build_batch_input(subtitle_chunk)},
        ]

        last_response_dict = None

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

            result_dict = parsed_result
            last_response_dict = result_dict

            is_valid, error_message = self._validate_translation_result(
                original_chunk=subtitle_chunk, translated_chunk=result_dict
            )

            if is_valid:
                return self._extract_final_translation(result_dict)

            logger.warning(f"Translation validation failed, retrying (Step {step + 1}): {error_message}")
            messages.append({"role": "assistant", "content": json.dumps(result_dict, ensure_ascii=False)})
            messages.append(
                {
                    "role": "user",
                    "content": self._build_repair_message(error_message, subtitle_chunk),
                }
            )

        raise ValueError(
            "Translation validation failed after retries."
            if last_response_dict is not None
            else "Translation returned no usable result."
        )

    def _validate_translation_result(
        self, original_chunk: Dict[str, str], translated_chunk: Dict[str, str]
    ) -> Tuple[bool, str]:
        expected_keys = set(original_chunk.keys())
        actual_keys = set(translated_chunk.keys())

        def sort_keys(keys):
            return sorted(keys, key=lambda x: int(x) if x.isdigit() else x)

        if expected_keys != actual_keys:
            missing = expected_keys - actual_keys
            extra = actual_keys - expected_keys
            error_parts = []

            if missing:
                error_parts.append(f"Missing keys {sort_keys(missing)} - you must translate these items")
            if extra:
                error_parts.append(f"Extra keys {sort_keys(extra)} - these keys are not in input, remove them")

            return False, "; ".join(error_parts)

        for key in sort_keys(expected_keys):
            value = translated_chunk[key]
            original_text = (original_chunk.get(key) or "").strip()

            if self.is_reflect:
                if not isinstance(value, dict):
                    return (
                        False,
                        f"Key '{key}': value must be a dict with 'native_translation' field. Got {type(value).__name__}.",
                    )

                if "native_translation" not in value:
                    available_keys = list(value.keys())
                    return (
                        False,
                        f"Key '{key}': missing 'native_translation' field. Found keys: {available_keys}.",
                    )

                final_value = value.get("native_translation")
                if not isinstance(final_value, str):
                    return False, f"Key '{key}': native_translation must be a string."
                if not final_value.strip():
                    return False, f"Key '{key}': native_translation must not be empty."
            else:
                if not isinstance(value, str):
                    return False, f"Key '{key}': translated value must be a string."
                if not value.strip():
                    return False, f"Key '{key}': translated value must not be empty."

            if original_text and len(original_text) <= 12:
                normalized_original = "".join(original_text.lower().split())
                normalized_value = "".join(
                    (value.get("native_translation") if self.is_reflect and isinstance(value, dict) else value).lower().split()
                )
                if normalized_original and normalized_original == normalized_value:
                    return False, f"Key '{key}': translation appears unchanged from the source text."

        return True, ""

    def _extract_final_translation(self, translated_dict: Dict[str, str]) -> Dict[str, str]:
        if self.is_reflect and isinstance(translated_dict, dict):
            return {
                k: f"{v.get('native_translation', v) if isinstance(v, dict) else v}"
                for k, v in translated_dict.items()
            }
        return {k: f"{v}" for k, v in translated_dict.items()}

    @staticmethod
    def _create_segments(original_segments: List[ASRDataSeg], translated_dict: Dict[str, str]) -> List[ASRDataSeg]:
        new_segments = []
        for i, seg in enumerate(original_segments, 1):
            trans_text = translated_dict.get(str(i), "")
            new_seg = ASRDataSeg(
                text=seg.text,
                start_time=seg.start_time,
                end_time=seg.end_time,
                translated_text=trans_text,
                words=list(seg.words),
            )
            new_segments.append(new_seg)
        return new_segments

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
