---
name: x-scraper
description: Fetch X/Twitter tweets for a specific username or a configured x account alias, with time-range or count filters, and output raw tweet content. Use when the user asks to scrape X posts, Twitter timelines, tweets from an account, or requests tweet collections that the agent can summarize or translate itself.
---

# X Scraper

## Purpose

Use this skill to fetch tweets from X for either:

- an exact username such as `karpathy` or `@OpenAI`
- a configured account alias such as `X_OpenAI` from `defaults/x_target_accounts.json`

*Note:* `{SKILL_ROOT}` in the instructions below refers to the absolute path to the directory containing this `SKILL.md` file. Always resolve `{SKILL_ROOT}` to its true absolute path before executing commands.

## Prerequisites

Before running the script, ensure the environment has X credentials:

1. **First**, check if `{SKILL_ROOT}/defaults/x.env` exists. If it does, automatically load its numbered credential pairs into the execution environment.
2. **Second**, if the `x.env` file is missing or incomplete, ask the user to fill it in.

Credential precedence:

- `defaults/x.env` is the standard configuration source for this skill
- if it does not provide usable numbered credential pairs, fail fast and ask the user to complete it

Recommended setup in `{SKILL_ROOT}/defaults/x.env`:

```bash
TWITTER_AUTH_TOKEN_1=your_auth_token_here
TWITTER_CT0_1=your_ct0_here
```

If you want to keep backup accounts in the same file, continue numbering them:

```bash
TWITTER_AUTH_TOKEN_2=your_auth_token_here
TWITTER_CT0_2=your_ct0_here
```

How to obtain `auth_token` and `ct0` from an active X login session:

1. Open `x.com` in Chrome or Edge and sign in to your account.
2. Press `F12` to open Developer Tools, then switch to the `Network` tab.
3. Refresh the page.
4. Click any request in the network list, commonly `HomeTimeline` or `guide.json`.
5. In `Headers` -> `Request Headers`, find the `cookie` header.
6. Copy the values of `auth_token` and `ct0`.
7. Do not include the trailing semicolon when copying either value.

When the skill reports missing credentials, remind the user to follow the steps above and fill in:

- `TWITTER_AUTH_TOKEN_1` plus `TWITTER_CT0_1`
- and optionally additional numbered pairs such as `TWITTER_AUTH_TOKEN_2` plus `TWITTER_CT0_2`

Optional dependency:

- `curl_cffi` for browser-like TLS impersonation

Install it when needed:

```bash
pip install curl_cffi
```

## Target Resolution

Resolve the user's target in this order:

1. If the user explicitly gives a username or profile URL, normalize it to a bare username.
2. Otherwise, if the user mentions a configured X account alias, resolve it through `defaults/x_target_accounts.json`.
3. If both are present, prefer the explicit username.

Normalization rules:

- strip leading `@`
- if the user provides `https://x.com/<name>` or `https://twitter.com/<name>`, extract `<name>`
- preserve case-insensitive matching for aliases, but pass the configured username exactly as stored

## Range Resolution

Rules:

- If the user gives an absolute range, prefer `--since-date` and `--until-date`
- If the user gives only a relative range like "最近 7 天", use `--days-lookback`
- If the user gives only a count like "抓 20 条", use `--limit`
- If the user gives both a range and a count, pass both
- Otherwise, rely on script defaults and check `--help` if the exact parameter behavior is unclear

*Note:* This skill is strictly designed for scraping raw tweets. If translations, summaries, or analyses are requested, do NOT modify the script; instead, run it to get the raw data, then read the output files and handle the translations/summaries using your own LLM context.

## Command

**CRITICAL Execution Rule:** Use `scripts/x_scrape.py` for one target at a time. Do not parallelize repeated X fetches.

**CRITICAL Batch Rule:** For multiple targets or account lists, use `scripts/x_scrape_batch.py` instead of chaining single-target runs. The batch script handles pacing and stops the run after the first `429` or `rate_limit`.

**CRITICAL Timeout Rule:** When an agent such as Codex or Claude Code runs this script for a real X fetch, set the command timeout to at least `600000 ms`. Real fetches can take several minutes because of retries, paging, and rate limits.

Default page delay is intentionally conservative to reduce rate-limit risk: `--page-delay-min 6.0` and `--page-delay-max 10.0`.

The script is intentionally fail-fast for agent use. If it hits `rate_limit`, `auth_error`, `api_error`, or `timeout`, it exits immediately with a clear error instead of retrying for a long time.

Use the scripts like this:

- single target: `scripts/x_scrape.py`
- multiple targets or account lists: `scripts/x_scrape_batch.py`
- if argument behavior or defaults are unclear, check the script help first with `python "{SKILL_ROOT}/scripts/x_scrape.py" --help` or `python "{SKILL_ROOT}/scripts/x_scrape_batch.py" --help`

## Multi-Target Safety Rules

When the user wants tweets from many accounts, apply these rules in addition to the normal single-target flow:

1. Use `scripts/x_scrape_batch.py` instead of chaining repeated single-target runs.

2. Make the batch behavior explicit in the response.
   If you process many targets, tell the user where execution stopped and whether a `429` or `rate_limit` occurred.


Run:

```bash
python "{SKILL_ROOT}/scripts/x_scrape.py" "<target>"
```

Batch run:

```bash
python "{SKILL_ROOT}/scripts/x_scrape_batch.py" "X_OpenAI,X_Anthropic,X_DeepSeek"
```

```bash
python "{SKILL_ROOT}/scripts/x_scrape_batch.py" "targets.txt" --days-lookback 3
```

Default output behavior:

- by default, create a timestamped directory in the current project root, such as `x-posts-20260403-113000`
- write the JSON and Markdown files for that run into that directory
- use `--output-dir` only when the user explicitly wants a different base directory

Batch output behavior:

- by default, create a timestamped directory in the current project root, such as `x-posts-batch-20260403-113000`
- write each target's JSON and Markdown files directly into that directory without extra per-target subdirectories
- also write `summary.json` and `summary.md` for the whole batch
- use script defaults unless the user explicitly asks to override batch sizing or delay settings

## Expected Outputs

The script writes two files:

- a JSON file with tweet metadata and original text
- a Markdown file with one section per tweet showing the original content
- retweets include extra fields describing the original retweeted post

When reporting results to the user:

- include the resolved username
- state whether it came from an alias or explicit username
- mention the effective range or count
- mention the effective `retweet_mode`
- mention the run status: `success`, `partial_success`, or `failed`
- summarize output file paths
- if the user requested Chinese, provide your own translation in the response after reading the output
- surface any partial failures such as empty fetches

The exported JSON now includes run metadata such as:

- `run_status`
- `pages_fetched`
- `partial_failure_reason`
- `env_file_used`

## Failure Handling

If the script cannot run:

- if X credentials are missing, ask the user to fill in `defaults/x.env` with `TWITTER_AUTH_TOKEN_1` and `TWITTER_CT0_1`, and include the browser extraction steps from the prerequisites section
- if the target alias is unknown, tell the user and offer nearby alias matches from `defaults/x_target_accounts.json`
- if a multi-target run hits `429` or `rate_limit`, stop the entire run immediately, report which target triggered the limit, and recommend resuming after at least 15 minutes instead of continuing the remaining targets or later batches

## Notes

- Keep output faithful to the source tweet content
- Preserve URLs, `@mentions`, hashtags, and line breaks when you translate in your own response
- Do not copy repository secrets into skill files
