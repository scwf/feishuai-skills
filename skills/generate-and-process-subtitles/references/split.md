# Semantic Split

Use semantic split only when the user explicitly requests natural re-segmentation. It is available through `transcribe --semantic-split` or `split` for raw Whisper JSON with word timestamps.

```bash
{PYTHON} {SKILL_ROOT}/scripts/generate_and_process_subtitles.py split raw-whisper.json --output-dir ./subtitles
```

The model proposes `<br>` boundaries. The program verifies character order and conservation, raw segment/word timelines, positive cue duration, non-overlap, serialized SRT validity, and configured limits. English ceilings are 21 words and 79 display characters; length is a ceiling, not a reason to prefer a syntactically broken boundary.

Long inputs are processed chunk by chunk. The CLI logs `chunk N/total` before and after each request, logs every requested seam repair, and atomically checkpoints every completed main chunk under `_subtitle_work/`. Repeating the same command with the same source and split settings resumes from that checkpoint; cached cue text and timing are rebuilt from the verified word groups rather than trusted from the mutable checkpoint. The final structured result reports `checkpoint_path`, total/completed chunks, and how many chunks were resumed. Each request has an explicit total timeout (`--llm-timeout-seconds`, default 180; environment default `SUBTITLE_LLM_TIMEOUT_SECONDS`); nested client retries are disabled for this bounded call. A timeout or interruption preserves completed main chunks but does not publish a final SRT/TXT pair; seam repair is re-evaluated after resume.

Chunk seams are repaired locally without growing a repair window across later seams. The command writes digest-suffixed seam and QC artifacts under `_subtitle_work/`; consume the returned `seam_times_path` and `qc_path` rather than constructing names.

Exit `2` means `review_required`. Preserve the generated pair, inspect the exact findings against word timestamps or audio, and stop downstream work. Failed or overlapping seam repair remains blocking until an exact reviewed resolution is supplied to QC.

Do not auto-merge cues, delete apparent repetition, add punctuation, or expand a core phrase list to fit one video. When repairing a continuation, do not merge past the default 21-word / 79-character English ceilings; use word timestamps to recut at a natural clause boundary. Prefer general boundary signals plus job-level terminology context.
