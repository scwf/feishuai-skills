from __future__ import annotations

import os
from typing import Optional, Union

from .asr.factory import create_asr
from .config import DEFAULT_LLM_MODEL, DEFAULT_MODEL_NAME, TranscribeConfig
from .data import ASRData
from .downloader import download_audio
from .split import split_subtitle
from .utils import setup_logger


logger = setup_logger("generate-and-process-subtitles")


def process_media(
    media_url_or_path: str,
    output_dir: str,
    *,
    model_name: str = DEFAULT_MODEL_NAME,
    device: str = "auto",
    compute_type: str = "auto",
    language: Optional[str] = None,
    vad_filter: bool = True,
    clip_timestamps: Optional[list[float]] = None,
    split_enabled: bool = False,
    split_model: Optional[str] = None,
    split_max_chars_cjk: int = 25,
    split_max_words_en: int = 21,
    split_chunk_word_limit: int = 350,
    split_max_retries: int = 2,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
) -> ASRData:
    if os.path.exists(media_url_or_path):
        audio_path = media_url_or_path
    else:
        audio_path = download_audio(media_url_or_path, output_dir)
        if not audio_path:
            raise RuntimeError(f"Failed to download audio from {media_url_or_path}")

    config = TranscribeConfig(
        model_name=model_name,
        language=language,
        device=device,
        compute_type=compute_type,
        output_dir=output_dir,
        vad_filter=vad_filter,
        clip_timestamps=clip_timestamps,
        split_enabled=split_enabled,
        split_model=split_model,
        split_max_chars_cjk=split_max_chars_cjk,
        split_max_words_en=split_max_words_en,
        split_chunk_word_limit=split_chunk_word_limit,
        split_max_retries=split_max_retries,
        api_key=api_key,
        base_url=base_url,
    )

    asr = create_asr(audio_path, config)
    asr_data = asr.run(callback=lambda progress, _message: logger.info("Progress: %s%%", progress))

    if split_enabled:
        asr_data = split_subtitle(
            asr_data,
            model=split_model or DEFAULT_LLM_MODEL,
            api_key=api_key,
            base_url=base_url,
            max_word_count_cjk=split_max_chars_cjk,
            max_word_count_english=split_max_words_en,
            chunk_word_limit=split_chunk_word_limit,
            max_retries=split_max_retries,
        )

    return asr_data


def optimize_subtitle(
    subtitle_data: Union[str, ASRData],
    model: str = DEFAULT_LLM_MODEL,
    custom_prompt: str = "",
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    thread_num: int = 5,
    batch_num: int = 10,
) -> ASRData:
    from .optimize import SubtitleOptimizer

    optimizer = SubtitleOptimizer(
        thread_num=thread_num,
        batch_num=batch_num,
        model=model,
        custom_prompt=custom_prompt,
        api_key=api_key,
        base_url=base_url,
    )
    return optimizer.optimize_subtitle(subtitle_data)


def translate_subtitle(
    subtitle_data: Union[str, ASRData],
    target_language: str,
    is_reflect: bool = False,
    model: str = DEFAULT_LLM_MODEL,
    custom_prompt: str = "",
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    thread_num: int = 5,
    batch_num: int = 10,
) -> ASRData:
    from .translate import SubtitleTranslator

    translator = SubtitleTranslator(
        thread_num=thread_num,
        batch_num=batch_num,
        model=model,
        custom_prompt=custom_prompt,
        target_language=target_language,
        is_reflect=is_reflect,
        api_key=api_key,
        base_url=base_url,
    )
    return translator.translate_subtitle(subtitle_data)
