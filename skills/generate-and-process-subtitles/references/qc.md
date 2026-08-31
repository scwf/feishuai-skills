# Viewer-Facing QC

Run QC on the exact SRT that will move downstream:

```bash
{PYTHON} {SKILL_ROOT}/scripts/generate_and_process_subtitles.py qc input.srt
```

Add `--bilingual` to inspect the contiguous English lines in a bilingual cue. Pass the exact `--seam-times-file` returned by split when available. The full atomic report is written to disk; stdout is only a bounded status summary.

QC combines compact structural signals: hanging function words or auxiliaries, short dependent fragments, adjacent duplicate suffixes, unfinished text before a long gap, overlong English word counts, overlong display lines, unresolved seam failures, lowercase continuations, and adjacent unpunctuated continuations. Capitalizing the next cue does not turn a continuation into a new sentence. Reports include cue number, timestamps, neighbor text, gaps, severity, and reasons.

The default English ceilings are 21 words and 79 display characters. Stricter `--max-words-en` or `--max-display-chars-en` values are ordinary overrides. Any value wider than its default requires a separate explicit `--allow-relaxed-limits`; semantic-split or optimize authorization does not imply it. The JSON report records `default_limits`, `effective_limits`, `limits_relaxed_from_default`, `relaxed_limits_authorized`, and the exact input `source_sha256`.

Exit `2` / `review_required` stops downstream production, not the agent's review. Group related cues; fix clear punctuation/case errors or authorized local cuts on a copy, then rerun QC. Prefer existing context, word timings and visible evidence; check local audio only where wording or delivery remains uncertain. Do not repeat unchanged checks or send the raw QC list to the user. Preserve faithful repetitions and speaker errors rather than rewriting for fluency; escalate only unresolved material ambiguity or a user-only choice.

Natural clauses, lists and coordinated actions may span screens below the length ceiling. Review semantic completeness of each block, neighbors, timing and display load; do not hard-merge full sentences, add fake punctuation or capitalize only to silence QC. Shortness alone is not an error, and static frames do not prove dynamic readability.

Reuse `--approved-cues-file` for completed AI or human evidence review. Its `source_sha256` must equal the current input SRT hash (including timing and neighbors); identify the actual `reviewed_by` and provide an exact cue/text/reason per retained finding. For example:

```json
{
  "source_sha256": "<SHA-256 of the exact input SRT>",
  "reviewed_by": "ai:<reviewer>",
  "approved_cues": [
    {"cue": 1, "text": "So when you connect a charger,", "reason": "Complete condition followed by its main clause; checked both cue timings and display lengths."}
  ]
}
```

This can resolve ambiguous/short findings and `lowercase_continuation` / `unpunctuated_continuation`; it is not bulk permission to retain every boundary. The report preserves original reasons and reviewer identity. It cannot waive hard dependencies, hanging words, duplicate suffixes, long-gap incompleteness, overlong word counts or lines. Seam failures still require exact `resolved_seams` evidence. Missing hash/reviewer, stale text or unused approvals are errors; re-review changed context, never refresh only the hash to suppress an error.
