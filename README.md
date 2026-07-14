# feishuai-skills

A collection of reusable agent skills for common research, scraping, and engineering workflows.

## Structure

All skills live under [`skills/`](./skills).

## Skill Catalog

| Skill | What It Does | Use It When | Key Outputs / Notes |
| --- | --- | --- | --- |
| `agent-skill-collection-evaluator` | Evaluates existing third-party Agent skills and decides whether they are worth collecting. | You want to assess a skill from a GitHub repository, industry report, article, link, or raw note before adding it to a personal Markdown skill library. | Produces a concise Chinese evaluation card and uses a bundled append script to add confirmed recommendations without overwriting existing library entries. |
| `infographic-prompt-builder` | Builds high-quality Chinese insight infographic prompts from a topic or reference materials. | You need an executive-readable image prompt for product strategy, Data & AI analysis, technical architecture, model briefs, benchmarks, industry insights, or product deep dives. | Documentation-first, tool-neutral prompt-building skill. Guides research extraction, core insight selection, infographic logic, and final Chinese prompt generation. |
| `infographic-to-editable-ppt` | Recreates a static infographic as a one-page editable PowerPoint slide. | You need to convert a PNG/JPG infographic, screenshot, poster-like analysis graphic, or chart-heavy one-pager into an editable `.pptx` with native text and shapes where practical. | Requires a rendered preview check and a short editability report covering PPT text, shapes/connectors, SVG, image slices, and visual approximations. |
| `slide-infographic-reviewer` | Reviews an existing one-page PPT slide, infographic, generation prompt, or text/Markdown layout draft. | You need evidence-based critique of a single-page presentation visual or its prompt, covering thesis clarity, structure, relationships, evidence, hierarchy, and audience comprehension. | Strictly review-only and tool-neutral. Routes deterministically between prompt, structural, and rendered modes; loads only the relevant references and returns prioritized findings plus a minimum revision or prompt patch. |
| `generate-and-process-subtitles` | Generates and processes subtitle files from local media, video URLs, existing SRT files, or raw Whisper JSON. | You need clean `.srt` and `.txt` outputs, subtitle cleanup, translation, or explicit semantic subtitle splitting. | Cross-platform Python `faster-whisper` backend. Final outputs stay in the target directory; process artifacts stay under `_subtitle_work/`. Does not handle dubbing or TTS. |
| `python-design-patterns` | Provides practical guidance for writing maintainable Python with simple, testable design patterns and architecture choices. | You are designing a new Python component, refactoring tangled code, or deciding whether an abstraction is justified. | Documentation-first skill. Focuses on KISS, SRP, separation of concerns, composition over inheritance, and dependency injection. |
| `video-frame-understanding` | Extracts frames from a local video and uses a local Ollama vision-language model to produce faithful frame-level understanding. | You need to understand visible slide, demo, interface, or presentation content from a local video, especially technology conferences, product launches, cloud summits, demos, lectures, or screen recordings. | Uses serial Ollama calls by default. Writes extracted frames, one compact JSON per frame, JSONL aggregate, `summary.md`, and `manifest.json`. Requires explicit user confirmation before execution. |
| `web-content-fetcher` | Extracts the main content from article-like web pages as clean Markdown or structured JSON, with high-fidelity support for WeChat articles. | You need to read, scrape, summarize, or process blog posts, docs pages, newsletters, or WeChat article URLs. | Uses a bundled fetch script with strategy selection and fallback handling for JS-heavy or anti-bot pages. Can localize WeChat images, download standard in-article videos when a real media URL is exposed, and fall back to cover-plus-metadata placeholders for Finder or 视频号 cards. |
| `x-daily-analyst` | Analyzes existing `x-scraper` batch outputs into Chinese intelligence summaries by category and reader perspective. | You want to analyze today's/latest X batch, inspect AI or developer-tool activity, or interpret tweet collections from a product manager, technical lead, or solo-builder perspective. | Reads existing batch data, defaulting to `~/data/x-daily/latest`. Does not scrape X. Supports single-category `interactive` output or a full batch `report` with a required `今日总判断`. Optional delivery helpers can render HTML/PDF or send email when explicitly requested. |
| `x-scraper` | Fetches raw tweets from X/Twitter for a username or configured account alias, with time-range or count filters. Supports single-target and paced batch runs. | You need a collection of posts from one account or many configured aliases before doing your own summarization, translation, or downstream analysis. | Requires user-provided X credentials. Exports structured JSON and Markdown. Batch runs also write `batch_category_index.json` and `summary.json` for downstream skills such as `x-daily-analyst`. Keeps tweet content faithful to the source. |
| `youtube-scraper` | Fetches YouTube channel, single-video, or batch publication metadata and, when explicitly requested, downloads a YouTube video or audio-only media file. | You need recent uploads, channel publication metadata, one video's description, a multi-channel batch scrape, or a local media file from YouTube for downstream workflows. | Separates metadata collection from explicit media download. Supports configured channel aliases, RSS-based channel feeds, `yt-dlp` single-video metadata, and batch targets. Does not handle transcription or subtitle workflows. |

## Testing

Bundled unit tests cover the scripted scraper skills:

```bash
python3 -m unittest discover -v -s skills/x-scraper/tests
python3 -m unittest discover -v -s skills/youtube-scraper/tests
```

Basic evals for `slide-infographic-reviewer` live under [`skills/slide-infographic-reviewer/evals/`](./skills/slide-infographic-reviewer/evals). They verify only skill discovery and routing: whether the skill is selected, which artifact is the review target, which primary mode applies, and which reference handles should be loaded. They intentionally do not score findings, revisions, prompt patches, visual quality, or real review effectiveness; validate those with real usage cases.

```bash
python skills/slide-infographic-reviewer/evals/run_evals.py --self-check
python skills/slide-infographic-reviewer/evals/run_evals.py --adapter-executable <agent-adapter> --adapter-timeout 120
python skills/slide-infographic-reviewer/evals/run_evals.py --results <observed-results.json>
```

An adapter reads one JSON envelope from stdin and writes one discovery or routing trace JSON object to stdout. Envelopes use opaque case IDs. Routing targets use canonical IDs: the exact manifest name for a supplied file, `slide_N` or `page_N` for a page inside a container, and `inline_prompt` or `inline_structural` for material that exists only in the request. Artifact data is limited to names, MIME types, and sizes; fixture contents, image payloads, and expected answers are never sent. `--help` documents timeout, adapter arguments, and output options.

## Notes

- Each skill is self-contained and should include its own `SKILL.md` plus any required scripts, references, or assets.
- Local runtime outputs, caches, and secret environment files are excluded from version control.
- `x-scraper` requires valid X session cookies. Copy [`skills/x-scraper/config/x.env.example`](./skills/x-scraper/config/x.env.example) to `skills/x-scraper/config/x.env`, then configure numbered credentials such as `TWITTER_AUTH_TOKEN_1` + `TWITTER_CT0_1`. See [`skills/x-scraper/SKILL.md`](./skills/x-scraper/SKILL.md) for setup steps, including how to extract `auth_token` and `ct0` from your browser session.
