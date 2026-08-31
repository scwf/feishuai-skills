# Evaluation Contract

Use these checks for meaningful Skill, prompt, QC, path, or publication changes. Judge public behavior and artifacts, not documentation wording, regex text, or function names.

## Routing

Positive cases must select the expected mode: local media transcription, YouTube confirmation then transcription, SRT normalization, conservative correction, translation/bilingual output, Whisper JSON semantic split, and SRT viewer-facing QC.

Negative cases must exclude dubbing/TTS/voice cloning, visual-only video understanding, channel metadata scraping, and publishing.

For a generic YouTube extraction request, no command may run until both semantic-split and description-assisted-optimize choices are explicit.

## Behavior Fixtures

- Normal baseline: valid local SRT normalize/QC and a mocked transcribe/translate pair.
- Agent Memory: `tests/fixtures/agent_memory_viewer_clusters.json` contains five original viewer failures and their reviewed replacements. Every original cluster must block; every reviewed cluster must pass.
- DeepSeek: `tests/fixtures/deepseek_boundaries.json` contains P01-P31 capitalization-bypassed broken boundaries plus 31 healthy controls. Every problem boundary must be detected and no healthy control may receive the capitalization-independent continuation reason.
- Semantic split: content/order conservation, cue limits, positive duration, seam isolation, and failed-seam persistence.
- Healthy short speech and natural boundaries: hash-bound AI/human reviews resolve only approvable findings, retain original reasons and identity, and fail on changed text, timing or neighbors. No review means no automatic clearance; hard failures remain unapprovable.
- Long bilingual cues: `tests/fixtures/long_bilingual_cues.json` must block under defaults, and a cue above 21 words but below 79 characters must report `overlong_word_count`.

## Deterministic Contracts

Verify:

- strict SRT numbering/timing/overlap parsing;
- raw ASR word/segment order before normalization;
- final SRT/TXT byte agreement and transactional publication;
- existing-target refusal, explicit archival replacement, and rollback after injected promotion failure;
- input/output alias rejection and safe regular single-link lock files;
- digest-suffixed, component-safe evidence/report paths;
- bounded ASCII-safe stdout and structured errors under a legacy Windows code page;
- exact source-language metadata hash and confidence;
- exit `2` propagation from nested and standalone review gates;
- wider standalone QC limits require `--allow-relaxed-limits`, while stricter limits do not; reports bind default/effective limits, authorization, and exact source SHA-256;
- targeted no-VAD repair requires interval bounds plus fixed language and never overwrites the baseline.

## Commands

```bash
python -m pytest skills/generate-and-process-subtitles/tests -q -p no:cacheprovider
python -m py_compile skills/generate-and-process-subtitles/scripts/generate_and_process_subtitles.py
python skills/generate-and-process-subtitles/scripts/generate_and_process_subtitles.py --help
python skills/generate-and-process-subtitles/scripts/generate_and_process_subtitles.py qc --help
```

Run the Skill validator with UTF-8 mode. For CLI changes, compare every documented command/option with live `--help`.

For QC changes, run the real DeepSeek source fixture when available and save the full report. The known broken source must not return zero risk. Record detection count and healthy-control results; do not claim general correctness from one video.

For publication or renderer-adjacent changes, fault-inject each promotion/rollback boundary. A green happy path alone is insufficient.

Completion requires all tests, negative cases, real CLI contracts, package validation, and an independent severity-ranked review with an explicit merge verdict.
