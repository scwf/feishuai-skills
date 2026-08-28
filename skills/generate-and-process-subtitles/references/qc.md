# Viewer-Facing QC

Run QC on the exact SRT that will move downstream:

```bash
{PYTHON} {SKILL_ROOT}/scripts/generate_and_process_subtitles.py qc input.srt
```

Add `--bilingual` to inspect the contiguous English lines in a bilingual cue. Pass the exact `--seam-times-file` returned by split when available. The full atomic report is written to disk; stdout is only a bounded status summary.

QC combines compact structural signals: hanging function words or auxiliaries, short dependent fragments, adjacent duplicate suffixes, unfinished text before a long gap, overlong English word counts, overlong display lines, unresolved seam failures, lowercase continuations, and adjacent unpunctuated continuations. Capitalizing the next cue does not turn a continuation into a new sentence. Reports include cue number, timestamps, neighbor text, gaps, severity, and reasons.

The default English ceilings are 21 words and 79 display characters. Stricter `--max-words-en` or `--max-display-chars-en` values are ordinary overrides. Any value wider than its default requires a separate explicit `--allow-relaxed-limits`; semantic-split or optimize authorization does not imply it. The JSON report records `default_limits`, `effective_limits`, `limits_relaxed_from_default`, `relaxed_limits_authorized`, and the exact input `source_sha256`.

Exit `2` / `review_required` is a hard stop. Inspect word timestamps, audio, or visible evidence before recutting or removing repetition. Do not auto-merge every short cue: complete utterances such as `Yes.` or `And there you go.` may be valid.

An exact approved-cues file can resolve only currently approvable ambiguous/short findings and must include cue, unchanged text, and review reason. It cannot waive mechanically proven dependencies, hanging words, duplicate suffixes, long-gap incompleteness, overlong word counts or lines, or capitalization-independent continuation findings. Seam failures require a separate exact `resolved_seams` entry. Stale or unused approvals are input errors.
