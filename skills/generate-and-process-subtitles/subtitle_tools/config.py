from dataclasses import dataclass
from typing import Optional


DEFAULT_MODEL_NAME = "large-v2"
DEFAULT_WORK_DIR_NAME = "_subtitle_work"
DEFAULT_LLM_BASE_URL = "https://api.deepseek.com/v1"
DEFAULT_LLM_MODEL = "deepseek-chat"


@dataclass
class TranscribeConfig:
    """Cross-platform faster-whisper transcription configuration."""

    model_name: str = DEFAULT_MODEL_NAME
    language: Optional[str] = None
    device: str = "auto"
    compute_type: str = "auto"
    output_dir: Optional[str] = None
    vad_filter: bool = True
    vad_threshold: float = 0.5
    prompt: Optional[str] = None
    split_enabled: bool = False
    split_model: Optional[str] = None
    split_max_chars_cjk: int = 25
    split_max_words_en: int = 21
    split_chunk_word_limit: int = 350
    split_max_retries: int = 2
    api_key: Optional[str] = None
    base_url: Optional[str] = None
