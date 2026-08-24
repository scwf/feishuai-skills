# Process Subtitles

Resolve `{SKILL_ROOT}` to this skill folder before running commands.

For a downstream workflow that requires a specific source language, pass `transcribe --require-language <code>`. Reusable YouTube subtitles are then restricted to that language, ASR detection must match, and the returned metadata records `source_language`, its origin, and the requirement. A mismatch is a hard stop; this flag does not invent a translation stage.

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

All process JSON stays under `_subtitle_work/`; only final `.srt` and `.txt` stay in the target directory. Every ordinary output command stages and validates both files before pair promotion, refuses existing targets by default, and accepts replacement only through `--replace-existing`, which archives the old members, returns their `archived_srt` / `archived_txt` paths, and rolls back a partial promotion.

Semantic split chunks the transcript for the LLM, then locally re-splits only the last cue before each chunk boundary plus the first cue after it. Prefer punctuation, original ASR segment boundaries, or pauses when cutting chunks. A repaired singleton window is not reused at the next seam; an overlapping repair window becomes a review item instead of growing across chunks. Repaired cues and final LLM results must remain within configured length limits and have positive duration; retry exhaustion never waives a limit. All length, chunk, and retry controls must be positive integers. English cues are limited to 21 words and 79 display characters; 80 characters wrap on 1080p at FontSize 16. `transcribe --semantic-split` and `split` validate raw Whisper segment and word order before any sorting, then validate the serialized SRT with the same strict parser used by standalone QC before writing final SRT/TXT. Zero-duration, overlapping, reverse-timeline, or blank-line cues are a structured `invalid_srt` error and do not leave a final SRT without QC/seams. Those commands write digest-suffixed `*.semantic-orphan-qc.json` and `*.chunk-seams.json` under `_subtitle_work/`; use the exact `qc_path` and `seam_times_path` returned by the command rather than constructing names. All basename-derived work artifacts use component-length-safe names. The seams artifact contains both timestamps and any seam-repair failures. Official writers sort seam timestamps so the file always satisfies the independent QC schema after the source timeline has passed validation. If QC status is `review_required`, those commands still write SRT/TXT but exit `2`. Do not continue the pipeline.

Re-run QC, including chunk-seam timestamps when the seams file exists:

```bash
python {SKILL_ROOT}/scripts/generate_and_process_subtitles.py qc input.srt --output ./subtitles/_subtitle_work/semantic-orphan-qc.json --seam-times-file "<seam_times_path returned by split>"
```

`--output` is optional. When omitted, QC atomically writes `<input-dir>/_subtitle_work/<safe-input-stem>-<stable-digest>.semantic-orphan-qc.json` (or beside the input when it is already inside `_subtitle_work`, case-insensitively). Every default name includes the source-stem digest so sanitized names cannot collide with either another source name or the digest namespace; long UTF-8 stems are shortened to preserve path-component limits. The output path is normalized before collision checks. Standalone QC always writes a full JSON report to disk and emits only a bounded status summary to stdout.

For Chinese-above-English SRT, add `--bilingual` so the English line is inspected. Exit code `2` means `review_required`. Viewer-facing findings include non-approvable `short_dependent_fragment` only when a bounded local subject/modal/complement, perfect-progressive, control-gerund, or contracted-auxiliary structure mechanically requires the one-second-or-shorter tail. Ambiguous wh/gerund attachments use `ambiguous_short_dependent_fragment`; they remain a stop gate until checked against word timestamps/audio, but an exact evidence-backed approved-cues entry may resolve them. A recognized independent `To …,` discourse marker wins over ambiguous predecessor evidence, while mechanically proven predecessor evidence still wins. Other findings include `adjacent_duplicate_suffix` for a repeated 2-6-word suffix lasting up to 1.5 seconds, and `incomplete_before_long_gap` for an unfinished modifier phrase such as `a bunch of different.`, `many other.`, or any `… of other.` phrase before a pause of at least 1.5 seconds even if terminal punctuation or a bounded trailing filler such as `you know` was added. Legal pronominal forms such as `than any other` and `like any other` are not incomplete. Reports include both neighboring cue texts, human-readable timestamps, and before/after gaps. Do not auto-merge high-risk cues or remove detected repetition until source word timestamps/audio show whether it was spoken. Do not merge a lowercase continuation after a cue already at the 21-word or 79-character English budget; recut hanging or overlong English instead. A cue ending in an unfinished auxiliary contraction such as `we're`, `we'll`, or `we've` is also high risk even when the next cue was capitalized by segmentation. `Yes.` / `Great.` are `ok_short`; explicitly recognized complete short sentences or discourse markers such as `And there you go.`, `To be clear, yes.`, `To clarify, no.`, and `To the moon!` are not dependent fragments merely because they are brief when the predecessor does not mechanically require a complement.

If review confirms that a flagged short cue is a complete utterance, write an approval file with an exact, auditable match:

```json
{"approved_cues": [{"cue": 12, "text": "I agree.", "reason": "Confirmed complete in source audio."}]}
```

Then rerun `qc` with `--approved-cues-file <approvals.json>`. This can clear only short-fragment findings whose cue number and text still match; it cannot waive hanging words, lowercase continuations, or overlong display lines. Every approval entry must be consumed by an exact currently approvable cue. Unknown cue numbers, stale text, and entries targeting non-approvable findings are structured input errors rather than silently ignored metadata. Continue only when the rerun exits `0`.

If the seams artifact contains `seam_repair_failures`, standalone QC keeps the stop gate active. After manually repairing and reviewing a failed seam against the source, create an explicit resolution file:

```json
{"resolved_seams": [{"seam_index": 1, "seam_time_ms": 42000, "reason": "Merged and reviewed against source audio."}]}
```

Rerun QC with both `--seam-times-file <chunk-seams.json>` and `--resolved-seams-file <resolved-seams.json>`. Resolution entries must exactly identify failures in the seams artifact; they do not suppress any remaining content-level QC finding.
