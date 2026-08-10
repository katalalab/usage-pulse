# Cleanup Roadmap

Updated: 2026-07-06 JST

## Current Status

- Repo state before this pass: clean.
- Public project surface: `README.md`, `CHANGELOG.md`, `CONTRIBUTING.md`, `LICENSE`, `.github/`.
- Runtime contract: Python `3.11+`, local selector `.python-version`, dependencies managed by `uv`.
- Canonical verifier: `scripts/verify.sh`.
- Full CI target: `bash scripts/verify.sh ci`.
- Dependency-free metadata target: `bash scripts/verify.sh providers-static`.

## Verified This Pass

- `bash -n scripts/verify.sh`: verifier shell syntax.
- `bash scripts/verify.sh providers-static`: provider version pin JSON parsing.
- `uv run --no-sync pytest tests/ -v --tb=short`: tests using the existing local environment.
- `git diff --check`: whitespace check.

## Roadmap

1. Keep README as the public entrypoint.
   - Preserve install, command, architecture, provider, and license sections.
   - Keep operational caveats in docs instead of expanding README indefinitely.
2. Keep `docs/current-state.md` as the reproducibility and CI snapshot.
   - Update Python, uv, verifier, CI, and provider-pin notes when contracts change.
   - Keep full dependency sync and security scan boundaries explicit.
3. Keep `docs/index.md` as the documentation map.
   - Link new operational docs here before adding more README links.
   - Keep official/source evidence under `docs/official-docs/`.
4. Keep `CHANGELOG.md` current for user-facing changes.
   - Add README/docs/verifier changes under `Unreleased`.
   - Provider behavior and version-pin changes must be called out separately.
5. Treat provider and hook changes as higher-risk.
   - Do not update `providers/VERSION_PINS.json` as incidental cleanup.
   - Hook installers and tmux integration should remain explicit user actions with backup retention.

## Open Items

- Run full `bash scripts/verify.sh ci` when dependency sync, `bandit`, and `pip-audit` are in scope.
- Refresh official/source evidence before changing GitHub Actions, uv setup, provider CLI behavior, hook install behavior, or cross-platform notification assumptions.
- Add a short provider schema compatibility note if `ccusage` or `codexbar` output formats change.
