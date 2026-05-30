# Setup

Use a regular Python environment on Windows, macOS, or Linux.
Resolve `{SKILL_ROOT}` to this skill folder before running commands.

```bash
python -m pip install -r {SKILL_ROOT}/requirements.txt
```

For media decoding and URL downloads, make sure `ffmpeg` is available on `PATH`. `yt-dlp` uses it for extracting audio from video URLs.

ASR defaults:

- Model: `large-v2`
- Device: `auto`
- Compute type: `auto`
- Fallback: `cpu/int8` if the requested device cannot load the model

Model download and cache behavior:

- First ASR use may download the selected `faster-whisper` model.
- Models use the system Hugging Face cache, not the subtitle output directory and not `_subtitle_work/`.
- Repeated runs reuse the cached model files.
- Advanced users can control the Hugging Face cache outside this skill with standard environment variables such as `HF_HOME`, `HF_HUB_CACHE`, or `HF_HUB_OFFLINE=1`.

LLM features require an OpenAI-compatible endpoint:

- `SUBTITLE_LLM_API_KEY`
- Optional `SUBTITLE_LLM_BASE_URL`, defaulting to `https://api.deepseek.com/v1`
- Optional `SUBTITLE_LLM_MODEL`, defaulting to `deepseek-chat`

Do not configure WSL, Windows Faster-Whisper-XXL, dubbing backends, TTS engines, or voice-cloning assets for this skill.
