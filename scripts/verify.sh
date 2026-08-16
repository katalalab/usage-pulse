#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET="${1:-ci}"

usage() {
  cat <<'USAGE'
Usage: scripts/verify.sh [ci|install|lint|typecheck|security|test|providers-static]

Targets:
  ci                Run install, lint, typecheck, security, tests, and static provider checks.
  install           Run uv sync --dev --frozen.
  lint              Run ruff check and ruff format --check.
  typecheck         Run mypy.
  security          Run bandit and pip-audit.
  test              Run pytest.
  providers-static  Parse provider version pins JSON.
USAGE
}

run_repo() {
  (cd "$ROOT_DIR" && "$@")
}

install_deps() {
  run_repo uv sync --dev --frozen
}

lint() {
  run_repo uv run ruff check src/ tests/
  run_repo uv run ruff format --check src/ tests/
}

typecheck() {
  run_repo uv run mypy src tests
}

security() {
  run_repo uv run bandit -r src/ -ll -x src/usage_pulse/display/tray.py
  run_repo uv run pip-audit
}

test_suite() {
  run_repo uv run pytest tests/ -v --tb=short
}

providers_static() {
  run_repo python3 - <<'PY'
import json
from pathlib import Path

path = Path("providers/VERSION_PINS.json")
data = json.loads(path.read_text(encoding="utf-8"))
for provider, info in data.items():
    if provider.startswith("_"):
        continue
    if not isinstance(info, dict) or not info.get("version"):
        raise SystemExit(f"{provider}: missing version pin")
PY
}

case "$TARGET" in
  ci)
    install_deps
    lint
    typecheck
    security
    test_suite
    providers_static
    ;;
  install)
    install_deps
    ;;
  lint)
    install_deps
    lint
    ;;
  typecheck)
    install_deps
    typecheck
    ;;
  security)
    install_deps
    security
    ;;
  test)
    install_deps
    test_suite
    ;;
  providers-static)
    providers_static
    ;;
  -h|--help|help)
    usage
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac
