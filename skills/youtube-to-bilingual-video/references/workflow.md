# Workflow And Recovery

## Job Layout

When the user does not supply a directory, run:

```bash
python "{COMPOSITE_SKILL_ROOT}/scripts/resolve_job_dir.py" --root "<cwd>" --title "<title>" --video-id "<video-id>"
```

Reuse the returned manifest-backed directory on retry. Do not create a second title-based job for the same video or follow symlink/junction escapes.
The default returned layout is `<cwd>/<safe-title>-<video-id>-<id-digest>/`.

```text
<job-dir>/
  source/                  media and download sidecar
  subtitles/
    transcribed/           atomic output plus _subtitle_work/
    baseline/              immutable source copy
    optimized/             optional candidate
    reviewed/              evidence-reviewed English
    bilingual/             Chinese-above-English pair
  audit/                   lexical, metadata, QC, validation reports
  render/
    final.zh-en.mp4
    render-report.json
    qa/
  notes/                   review evidence
```

Never edit the baseline in place.

## Audit And Review

After optional optimize, compare baseline and candidate:

```bash
python "{COMPOSITE_SKILL_ROOT}/scripts/audit_subtitle_changes.py"   "<baseline.srt>" "<candidate.srt>"   --output "<job-dir>/audit/optimize-changes.json"
```

Exit `0` means only allowed non-lexical changes. Exit `2` requires evidence review. Exit `1` means the inputs or structure are invalid.

For every lexical item, prefer evidence in this order:

1. visible text at the exact cue timestamp;
2. official title, description, or supplied source notes;
3. source audio.

Keep uncertain text unchanged or ask the user. Do not accept a plausible term merely because it appears in the description. Preserve a reviewed English copy and the audit trail from baseline to that exact file.

Rerun the atomic final-English QC after all manual changes. Punctuation or case changes can create a new orphan, so carry forward only still-valid seam and approval artifacts. Translate only after the exact downstream English SRT returns QC exit code `0`.

## Bind And Validate

If reviewed English bytes differ from transcription output, bind the exact final source through the full audit lineage:

```bash
python "{COMPOSITE_SKILL_ROOT}/scripts/bind_reviewed_source_metadata.py"   --source-srt "<reviewed.en.srt>"   --upstream-metadata "<transcription-metadata.json>"   --audit-report "<audit-1.json>"   --reviewed-by "<reviewer>" --review-note "<evidence>"   --accept-reviewed-changes   --output "<job-dir>/audit/reviewed-source.metadata.json"
```

Repeat `--audit-report` in byte-hash order when there are multiple stages. `--accept-reviewed-changes` records completed human review; it is never an automatic bypass.

Validate bilingual structure and media coverage:

```bash
python "{COMPOSITE_SKILL_ROOT}/scripts/validate_bilingual_srt.py"   "<bilingual.srt>" --source-srt "<reviewed.en.srt>"   --source-metadata "<exact-source-metadata.json>"   --source-qc-report "<job-dir>/audit/final-english-qc.json"   --video "<source-video>"   --output "<job-dir>/audit/bilingual-validation.json"
```

The validator must confirm exact English text/timing parity, sequential cues, Chinese-first ordering, language evidence, metadata hash, final-English QC hash and limit evidence, non-overlap, and material head/tail coverage. It records each cue's verified source-English line count so rendering never guesses the language boundary from character types. A result with `coverage_checked=false` is not render-ready. Do not widen coverage tolerances until the gap is confirmed silent; repair confirmed missing speech in the English source first.

Run atomic `qc --bilingual` on the same bilingual file and require exit `0`.

## Render And Inspect

```bash
python "{COMPOSITE_SKILL_ROOT}/scripts/render_bilingual_video.py"   --input-video "<source-video>"   --subtitle "<bilingual.srt>"   --validation-report "<job-dir>/audit/bilingual-validation.json"   --output "<job-dir>/render/final.zh-en.mp4"   --work-dir "<job-dir>/render"   --margin-v 8
```

Defaults keep Chinese above English, bottom-center, FontSize 16, width-filling automatic wrapping, explicit horizontal margins, H.264/AAC, and adaptive CJK font selection. The delivered bilingual SRT is immutable: the renderer writes a digest-named layout SRT under `render/layout/`, removes hard breaks within each language, and preserves only the Chinese/English separator. Override style only for a user requirement or confirmed QA problem.

The renderer rejects a missing, stale, coverage-incomplete, or hash-mismatched validation report; serializes normalized output aliases; encodes to a unique partial; verifies streams and duration; performs a full decode; and only then promotes. QA includes ordinary start/middle/end frames, every user time, and the midpoint of the Top 5 cues by deterministic bilingual display load. The report records cue, selection reason, load and estimated line metrics, layout hash, wrap style, margins, and Unicode-wrap support. `--replace-existing` archives and transactionally replaces an old result. Use `--allow-silent` only after explicit acceptance.

Inspect every high-load frame plus at least one ordinary frame and every terminology, coverage, or boundary repair timestamp. `qa_review_required=true` means the MP4 is not yet deliverable even though deterministic render verification passed. If estimated Chinese or English lines exceed 2, or the total exceeds 4, the renderer returns `review_required` / exit `2`, records the affected cues, and keeps the verified MP4 under `render/review/` without creating or replacing the requested final output. Decode success does not prove subtitle readability.

## Manual Revision Loop

After any subtitle edit:

1. keep all immutable evidence;
2. update reviewed English first;
3. rerun English QC;
4. regenerate aligned bilingual subtitles;
5. rebind source metadata and rerun deterministic validation plus bilingual QC;
6. rerender with recoverable replacement;
7. inspect a QA frame at every edited cluster.

## Recovery

- Timeout: inspect live process, reports, partials, and completed stage artifacts; resume instead of deleting or redownloading.
- Download error: require a coherent media/sidecar pair before transcription.
- Missing description: skip optimize unless other evidence is supplied.
- Audit or QC exit `2`: stop, review evidence, update the reviewed English copy, and rerun the same gate.
- Translation error: retain reviewed English and retry only translation.
- Validation error: repair from reviewed English; never patch only Chinese or widen limits to hide missing speech.
- Missing source audio: ask whether silent delivery is acceptable.
- Render/QA error: retain source and subtitles; a partial or visually unreadable MP4 is not deliverable.

## Final Report

Return absolute paths for source and sidecar, immutable baseline, reviewed English, bilingual SRT, audit/metadata/QC/validation reports, final MP4, render report, QA frames, and unresolved warnings.
