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
- Targeted recovery requires interval bounds, fixed language, and `--no-vad` together; passes both bounds to faster-whisper; writes distinct component-safe interval outputs through short target-independent temporary names; validates both files before promotion; uses same-directory atomic rename with TXT first and SRT last as the completion marker; reports incomplete rollback instead of swallowing a persistent final-file lock; and refuses existing repair outputs without changing the baseline.
- Every ordinary SRT/TXT producer also stages and validates the pair, refuses existing targets without `--replace-existing`, archives existing members before authorized replacement, rejects input/output aliases, and restores the old pair after a failed promotion.
- Semantic split rejoins a chunk-boundary `our` / `customers.` fragment, keeps a legal `Yes.` unmerged, does not drop a trailing `And` or `the`, prevents singleton repair windows from cascading across later chunks, enforces cue-length limits after retry exhaustion and positive duration on repaired windows, rejects English segments over the 79-character display budget, rejects non-positive limit/chunk/retry controls, validates raw Whisper order before sorting, and converts any failed or overlapping seam repair into a structured high-risk QC item.
- Semantic split recognizes ASCII and CJK sentence-ending punctuation plus Unicode closing quotes, and checks the first content character after opening quotes before accepting a clean seam.
- `qc` flags `customers.`, unlisted short CJK fragments, quoted or bracketed lowercase continuations, CJK function fragments, short-cue lowercase continuations, hanging `our` even at 21 words, unfinished auxiliary contractions such as `we're`, mechanically proven one-second-or-shorter dependent tails (`...are going` + `To be stored.`, `Teams need` / `She will need` / `We still hope` / `They may try` / `We are hoping` / `They have been hoping` / `She keeps trying` + `To be ready.`, including bounded filler variants), ambiguous wh/gerund attachments as a separately approvable review reason, adjacent 2-6-word duplicate suffixes lasting up to 1.5 seconds, structurally unfinished modifiers such as `a bunch of different.`, `many other.`, or any `… of other.` phrase before subtitle gaps of at least 1.5 seconds, and English lines longer than 79 display characters (`overlong_display_line`) as `review_required`; includes timestamps, neighboring cue text, and gap duration in findings; does not flag `And there you go.`, `So how is it going` + `To clarify, no.`, object-complete `That is all we need` + a discourse marker, non-agent `The situation has been trying` + a discourse marker, existential `There are several plans` + a discourse marker, `than any other`, `like any other`, `To the moon!`, complete predicative/pronominal sentences, or a lowercase continuation after an unpunctuated cue already at the 21-word or 79-character budget; classifies only deterministic short utterances such as `Yes.` and `好。` as `ok_short`; rejects malformed, non-sequential, reverse-timeline, zero-duration, or overlapping SRT cues; and checks all contiguous English source lines in bilingual cues.
- Exact reviewed short-cue approvals require a positive non-boolean integer cue plus exact text and reason; every entry must be consumed by a currently approvable finding; stale, mismatched, unknown, or non-approvable entries are rejected; approvals cannot waive hanging words, lowercase continuations, or overlong display lines.
- Normalized QC report paths cannot alias an input, including Windows device-prefix, case, trailing-dot/space, and noncanonical directory aliases; standalone and nested QC/work artifacts always atomically write to deterministic, universally digest-suffixed, component-length-safe paths; atomic temporary names remain short and target-independent, with bounded retries for transient Windows replace conflicts; seam JSON uses a strict sorted non-negative integer schema, official writers sort non-monotonic ASR seam times before persisting, and the artifact persists repair failures; standalone QC inherits those failures until exact reviewed resolutions are supplied; all QC stdout contains only a bounded summary and closed pipes cannot alter the post-write exit contract; argument errors emit structured JSON with exit `1`; `transcribe --semantic-split` / `split` validate the unreordered cue list and the serialized SRT round-trip before writing final files, convert nested parse or reverse-timeline failures to structured `invalid_srt` / exit `1` without leaving SRT-without-QC half-finished artifacts, and exit `2` when nested QC is `review_required`.
- Fault-inject TXT/SRT promotion: temporary-pair validation occurs exactly once before commit, no fallible validation runs after SRT promotion, and a failed publication restores pre-existing content-addressed work evidence while removing only artifacts newly created by that failed transaction.
