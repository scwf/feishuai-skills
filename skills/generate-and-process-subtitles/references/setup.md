# Setup

Resolve `{SKILL_ROOT}` to this skill folder before running commands.

Prefer `uv` to create a per-skill virtual environment at `{SKILL_ROOT}/.venv` so this skill's dependencies do not pollute the user's global Python environment. If the host agent provides an isolated Python runtime, use that runtime instead.

Create and install once on macOS/Linux:

```bash
uv venv {SKILL_ROOT}/.venv
uv pip install --python {SKILL_ROOT}/.venv/bin/python -r {SKILL_ROOT}/requirements.txt
```

On Windows:

```bash
uv venv {SKILL_ROOT}\.venv
uv pip install --python {SKILL_ROOT}\.venv\Scripts\python.exe -r {SKILL_ROOT}\requirements.txt
```

If `uv` is unavailable, fall back to `python -m venv` and install dependencies with the venv's `python -m pip`.

Run later commands with the same venv Python: `{SKILL_ROOT}/.venv/bin/python` on macOS/Linux or `{SKILL_ROOT}\.venv\Scripts\python.exe` on Windows.

Optional Windows GPU setup:

```bash
uv pip install --python {SKILL_ROOT}\.venv\Scripts\python.exe -r {SKILL_ROOT}\requirements-windows-gpu.txt
```

Use this only when CTranslate2 GPU inference on Windows cannot find CUDA 12 runtime DLLs such as `cublas64_12.dll`. The ASR code automatically registers those package DLL directories when they exist; other platforms and CPU-only runs do not need this file.

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
