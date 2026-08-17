---
name: youtube-scraper
description: Fetch recent YouTube channel publications from one or more configured aliases, channel URLs, video URLs, @handles, or channel IDs, and save raw video metadata plus description text. Use when an agent needs channel-level YouTube updates such as latest uploads, recent channel videos, publishing activity, or a bounded time/count scrape for a channel or a batch of channels. Also use when a user asks for metadata or description text for one specific YouTube watch/youtu.be/shorts URL. This skill may also download a YouTube video or an audio-only media file, but only when the user explicitly asks to save or extract media. Do not use for transcription, subtitle generation, subtitle optimization, subtitle translation, dubbing, or general YouTube analysis that does not require publication metadata or explicit media download.
---

# YouTube Scraper

Use this skill for YouTube channel publication discovery by default, with single-video metadata as a supported narrow path. Use media download only on explicit user request.

Typical requests:

- "Fetch recent uploads from this YouTube channel"
- "抓取这些 YouTube 账号最近 7 天发布的视频信息"
- "抓取这个 YouTube 视频链接的 description"
- "Get metadata for this YouTube video"

Channel metadata flow:

1. Resolve the target to a `channel_id`.
2. Run the bundled script once with the narrowest valid range.
3. Validate that outputs were written and the result is coherent.
4. Summarize the result without pasting long descriptions into the chat.
5. If no output directory was provided, expect the script to create a timestamped directory like `./youtube-YYYYMMDD-HHMMSS`.

Single video metadata flow:

1. Use this flow when the user gives a YouTube watch, youtu.be, or shorts URL and asks for that video's description or metadata.
2. Run the bundled single-video metadata script once.
3. Validate that outputs were written and the result is coherent.
4. Summarize the result without pasting the full description unless the user asks for it.
5. If no output directory was provided, expect the script to create a timestamped directory like `./youtube-video-YYYYMMDD-HHMMSS`.

Batch flow:

1. Use the batch script when the user asks for multiple aliases, handles, channel URLs, video URLs, or channel IDs in one request.
2. Put each target in the command arguments or in a UTF-8 targets file.
3. Run the batch script once with the narrowest valid shared range; exact duplicate targets are ignored after their first occurrence.
4. Validate the batch summary plus each per-target JSON output.
5. If no output directory was provided, expect the script to create a timestamped directory like `./youtube-batch-YYYYMMDD-HHMMSS`.

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
- `@handle` such as `@OpenAI`
- direct `channel_id` such as `UCXZCJLdBC09xxGZ6gcdrc6A`
- single YouTube video URL such as `https://www.youtube.com/watch?v=Hbn5H0rFOmE`
- short URL such as `https://youtu.be/Hbn5H0rFOmE`
- shorts URL such as `https://www.youtube.com/shorts/Hbn5H0rFOmE`

Accepted batch targets:

- any mix of the accepted single-target forms
- command arguments such as `"YT_OpenAI" "@AnthropicAI" "UC..."`
- a UTF-8 text file with one target per line; blank lines and lines starting with `#` are ignored
- a JSON file containing either a list of strings or an object with a `targets` list
- every alias in `defaults/youtube_channels.json` by passing `--all-configured`

Accepted download targets:

- single YouTube video URLs such as `https://www.youtube.com/watch?v=...`
- short URLs such as `https://youtu.be/...`
- shorts URLs such as `https://www.youtube.com/shorts/...`

The metadata script uses YouTube's public RSS feed:
`https://www.youtube.com/feeds/videos.xml?channel_id=<channel_id>`

The single-video metadata script uses `yt-dlp` in metadata-only mode:
`extract_info(..., download=False)`

No API key is required.
Optional dependency:
- `curl_cffi` for browser-like TLS impersonation during handle or URL resolution
- `yt-dlp` for single-video metadata and explicit media downloads

RSS stability behavior:

- The script sends browser-like headers for RSS requests.
- If the `channel_id` RSS endpoint fails, it retries with short backoff and then falls back to derived playlist RSS variants.
- The JSON output records the selected feed URL and failed attempts under `rss_fetch` so intermittent YouTube RSS failures can be diagnosed after a run.

## Boundary Rules

Use this skill for:

- channel discovery
- recent uploads
- publication metadata export
- single-video metadata and description extraction
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

If the user gives a watch, youtu.be, or shorts URL and asks for that video's description or metadata, treat it as a single-video metadata request. Do not expand it to a channel recent-upload scrape.

If the user gives a video URL but asks for the owning channel's recent uploads or activity, resolve the video URL to its owning `channelId` and use the channel metadata flow.

Resolve the target in this order:

1. If the user mentions a configured alias, resolve it through `defaults/youtube_channels.json`.
   This file is the single source of truth and stores the full channel catalog, including alias and `channel_id`.
2. If the input starts with `UC`, treat it as a `channel_id`.
3. If the input is a YouTube URL or `@handle`, fetch the page and extract the owning `channelId`.
4. If the input is a bare string that is not an alias, treat it as a handle and try `https://www.youtube.com/@<value>`.

Normalize by trimming whitespace. Strip a leading `@` only when normalizing a handle. Accept `youtube.com/@handle`, `youtube.com/channel/<id>`, `youtube.com/c/...`, `youtube.com/user/...`, `youtube.com/watch?v=...`, `youtu.be/...`, and `youtube.com/shorts/...`.

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

Channel scrape command:

Run:

```bash
python "{SKILL_ROOT}/scripts/youtube_channel_meta.py" "<target>"
```

Batch scrape command:

Run:

```bash
python "{SKILL_ROOT}/scripts/youtube_batch_meta.py" "<target-1>" "<target-2>"
```

Or from a targets file:

```bash
python "{SKILL_ROOT}/scripts/youtube_batch_meta.py" --targets-file "targets.txt"
```

Or all configured aliases:

```bash
python "{SKILL_ROOT}/scripts/youtube_batch_meta.py" --all-configured
```

Single-video metadata command:

```bash
python "{SKILL_ROOT}/scripts/youtube_video_meta.py" "https://www.youtube.com/watch?v=example"
```

Examples:

```bash
python "{SKILL_ROOT}/scripts/youtube_channel_meta.py" "YT_OpenAI" --days-lookback 14 --limit 10
```

```bash
python "{SKILL_ROOT}/scripts/youtube_channel_meta.py" "@OpenAI" --since-date 2026-03-01 --until-date 2026-03-20 --limit 20
```

```bash
python "{SKILL_ROOT}/scripts/youtube_batch_meta.py" "YT_OpenAI" "@OpenAI" "UCXZCJLdBC09xxGZ6gcdrc6A" --days-lookback 14 --limit 10
```

```bash
python "{SKILL_ROOT}/scripts/youtube_video_meta.py" "https://youtu.be/Hbn5H0rFOmE"
```

When the user asks to scrape all configured YouTube accounts, prefer `--all-configured` instead of manually extracting aliases into a targets file. The batch script forwards shared range and output options to the single-target metadata script. It continues after individual target failures by default and returns `partial_failure` with a nonzero exit code if any target fails. Use `--stop-on-error` only when partial results are not useful.

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

If `--output-dir` is omitted, the single-video metadata script creates a timestamped directory like `./youtube-video-YYYYMMDD-HHMMSS`.
If `--output-dir` is omitted, the channel and download scripts create a timestamped directory like `./youtube-YYYYMMDD-HHMMSS`.
For batch metadata scraping, omitted `--output-dir` creates a timestamped directory like `./youtube-batch-YYYYMMDD-HHMMSS`.

## Validate Result

Read the JSON file written to disk; do not treat console encoding or stdout as the source of truth. Console JSON is ASCII status only. Do not ask the caller to set `PYTHONIOENCODING` or UTF-8 mode.

For channel metadata runs, check all of the following before you trust the result:

- the JSON `status` field is `ok` or `ok_with_warnings` (read the JSON file; do not rely only on stdout)
- JSON and Markdown files both exist
- `resolved_channel_id` is present
- `video_count` matches the number of exported items
- if the feed returned a `feed_channel_id`, it matches the resolved channel unless the script explicitly marked a warning
- `video_count = 0` is treated as a valid but notable outcome, not silent success

For batch runs, also check:

- batch summary `status` is `ok`, `ok_with_warnings`, or `partial_failure`
- `attempted_count`, `success_count`, and `failure_count` match the per-target results
- every successful target has per-target JSON and Markdown paths
- for each successful target, validate the per-target JSON using the single-target checklist above

The batch runner uses child stdout only to locate JSON and Markdown artifacts. After validation, all per-target business fields and counts in the batch summary come from the child JSON on disk; stale or contradictory stdout fields are ignored.
- `partial_failure` is reported to the user with the failed targets and structured error messages

For single-video metadata runs, check all of the following before you trust the result:

- the JSON `status` field is `ok` or `ok_with_warnings` (read the JSON file; do not rely only on stdout)
- JSON and Markdown files both exist
- `mode` is `single_video_metadata`
- `video_id`, `title`, and `description` are present unless the script explicitly marked a warning
- `channel_id` is present unless the script explicitly marked a warning

## Expected Outputs

The metadata script writes:

- a JSON file with metadata, effective query parameters, validation results, and video items
- a Markdown file with one section per video showing raw publication information

The batch metadata script writes:

- all per-target JSON and Markdown files produced by the single-target metadata script
- one batch summary JSON file with target status, per-target paths, counts, and errors
- one batch summary Markdown file for quick review

The single-video metadata script writes:

- one JSON file with the requested video's metadata and validation result
- one Markdown file with the requested video's raw description

The download script writes:

- one local media file
- one sidecar JSON file ending in `.download.json`

Each channel video item should include:

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

The single-video metadata output should include:

- `mode`
- `source_url`
- `resolved_url`
- `video_id`
- `title`
- `published_at`
- `channel_name`
- `channel_id`
- `duration_seconds`
- `duration_text`
- `description`
- `thumbnail_url`
- `json_path`
- `markdown_path`

When reporting results to the user:

- include whether the run succeeded cleanly, succeeded with warnings, or failed
- include the `video_id` for single-video runs, or the resolved `channel_id` for channel runs
- state whether it came from an alias, video URL, channel URL, handle, or explicit ID
- mention the effective range or count for channel runs
- summarize output file paths
- summarize the videos; do not paste long descriptions unless the user asks
- if the user requested Chinese, provide your own translation or summary after reading the output
- surface partial failures such as empty feeds, mismatched IDs, or handle resolution failures

For batch metadata runs also report:

- batch status, attempted count, success count, and failure count
- the batch summary JSON and Markdown paths
- per-target output paths for successful targets
- failed targets with `error_type`, `failed_step`, and actionable suggestions when present

For explicit downloads also report:

- whether the result is `video` or `audio`
- the final saved media path
- the sidecar JSON path
- any dependency limitation such as missing `ffmpeg` during video merging

## Failure Handling

If the script cannot run:

- if single-video metadata fails because `yt-dlp` is missing, tell the user to install `yt-dlp`
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
