# Translate

Translate an existing, validated SRT while preserving cue numbering and timing:

```bash
{PYTHON} {SKILL_ROOT}/scripts/generate_and_process_subtitles.py translate input.srt --target-language zh-Hans --output-dir ./subtitles
```

Choose one output format:

- `bilingual-trans-first`: translation above source; use this for Chinese-on-top delivery.
- `bilingual-source-first`: source above translation.
- `translation-only`: translated text only.

Use `--description` or `--description-file` for job-specific terminology and style requirements. Standard translation is the default. Reflective translation is a separate, higher-cost model path and must be explicitly requested; do not load or select it implicitly.

The model translates each key independently. Program validation owns key preservation, cue alignment, timing, output serialization, and pair publication. A fragment may remain a fragment; translation must not fill it from adjacent cues. In a composite bilingual-video workflow, translate only the exact reviewed source SRT that has passed final English QC.
