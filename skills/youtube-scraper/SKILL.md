---
name: youtube-scraper
description: Fetch recent YouTube channel publications from a configured alias, channel URL, video URL, @handle, or channel ID, and save raw video metadata plus description text. Use when an agent needs channel-level YouTube updates such as latest uploads, recent channel videos, publishing activity, or a bounded time/count scrape for a channel. If given a YouTube video URL, resolve its owning channel first and then scrape that channel's publications. This skill may also download a YouTube video or an audio-only media file, but only when the user explicitly asks to save or extract media. Do not use for transcription, subtitle generation, subtitle optimization, subtitle translation, dubbing, or general YouTube analysis that does not require publication metadata or explicit media download.
---

# YouTube Scraper

Use this skill for YouTube publication discovery by default, and for media download only on explicit user request.

Default flow:

1. Resolve the target to a `channel_id`.
2. Run the bundled script once with the narrowest valid range.
3. Validate that outputs were written and the result is coherent.
4. Summarize the result without pasting long descriptions into the chat.
5. If no output directory was provided, expect the script to create a timestamped directory like `./youtube-YYYYMMDD-HHMMSS`.

Download flow:

1. Confirm that the user explicitly asked to download a video or extract audio.
2. Run the bundled download script once for a single YouTube video URL.
3. Validate that the media file and sidecar JSON were written.
4. Report the saved file path.
5. If no output directory was provided, expect the script to create a timestamped directory like `./youtube-YYYYMMDD-HHMMSS`.

The skill is self-contained. Do not import or rely on modules from the current repository.

`{SKILL_ROOT}` below means the directory containing this `SKILL.md`.

Accepted targets:

- configured alias such as `YT_OpenAI` from `defaults/youtube_channels.json`
- channel URL such as `https://www.youtube.com/@OpenAI`
- video URL such as `https://www.youtube.com/watch?v=Hbn5H0rFOmE`
- `@handle` such as `@OpenAI`
- direct `channel_id` such as `UCXZCJLdBC09xxGZ6gcdrc6A`

Accepted download targets:

- single YouTube video URLs such as `https://www.youtube.com/watch?v=...`
- short URLs such as `https://youtu.be/...`
- shorts URLs such as `https://www.youtube.com/shorts/...`

The metadata script uses YouTube's public RSS feed:
`https://www.youtube.com/feeds/videos.xml?channel_id=<channel_id>`

No API key is required.
Optional dependency:
- `curl_cffi` for browser-like TLS impersonation during handle or URL resolution
- `yt-dlp` for explicit media downloads

## Boundary Rules

Use this skill for:

- channel discovery
- recent uploads
- publication metadata export
- explicit video download
- explicit audio-only download

Do not use this skill for:

- transcription
- subtitle generation
- subtitle optimization
- subtitle translation
- dubbing

Those belong to `subtitle-workbench`.

If the user asks for subtitle outputs from YouTube, route that work to `subtitle-workbench`. If a local media file is also needed and the user explicitly asks to keep it, download it here first and then hand off the local file.

## Resolve Target

Resolve the target in this order:

1. If the user mentions a configured alias, resolve it through `defaults/youtube_channels.json`.
   This file is the single source of truth and stores the full channel catalog, including alias and `channel_id`.
2. If the input starts with `UC`, treat it as a `channel_id`.
3. If the input is a YouTube URL or `@handle`, fetch the page and extract the owning `channelId`.
4. If the input is a bare string that is not an alias, treat it as a handle and try `https://www.youtube.com/@<value>`.

Normalize by trimming whitespace. Strip a leading `@` only when normalizing a handle. Accept `youtube.com/@handle`, `youtube.com/channel/<id>`, `youtube.com/c/...`, `youtube.com/user/...`, and `youtube.com/watch?v=...`.

## Resolve Range

Support both count-based and time-based fetching.

- Count-based: use `--limit`
- Relative time range: use `--days-lookback`
- Absolute time range: use `--since-date` and optional `--until-date`

Rules:

- If the user gives an absolute range, prefer `--since-date` and `--until-date`
- If the user gives only a relative range like "last 7 days", use `--days-lookback 7`
- If the user gives only a count like "fetch 20 videos", use `--limit 20`
- If the user gives both a range and a count, pass both
- If the user gives neither, default to `--limit 20`
- If the user gives a date range but no explicit count, let the script use its wider date-range default

Duration rule:

- Default to including duration metadata for each video
- The script fetches each video page and extracts duration metadata after the RSS pass
- Only use `--skip-duration` when speed matters more than runtime metadata

## Parameter Policy

Default behavior:

- Do not override optional script parameters unless the user explicitly asks for different behavior.
- Prefer the script defaults when they already match the task.
- Treat optional flags as overrides, not as required boilerplate.
- If you are unsure whether an optional parameter is needed, check the script's `--help` output before adding overrides.

Use optional parameters only in these cases:

- use `--limit` when the user explicitly asks for a count, or when a bounded result size is necessary for the task
- use `--days-lookback`, `--since-date`, or `--until-date` only when the user explicitly gives a relative or absolute time range
- use `--skip-duration` only when the user explicitly prioritizes speed or does not need duration metadata
- use `--output-dir` only when the user explicitly wants a specific save location or a downstream workflow requires a stable path
- use `--alias-file` only when the user explicitly points to a custom alias catalog
- use `--request-timeout` only when the user explicitly asks to tune timeout behavior or you are debugging a network issue

Do not invent optional overrides just because they are available.

## Command

Default scrape command:

Run:

```bash
python "{SKILL_ROOT}/scripts/youtube_channel_meta.py" "<target>"
```

Examples:

```bash
python "{SKILL_ROOT}/scripts/youtube_channel_meta.py" "YT_OpenAI" --days-lookback 14 --limit 10
```

```bash
python "{SKILL_ROOT}/scripts/youtube_channel_meta.py" "@OpenAI" --since-date 2026-03-01 --until-date 2026-03-20 --limit 20
```

Explicit download commands:

Download a video file only when the user explicitly asks to save the video:

```bash
python "{SKILL_ROOT}/scripts/youtube_download.py" "https://www.youtube.com/watch?v=example" --download-video
```

Download an audio-only media file only when the user explicitly asks to extract or save audio:

```bash
python "{SKILL_ROOT}/scripts/youtube_download.py" "https://www.youtube.com/watch?v=example" --extract-audio
```

Do not download media by default during normal scraping workflows.

If `--output-dir` is omitted, both scripts create a timestamped directory like `./youtube-YYYYMMDD-HHMMSS`.

## Validate Result

After the script finishes, check all of the following before you trust the result:

- the JSON `status` field is `ok` or `ok_with_warnings` (read the JSON file; do not rely only on stdout)
- JSON and Markdown files both exist
- `resolved_channel_id` is present
- `video_count` matches the number of exported items
- if the feed returned a `feed_channel_id`, it matches the resolved channel unless the script explicitly marked a warning
- `video_count = 0` is treated as a valid but notable outcome, not silent success

## Expected Outputs

The metadata script writes:

- a JSON file with metadata, effective query parameters, validation results, and video items
- a Markdown file with one section per video showing raw publication information

The download script writes:

- one local media file
- one sidecar JSON file ending in `.download.json`

Each video item should include:

- `video_id`
- `title`
- `published_at`
- `url`
- `channel_name`
- `channel_id`
- `description`
- `thumbnail_url`
- `rss_url`
- `duration_seconds`
- `duration_text`

When reporting results to the user:

- include whether the run succeeded cleanly, succeeded with warnings, or failed
- include the resolved `channel_id`
- state whether it came from an alias or explicit input
- mention the effective range or count
- summarize output file paths
- summarize the videos; do not paste long descriptions unless the user asks
- if the user requested Chinese, provide your own translation or summary after reading the output
- surface partial failures such as empty feeds, mismatched IDs, or handle resolution failures

For explicit downloads also report:

- whether the result is `video` or `audio`
- the final saved media path
- the sidecar JSON path
- any dependency limitation such as missing `ffmpeg` during video merging

## Failure Handling

If the script cannot run:

- read the structured error payload first
- if the target alias is unknown, tell the user and offer nearby alias matches from `defaults/youtube_channels.json`
- if the target URL or handle cannot be resolved to a `channel_id`, explain that resolution failed and suggest passing a direct `channel_id`
- if the network fetch fails, report the failed step and whether retrying is likely to help
- if explicit media download fails because `yt-dlp` is missing, tell the user to install `yt-dlp`
- if explicit video download fails because `ffmpeg` is missing for format merging, tell the user to install `ffmpeg` or retry with audio-only download

## Notes

- Keep output faithful to the source RSS feed and channel page
- Preserve URLs and line breaks in descriptions
- The script must not call any LLM or translation API
- Do not add subtitle or transcript logic in this skill
- Do not download media unless the user explicitly asked for it
