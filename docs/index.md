# usage-pulse Docs Index

`usage-pulse` is a cross-platform AI tool usage monitor for tmux statusline output,
desktop tray/notification integration, Claude Code hooks, and agent-readable usage
state.

## Primary Sources

- [README.md](../README.md): user-facing install, commands, architecture, and provider notes.
- [AGENTS.md](../AGENTS.md): repo-local agent rules, dependency policy, and verification entrypoint.
- [pyproject.toml](../pyproject.toml): Python package metadata, dependencies, and tool settings.
- [scripts/verify.sh](../scripts/verify.sh): repo-local verification targets used by CI and local runs.
- [.github/workflows/ci.yml](../.github/workflows/ci.yml): lint, typecheck, security, and test workflow.
- [.github/workflows/check-providers.yml](../.github/workflows/check-providers.yml): scheduled provider version check.
- [providers/VERSION_PINS.json](../providers/VERSION_PINS.json): pinned external provider versions.

## Operational Notes

- [current-state.md](current-state.md): current reproducibility, CI, and adoption status.
- [cleanup-roadmap.md](cleanup-roadmap.md): README/docs/verifier cleanup plan and verification boundaries.
- [official-docs/ai-audit-sources-2026-06-21.md](official-docs/ai-audit-sources-2026-06-21.md): prior official/source evidence for the AI audit surface.

## Local Verification

Use the repo-local verifier instead of duplicating CI commands:

```bash
bash scripts/verify.sh ci
```

For a dependency-free smoke check of provider pin metadata:

```bash
bash scripts/verify.sh providers-static
```

For docs-only cleanup slices, also run:

```bash
bash -n scripts/verify.sh
git diff --check
```
