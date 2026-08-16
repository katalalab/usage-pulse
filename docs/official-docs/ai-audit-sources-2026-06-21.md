# AI audit official-docs evidence

retrieved_at: 2026-06-21 JST

This note records the official/primary sources used to design `usage-pulse audit`.
The implemented collector is intentionally read-only and avoids emitting secret values.

## Source decisions

- OpenAI Codex config: Codex user config is at `~/.codex/config.toml`, and repo-scoped config can live at `.codex/config.toml`.
  Source: https://developers.openai.com/codex/config-basic
- OpenAI Codex instructions: Codex reads `AGENTS.md` in global/project layers, so `audit` records presence/size rather than contents.
  Source: https://developers.openai.com/codex/guides/agents-md
- Anthropic Claude Code settings: `settings.json` is the official hierarchical configuration mechanism; `audit` summarizes safe keys such as model, permissions, hooks, and status line.
  Source: https://docs.anthropic.com/en/docs/claude-code/settings
- Anthropic Claude Code hooks: hooks are configured lifecycle commands/HTTP/LLM prompts, so `audit` records hook presence but redacts nested command details.
  Source: https://docs.anthropic.com/en/docs/claude-code/hooks
- Anthropic Claude Code model config: Claude Code supports model aliases or provider-specific model names, so model-like settings are safe and useful for efficiency review.
  Source: https://docs.anthropic.com/en/docs/claude-code/model-config
- Cursor rules: Cursor supports project rules in `.cursor/rules` and `AGENTS.md`, so `audit` records these instruction surfaces by presence/size.
  Source: https://cursor.com/docs/rules.md
- Gemini CLI config: Gemini CLI uses layered JSON settings, including user `~/.gemini/settings.json` and project `.gemini/settings.json`.
  Source: https://google-gemini.github.io/gemini-cli/docs/get-started/configuration.html
- OpenCode config: OpenCode supports JSON/JSONC config, global `~/.config/opencode/opencode.json`, project `opencode.json`, and merged precedence.
  Source: https://opencode.ai/docs/config/
- ccusage: ccusage reads local agent CLI usage data and emits daily/weekly/monthly/session reports, including JSON output and cache token support.
  Source: https://github.com/ccusage/ccusage

## Implementation mapping

- `usage_pulse.audit.collect_tools`: tool availability, versions, safe config summaries, and instruction surface presence.
- `usage_pulse.audit.collect_usage`: `ccusage daily --json` through the existing provider plus model ROI.
- `usage_pulse.audit.collect_processes`: AI-related process rows with sensitive command arguments redacted.
- `usage_pulse.audit.collect_tmux`: tmux pane count and AI-looking panes.
- `usage_pulse.audit.analyze_bottlenecks`: high load, missing usage source, unavailable usage, high AI CPU, many AI tmux panes, and low cache efficiency.
- `usage-pulse fleet-audit`: SSH aggregation of remote `usage-pulse audit --json --skip-live` output.
