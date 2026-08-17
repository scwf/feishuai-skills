# Process Subtitles

Resolve `{SKILL_ROOT}` to this skill folder before running commands.

## Normalize

Normalize an existing SRT and export standard SRT/TXT without LLM calls:

```bash
python {SKILL_ROOT}/scripts/generate_and_process_subtitles.py normalize input.srt --output-dir ./subtitles
```

## Optimize

Use an LLM to correct subtitle recognition errors while preserving timing:

```bash
python {SKILL_ROOT}/scripts/generate_and_process_subtitles.py optimize input.srt --output-dir ./subtitles
```

Configure the LLM with `SUBTITLE_LLM_*` environment variables or the untracked `{SKILL_ROOT}/llm.env` file described in `references/setup.md`.

Add reference evidence with `--reference` or `--reference-file` for names, terminology evidence, source notes, or video title/channel/raw description. These options are evidence only; do not use them for task-level correction, rewrite, or style instructions.

## Translate

Translate an existing SRT:

```bash
python {SKILL_ROOT}/scripts/generate_and_process_subtitles.py translate input.srt --target-language zh-Hans --output-dir ./subtitles
```

Output format choices:

- `bilingual-trans-first`
- `bilingual-source-first`
- `translation-only`

Use `--description` or `--description-file` for reference information, terminology, translation requirements, or style guidance.

## Semantic Split

Use only when the user explicitly requests semantic segmentation or natural subtitle line breaking.

For raw Whisper JSON:

```bash
python {SKILL_ROOT}/scripts/generate_and_process_subtitles.py split raw-whisper.json --output-dir ./subtitles
```

For transcription plus split:

```bash
python {SKILL_ROOT}/scripts/generate_and_process_subtitles.py transcribe input.mp4 --semantic-split --output-dir ./subtitles
```

All process JSON stays under `_subtitle_work/`; only final `.srt` and `.txt` stay in the target directory.

Semantic split chunks the transcript for the LLM, then locally re-splits only the last cue before each chunk boundary plus the first cue after it. Prefer punctuation, original ASR segment boundaries, or pauses when cutting chunks. A repaired singleton window is not reused at the next seam; an overlapping repair window becomes a review item instead of growing across chunks. Repaired cues must also remain within configured length limits and have positive duration. `transcribe --semantic-split` and `split` validate the unreordered cue list and the serialized SRT with the same strict parser used by standalone QC before writing final SRT/TXT. Zero-duration, overlapping, reverse-timeline, or blank-line cues are a structured `invalid_srt` error and do not leave a final SRT without QC/seams. Those commands write digest-suffixed `*.semantic-orphan-qc.json` and `*.chunk-seams.json` under `_subtitle_work/`; use the exact `qc_path` and `seam_times_path` returned by the command rather than constructing names. All basename-derived work artifacts use component-length-safe names. The seams artifact contains both timestamps and any seam-repair failures. Official writers sort seam timestamps so the file always satisfies the independent QC schema, even when ASR word times are non-monotonic. If QC status is `review_required`, those commands still write SRT/TXT but exit `2`. Do not continue the pipeline.

Re-run QC, including chunk-seam timestamps when the seams file exists:

```bash
python {SKILL_ROOT}/scripts/generate_and_process_subtitles.py qc input.srt --output ./subtitles/_subtitle_work/semantic-orphan-qc.json --seam-times-file "<seam_times_path returned by split>"
```

`--output` is optional. When omitted, QC atomically writes `<input-dir>/_subtitle_work/<safe-input-stem>-<stable-digest>.semantic-orphan-qc.json` (or beside the input when it is already inside `_subtitle_work`, case-insensitively). Every default name includes the source-stem digest so sanitized names cannot collide with either another source name or the digest namespace; long UTF-8 stems are shortened to preserve path-component limits. The output path is normalized before collision checks. Standalone QC always writes a full JSON report to disk and emits only a bounded status summary to stdout.

For Chinese-above-English SRT, add `--bilingual` so the English line is inspected. Exit code `2` means `review_required`. Do not auto-merge high-risk cues. `Yes.` / `Great.` are `ok_short`.

If review confirms that a flagged short cue is a complete utterance, write an approval file with an exact, auditable match:

```json
{"approved_cues": [{"cue": 12, "text": "I agree.", "reason": "Confirmed complete in source audio."}]}
```

Then rerun `qc` with `--approved-cues-file <approvals.json>`. This can clear only short-fragment findings whose cue number and text still match; it cannot waive hanging words or lowercase continuations. Every approval entry must be consumed by an exact currently approvable cue. Unknown cue numbers, stale text, and entries targeting non-approvable findings are structured input errors rather than silently ignored metadata. Continue only when the rerun exits `0`.

If the seams artifact contains `seam_repair_failures`, standalone QC keeps the stop gate active. After manually repairing and reviewing a failed seam against the source, create an explicit resolution file:

```json
{"resolved_seams": [{"seam_index": 1, "seam_time_ms": 42000, "reason": "Merged and reviewed against source audio."}]}
```

Rerun QC with both `--seam-times-file <chunk-seams.json>` and `--resolved-seams-file <resolved-seams.json>`. Resolution entries must exactly identify failures in the seams artifact; they do not suppress any remaining content-level QC finding.
