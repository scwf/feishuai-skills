# Workflow And Recovery

## Job Layout

Use a stable, user-visible job directory. A recommended layout is:

```text
<job-dir>/
  source/                  downloaded source and .download.json
  subtitles/
    transcribed/           first final SRT/TXT plus _subtitle_work/
    baseline/              immutable copy used for audits
    optimized/             optional optimize result
    reviewed/              audited English SRT
    bilingual/             Chinese-English SRT/TXT
  audit/
    optimize-changes.json
    bilingual-validation.json
  render/
    final.zh-en.mp4
    render-report.json
    qa/
  notes/
    terminology-review.md
```

Never edit the baseline in place. Copy the chosen transcription SRT to `baseline/` before optimization.

## Optimization Audit

Run:

```bash
python "{COMPOSITE_SKILL_ROOT}/scripts/audit_subtitle_changes.py" \
  "<baseline.srt>" "<optimized.srt>" \
  --output "<job-dir>/audit/optimize-changes.json"
```

The audit compares cue structure and normalized lexical tokens:

- punctuation, spacing, and capitalization-only changes are safe for automatic continuation;
- lexical insertion, deletion, or replacement requires review;
- cue-count, numbering, or timestamp changes are structural failures unless a previously approved segmentation step explains them.

For each flagged cue, extract frames near the cue midpoint:

```bash
ffmpeg -ss <seconds> -i "<source-video>" -frames:v 1 "<job-dir>/render/qa/term-<cue-id>.png"
```

Inspect the frame directly. If no visible evidence exists, consult official description evidence and audio. Keep unresolved terms unchanged or ask the user; do not guess.

## Bilingual Validation

Run:

```bash
python "{COMPOSITE_SKILL_ROOT}/scripts/validate_bilingual_srt.py" \
  "<bilingual.srt>" --source-srt "<audited-english.srt>" \
  --video "<source-video>" \
  --output "<job-dir>/audit/bilingual-validation.json"
```

Always pass `--video` (or `--duration`) so head/tail coverage is checked. The validator reports `coverage_checked=false` when duration is missing; that result is not render-ready. It checks source cue/timing parity, cue numbering, overlap, language order, empty text, and material video head/tail coverage. Its default head/tail limit is the larger of 30 seconds or 10% of video duration; override either limit only when verified silent intro/outro content explains the gap. Mixed product names are allowed when the first line is measurably more Chinese-dominant than the final line.

## Rendering

Render with conservative bottom placement:

```bash
python "{COMPOSITE_SKILL_ROOT}/scripts/render_bilingual_video.py" \
  --input-video "<source-video>" \
  --subtitle "<bilingual.srt>" \
  --output "<job-dir>/render/final.zh-en.mp4" \
  --work-dir "<job-dir>/render" \
  --margin-v 8
```

Useful overrides:

- `--font-name "<installed CJK font>"`
- `--font-size 18` for larger mobile-friendly subtitles
- `--margin-v 4` to move closer to the bottom, while checking clipping
- `--encoder libx264` for deterministic CPU encoding
- `--qa-time 30.5 --qa-time 120.0` for known terminology cues
- `--replace-existing` only when replacing a prior output is intentional
- `--allow-silent` only after the user explicitly accepts a silent final video

The renderer writes a partial file first, verifies streams and duration, performs a full decode scan, extracts QA frames, archives an existing output when replacement was authorized, and then promotes the verified file.

## Recovery Rules

- **Download failure:** read the downloader's structured sidecar/error; do not begin transcription on an unknown source.
- **No description context:** skip optimize and report why, unless the user supplies another evidence file.
- **Audit exit 2:** pause, inspect evidence, create a reviewed SRT, and rerun the audit from baseline to reviewed.
- **Translation failure:** retain the audited English SRT and retry only translation.
- **Validation failure (structure/order):** numbering, overlap, language order, empty text, or source cue/timing mismatch: fix the bilingual SRT from the audited English source; do not start rendering; do not widen gap limits.
- **Validation failure (head/tail coverage):** `video_head_coverage_gap` / `video_tail_coverage_gap`: do not invent bilingual cues. Listen to the gap. If it is verified silent intro/outro, ask before widening `--max-head-gap-seconds` or `--max-tail-gap-seconds`. If it contains speech the source SRT never captured, repair the audited English source first with `generate-and-process-subtitles` targeted interval re-transcription (`--start-seconds`, `--end-seconds`, `--language`, and `--no-vad` together), then translate the added cues and re-validate.
- **Render failure (no audio):** stop and ask whether a silent final video is acceptable. Retry with `--allow-silent` only after explicit acceptance. Do not add the flag on your own.
- **Render failure:** retain the source and subtitles. A `.partial.mp4` is not deliverable.
- **QA failure:** adjust style and rerender; do not claim completion because media decoding succeeded.

## Final Report

Report absolute paths for:

1. source video and download sidecar;
2. baseline and audited English SRT;
3. bilingual SRT;
4. optimization audit and bilingual validation reports;
5. final MP4, render report, and QA frames;
6. unresolved terminology or style warnings.
