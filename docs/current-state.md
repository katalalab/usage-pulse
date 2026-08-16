# usage-pulse Current State

Updated: 2026-06-29

## Purpose

`usage-pulse` is an OSS Python CLI for monitoring AI tool usage across macOS,
Windows, and Linux. It provides tmux statusline output, tray/notification surfaces,
agent handshake JSON, provider diagnostics, and a model-advisor skill.

## Runtime And Reproducibility

- Runtime: Python 3.11+.
- Local Python selector: `.python-version`.
- Dependency manager: `uv`.
- Lockfile: `uv.lock`.
- Install path: `uv sync --dev --frozen`.
- Main CLI entrypoint: `usage-pulse` via `usage_pulse.cli:main`.

## Verification Contract

The canonical verifier is `scripts/verify.sh`.

- `bash scripts/verify.sh ci`: install, lint, typecheck, security scan, tests, and provider pin parsing.
- `bash scripts/verify.sh lint`: `ruff check` and `ruff format --check`.
- `bash scripts/verify.sh typecheck`: `mypy`.
- `bash scripts/verify.sh security`: `bandit` and `pip-audit`.
- `bash scripts/verify.sh test`: `pytest`.
- `bash scripts/verify.sh providers-static`: parse `providers/VERSION_PINS.json` without dependency sync.

Full CI intentionally performs dependency installation and security scanning. For
lightweight repo standardization checks, use `providers-static`, shell syntax checks,
workflow YAML parsing, and Python compile checks.

## CI Surface

- `.github/workflows/ci.yml`: lint, typecheck, security, and multi-OS test matrix.
- `.github/workflows/check-providers.yml`: weekly provider version check.

CI depends on GitHub-hosted runners, `actions/setup-python`, `astral-sh/setup-uv`,
and the pinned provider metadata in `providers/VERSION_PINS.json`.

## Safety Boundaries

- Do not commit API keys, tokens, cookies, shell history, CLI auth databases, or live
  usage exports.
- Provider versions are intentionally pinned. Do not update
  `providers/VERSION_PINS.json` just because a newer version exists.
- Hook installers create local backups and should remain explicit user actions.
- Fleet/audit commands must redact secrets and report only safe configuration summaries.

## Current Standardization Status

- Repo capsule status: docs index and current-state added.
- Reproducibility status: expected reproducible-ready with Python 3.11+, `uv`,
  `.python-version`, `pyproject.toml`, and `uv.lock`.
- Deferred checks: full `bash scripts/verify.sh ci` because it performs dependency
  sync and security tooling; run it when dependency installation is acceptable.
- Cleanup roadmap: `docs/cleanup-roadmap.md` tracks README/docs/verifier upkeep,
  provider-pin boundaries, and the dependency-sync split for future cleanup passes.
