# Evaluation

Use these checks before publishing meaningful changes.

## Positive Triggers

- "Generate subtitles for this local mp4" -> use `transcribe`.
- "Extract subtitles from this YouTube video" -> ask the YouTube Confirmation Gate questions before running commands: semantic split during transcription, then description-reference-assisted correction after transcription.
- "Normalize this SRT and export TXT" -> use `normalize`.
- "Translate this SRT to zh-Hans and keep bilingual subtitles" -> use `translate`.
- "Re-cut this Whisper JSON into natural subtitle segments" -> use `split`.
- "Check this SRT for orphan subtitle fragments" -> use `qc`.

## Negative Triggers

- "Dub this video", "clone this voice", or "generate TTS" -> do not use this skill.
- "Summarize the visual content of this video" -> do not use this skill.

## Output Checks

- Only final `.srt` and `.txt` files are directly under the target output directory.
- Downloads, ASR JSON, metadata, cached subtitles, and LLM intermediate data are under `_subtitle_work/`.
- Faster-whisper model files are outside the target output directory because they use the system Hugging Face cache.
- Invalid local paths fail with structured JSON before creating `_subtitle_work/`.
- Targeted recovery requires interval bounds, fixed language, and `--no-vad` together; passes both bounds to faster-whisper; writes distinct interval-named outputs atomically; and refuses existing repair outputs without changing the baseline.
- Semantic split rejoins a chunk-boundary `our` / `customers.` fragment, keeps a legal `Yes.` unmerged, does not drop a trailing `And` or `the`, prevents singleton repair windows from cascading across later chunks, enforces cue-length limits and positive duration on repaired windows, and converts any failed or overlapping seam repair into a structured high-risk QC item.
- Semantic split recognizes ASCII and CJK sentence-ending punctuation plus Unicode closing quotes, and checks the first content character after opening quotes before accepting a clean seam.
- `qc` flags `customers.`, unlisted short CJK fragments, quoted or bracketed lowercase continuations, CJK function fragments, long-cue lowercase continuations, and hanging `our` as `review_required`; classifies only deterministic short utterances such as `Yes.` and `好。` as `ok_short`; does not flag complete preposition endings or uppercase labels; rejects malformed, non-sequential, reverse-timeline, zero-duration, or overlapping SRT cues; and checks all contiguous English source lines in bilingual cues.
- Exact reviewed short-cue approvals require a positive non-boolean integer cue plus exact text and reason; every entry must be consumed by a currently approvable finding; stale, mismatched, unknown, or non-approvable entries are rejected; approvals cannot waive hanging words or lowercase continuations.
- Normalized QC report paths cannot alias an input, including through noncanonical directory paths; standalone and nested QC/work artifacts always atomically write to deterministic, universally digest-suffixed, component-length-safe paths; atomic temporary names remain short and target-independent, with bounded retries for transient Windows replace conflicts; seam JSON uses a strict sorted non-negative integer schema, official writers sort non-monotonic ASR seam times before persisting, and the artifact persists repair failures; standalone QC inherits those failures until exact reviewed resolutions are supplied; all QC stdout contains only a bounded summary and closed pipes cannot alter the post-write exit contract; argument errors emit structured JSON with exit `1`; `transcribe --semantic-split` / `split` validate the unreordered cue list and the serialized SRT round-trip before writing final files, convert nested parse or reverse-timeline failures to structured `invalid_srt` / exit `1` without leaving SRT-without-QC half-finished artifacts, and exit `2` when nested QC is `review_required`.
