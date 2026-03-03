# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Single-file Node.js CLI tool (`pr-review-insights.mjs`) that collects code review comments and diffs from a user's recent GitHub PRs, sends them to an AI provider for analysis, and outputs actionable insights. Written in Portuguese (pt-BR).

## Running

```bash
# Requires: gh CLI authenticated (gh auth login) + one API key exported
export GEMINI_API_KEY='...'   # or ANTHROPIC_API_KEY or DEEPSEEK_API_KEY

npm install   # first time only
node pr-review-insights.mjs
```

The script is interactive — it prompts for provider selection (Claude/Gemini/DeepSeek) and analysis mode (comments/diff/both). There are no tests, no build step, no linter configured. Dependencies (`@anthropic-ai/sdk`, `@google/generative-ai`, `openai`) are declared in `package.json`.

## Architecture

Everything lives in `pr-review-insights.mjs` (ESM). The flow is sequential:

1. **Provider selection** (`selectProvider`) — validates API key with a ping request before proceeding
2. **Mode selection** (`selectMode`) — comments only, diff only, or both
3. **PR discovery** (`getRecentPrs`) — uses `gh search prs --author @me` to find up to 80 recent PRs
4. **PR filtering** — keeps only PRs with >3 changed files, up to 10 qualifying PRs
5. **Data collection** (`getReviewComments`, `getPrDiff`) — fetches inline comments, review summaries, and diffs via `gh` CLI
6. **Prompt building** (`buildPrompt`) — assembles a structured Portuguese prompt with sections for comment validation, diff review, patterns/insights, and XYZ-format contributions
7. **AI streaming** (`runClaude`/`runGemini`/`runDeepseek`) — streams response to stdout
8. **Output** — saves markdown to `~/pr-insights/insights_<timestamp>.md`

Key design decisions:
- All GitHub interaction goes through the `gh()` helper which wraps `gh` CLI via `execFileSync` (not the GitHub API directly)
- Diff is truncated: max 120 lines per file, 90K total chars, skips lock files/dist/generated files (`_SKIP_RE`)
- Gemini has fallback model chain: `gemini-2.5-pro` → `gemini-2.5-flash` → `gemini-1.5-pro`

## Language

All user-facing strings, prompts, and comments are in Brazilian Portuguese.
