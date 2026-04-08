# feishuai-skills

A collection of reusable agent skills for common research, scraping, and engineering workflows.

## Structure

All skills live under [`skills/`](./skills).

## Skill Catalog

| Skill | What It Does | Use It When | Key Outputs / Notes |
| --- | --- | --- | --- |
| `python-design-patterns` | Provides practical guidance for writing maintainable Python with simple, testable design patterns and architecture choices. | You are designing a new Python component, refactoring tangled code, or deciding whether an abstraction is justified. | Documentation-first skill. Focuses on KISS, SRP, separation of concerns, composition over inheritance, and dependency injection. |
| `web-content-fetcher` | Extracts the main content from article-like web pages as clean Markdown or structured JSON, with high-fidelity support for WeChat articles. | You need to read, scrape, summarize, or process blog posts, docs pages, newsletters, or WeChat article URLs. | Uses a bundled fetch script with strategy selection and fallback handling for JS-heavy or anti-bot pages. Can localize WeChat images, download standard in-article videos when a real media URL is exposed, and fall back to cover-plus-metadata placeholders for Finder or 视频号 cards. |
| `x-scraper` | Fetches raw tweets from X/Twitter for a username or configured account alias, with time-range or count filters. | You need a collection of posts from an account before doing your own summarization, translation, or downstream analysis. | Requires user-provided X credentials. Exports structured JSON and Markdown. Keeps tweet content faithful to the source. |
| `youtube-scraper` | Fetches YouTube channel publication metadata and, when explicitly requested, downloads a YouTube video or audio-only media file. | You need recent uploads, channel publication metadata, or a local media file from YouTube for downstream workflows. | Separates channel metadata collection from explicit media download. Does not handle transcription or subtitle workflows. |

## Notes

- Each skill is self-contained and should include its own `SKILL.md` plus any required scripts, references, or assets.
- Local runtime outputs, caches, and secret environment files are excluded from version control.
- `x-scraper` requires valid X session cookies. Configure numbered credentials in `skills/x-scraper/config/x.env`, such as `TWITTER_AUTH_TOKEN_1` + `TWITTER_CT0_1`. See [`skills/x-scraper/SKILL.md`](./skills/x-scraper/SKILL.md) for setup steps, including how to extract `auth_token` and `ct0` from your browser session.
