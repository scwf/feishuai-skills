# Transcribe

Use `transcribe` for local audio/video and supported media URLs:

```bash
{PYTHON} {SKILL_ROOT}/scripts/generate_and_process_subtitles.py transcribe "<input>" --output-dir "<target-dir>"
```

The default final outputs are `<base>.srt` and `<base>.txt`. Read [output-contract.md](output-contract.md) for publication and evidence placement.

## Source Selection

YouTube human subtitles are reused when available. Pass `--force-asr` only when the user explicitly wants ASR. A confirmed `--semantic-split` also uses ASR because seam repair requires word timestamps; read [split.md](split.md).

Use `--require-language <code>` when a downstream workflow requires a verified source language. A reusable track must match that language, and ASR detection must match with sufficient confidence. Mismatch is a hard stop. The returned metadata binds language evidence to the exact emitted SRT.

For YouTube, metadata includes title, channel, and description. When description text exists, the command writes an immutable `_subtitle_work/context-<video-id>-<digest>.txt` and records its SHA-256 for an optional, separately confirmed optimize step. Transcribe never applies that context automatically.

Useful ASR controls include `--model`, `--device`, `--compute-type`, and `--language`. Defaults and optional Windows GPU setup are in [setup.md](setup.md).

Faster-whisper can rarely emit a word whose start and end timestamps are identical. When there is a proven non-overlapping gap immediately beside that word, the adapter assigns only a 1 ms bounded interval and records the original timestamps, repaired timestamps, token, indices, and method in raw ASR JSON under `timestamp_repairs`. If no safe adjacent interval exists, strict timeline validation still stops the run; the program never shifts neighboring words or silently drops the token.

## Targeted Missing-Speech Recovery

Audible speech with no source cue is a transcription coverage failure. Preserve the current SRT, confirm the affected interval against the media, and rerun only that interval:

```bash
{PYTHON} {SKILL_ROOT}/scripts/generate_and_process_subtitles.py transcribe "<local-media>" \
  --output-dir "<repair-dir>" --language en \
  --start-seconds 120.0 --end-seconds 128.0 --no-vad
```

Both bounds, a fixed language, and `--no-vad` are required together; global no-VAD transcription is rejected. Prefer the already downloaded local source. Returned word/cue timestamps remain on the original media timeline.

Review the interval output against adjacent cues. Reject boundary duplication, filler-only fragments, hallucination, and garbling. Merge only verified missing speech into a copy of the baseline, then renumber and rerun structural and viewer-facing QC. If bilingual subtitles exist, repair the source-language cue first and translate the verified addition.
