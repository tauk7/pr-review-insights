# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Single-file Python CLI tool (`pr-review-insights.py`) that collects code review comments and diffs from a user's recent GitHub PRs, sends them to an AI provider for analysis, and outputs actionable insights. Written in Portuguese (pt-BR).

## Running

```bash
# Requires: gh CLI authenticated (gh auth login) + one API key exported
export GEMINI_API_KEY='...'   # or ANTHROPIC_API_KEY or DEEPSEEK_API_KEY

python3 pr-review-insights.py
```

The script is interactive — it prompts for provider selection (Claude/Gemini/DeepSeek) and analysis mode (comments/diff/both). There are no tests, no build step, no linter configured. Dependencies (`anthropic`, `google-generativeai`, `openai`) are auto-installed via pip on first use.

## Architecture

Everything lives in `pr-review-insights.py`. The flow is sequential:

1. **Provider selection** (`select_provider`) — validates API key with a ping request before proceeding
2. **Mode selection** (`select_mode`) — comments only, diff only, or both
3. **PR discovery** (`get_recent_prs`) — uses `gh search prs --author @me` to find up to 80 recent PRs
4. **PR filtering** — keeps only PRs with >3 changed files, up to 10 qualifying PRs
5. **Data collection** (`get_review_comments`, `get_pr_diff`) — fetches inline comments, review summaries, and diffs via `gh` CLI
6. **Prompt building** (`build_prompt`) — assembles a structured Portuguese prompt with sections for comment validation, diff review, patterns/insights, and XYZ-format contributions
7. **AI streaming** (`run_claude`/`run_gemini`/`run_deepseek`) — streams response to stdout
8. **Output** — saves markdown to `~/pr-insights/insights_<timestamp>.md`

Key design decisions:
- All GitHub interaction goes through the `gh()` helper which wraps `gh` CLI (not the GitHub API directly)
- Diff is truncated: max 120 lines per file, 90K total chars, skips lock files/dist/generated files (`_SKIP_RE`)
- Gemini has fallback model chain: `gemini-2.5-pro` → `gemini-2.5-flash` → `gemini-1.5-pro`
- Python 3.6+ compatibility is maintained (no walrus operator, no f-string debugging, etc.)

## Language

All user-facing strings, prompts, and comments are in Brazilian Portuguese.
