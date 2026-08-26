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

Faster-whisper can emit words that collapse to zero duration after millisecond quantization. These events may accumulate on long media even when they are sparse per word. For an isolated word, the adapter first uses a proven adjacent gap for a 1 ms interval. A multi-word cluster at one timestamp is planned as a unit: it consumes only the required milliseconds from the cluster's outer gaps first, then may borrow any remainder from an adjacent positive-duration word in the same segment while leaving that donor at least 20 ms long. It never crosses segment boundaries or repairs reverse timestamps.

Every changed zero-duration word and donor adjustment is recorded in raw ASR JSON under `timestamp_repairs`. `timestamp_repair_summary` reports gap repairs, packed clusters, repaired words, donor adjustments, borrowed milliseconds, safety limits, and whether a large repaired cluster merits review. The defaults allow at most 50 packed-word repairs per 10,000 ASR words and a maximum contiguous run of 4 zero-duration words, measured by original word order before any gap repair even when their timestamps are staggered; short inputs receive enough allowance for one maximum-size run. Console cluster samples contain only bounded token excerpts, while the complete evidence remains in hash-bound raw ASR JSON. Override limits only after inspecting that raw alignment:

```bash
--max-packed-word-repairs-per-10k 50
--max-packed-cluster-size 4
```

The corresponding environment variables are `SUBTITLE_MAX_PACKED_WORD_REPAIRS_PER_10K` and `SUBTITLE_MAX_PACKED_CLUSTER_SIZE`. Exceeding a limit, lacking a safe donor, or finding a contiguous zero-duration run whose original timestamps move backward remains a hard stop before any timestamp is changed. The structured error includes the raw ASR JSON path, SHA-256, bounded diagnostic samples, and repair summary; the unchanged strict timeline validator still runs after every successful repair.

## Targeted Missing-Speech Recovery

Audible speech with no source cue is a transcription coverage failure. Preserve the current SRT, confirm the affected interval against the media, and rerun only that interval:

```bash
{PYTHON} {SKILL_ROOT}/scripts/generate_and_process_subtitles.py transcribe "<local-media>" \
  --output-dir "<repair-dir>" --language en \
  --start-seconds 120.0 --end-seconds 128.0 --no-vad
```

Both bounds, a fixed language, and `--no-vad` are required together; global no-VAD transcription is rejected. Prefer the already downloaded local source. Returned word/cue timestamps remain on the original media timeline.

Review the interval output against adjacent cues. Reject boundary duplication, filler-only fragments, hallucination, and garbling. Merge only verified missing speech into a copy of the baseline, then renumber and rerun structural and viewer-facing QC. If bilingual subtitles exist, repair the source-language cue first and translate the verified addition.
