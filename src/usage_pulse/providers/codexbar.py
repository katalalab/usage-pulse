"""CodexBar provider: reads rate-window data via per-provider CLI calls.

Root-cause analysis of the TTY hang (issue #1329):
  `codexbar usage --json` (all providers) hangs without a TTY because the
  `codex` provider defaults to --source auto, which attempts browser OAuth and
  prompts interactively.

Fix: call each supported provider individually. Per-provider calls that use
web cookies or the CLI binary work without any TTY. The codex provider must
use --source cli to skip the web OAuth flow.

Confirmed background-safe providers (tested 2026-06-19):
  claude, gemini, cursor, opencodego  -- exit 0, no TTY needed
  codex --source cli                  -- exit 0, no TTY needed
  amp                                 -- exit 1 (no cookie), but non-blocking
"""

import json
import os
import platform
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor

from .base import RateWindow, UsageData

_DEFAULT_PROVIDER_NAMES = "claude,codex,cursor,opencodego,gemini,antigravity,copilot"

# Providers to query and their display labels.
_PROVIDERS: dict[str, tuple[str, list[str]]] = {
    # (provider_name, display_label, extra_flags)
    "claude": ("CC", []),
    "codex": ("CX", ["--source", "cli"]),  # --source cli avoids browser OAuth hang
    "cursor": ("CU", []),
    "opencodego": ("OC", []),
    "gemini": ("GM", []),
    "antigravity": ("AG", []),
    "copilot": ("GH", []),
}


def _default_timeout() -> int:
    try:
        return max(1, int(os.environ.get("USAGE_PULSE_CODEXBAR_TIMEOUT", "8")))
    except ValueError:
        return 8


def _selected_providers() -> list[tuple[str, str, list[str]]]:
    configured = os.environ.get("USAGE_PULSE_CODEXBAR_PROVIDERS", _DEFAULT_PROVIDER_NAMES)
    out = []
    for raw_name in configured.split(","):
        name = raw_name.strip().lower()
        if not name or name not in _PROVIDERS:
            continue
        label, extra = _PROVIDERS[name]
        out.append((name, label, extra))
    return out


def _as_int(value, default: int) -> int:
    try:
        return int(value if value is not None else default)
    except (TypeError, ValueError):
        return default


def _error_message(error: object) -> str | None:
    if not isinstance(error, dict):
        return None
    for key in ("message", "detail", "code"):
        value = error.get(key)
        if value:
            return str(value)
    return None


class CodexbarProvider:
    """Fetch rate-window data from CodexBar CLI without TTY.

    Uses per-provider calls instead of `codexbar usage --json` (all-providers)
    to avoid the codex-provider TTY hang. Works on macOS; returns {} elsewhere.
    """

    def __init__(self, timeout: int | None = None):
        self.timeout = timeout or _default_timeout()
        self._binary: str = shutil.which("codexbar") or "codexbar"

    @property
    def available(self) -> bool:
        return platform.system() == "Darwin" and shutil.which("codexbar") is not None

    @staticmethod
    def _account_index(item: dict) -> str | None:
        usage = item.get("usage", {})
        if isinstance(usage, dict):
            identity = usage.get("identity") or {}
            value = (
                identity.get("accountOrganization")
                or usage.get("accountOrganization")
                or identity.get("loginMethod")
                or usage.get("loginMethod")
            )
            if value:
                return str(value)
        account = item.get("account")
        if isinstance(account, dict):
            value = account.get("label") or account.get("name") or account.get("id")
            if value and "@" not in str(value):
                return str(value)
        source = item.get("source")
        return str(source) if source else None

    @staticmethod
    def _parse_items(raw: str) -> list:
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass

        for line in reversed(raw.splitlines()):
            line = line.strip()
            if not line.startswith("["):
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, list):
                return parsed
        return []

    def _fetch_status(self, provider: str, extra_flags: list[str]) -> dict:
        """Run codexbar for one provider and return a sanitized diagnostic record."""
        cmd = [self._binary, "usage", "--provider", provider, "--json-only"] + extra_flags
        if provider == "codex" and os.environ.get("USAGE_PULSE_CODEXBAR_ALL_ACCOUNTS", "1") == "1":
            cmd.append("--all-accounts")
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
            raw = result.stdout.strip()
            if not raw:
                detail = result.stderr.strip().splitlines()[0] if result.stderr else "no stdout"
                return {
                    "provider": provider,
                    "status": "warn",
                    "detail": detail,
                    "item_count": 0,
                    "items": [],
                }
            items = self._parse_items(raw)
            if not items:
                return {
                    "provider": provider,
                    "status": "warn",
                    "detail": "no JSON array in codexbar output",
                    "item_count": 0,
                    "items": [],
                }
            successful = [item for item in items if isinstance(item, dict) and "error" not in item]
            if not successful:
                # detail は 147 行目で str として束縛済み。ここは None を取りうるので
                # 別名にする（同じ名前へ str | None を入れると mypy が落ちる）。
                error_detail: str | None = None
                for item in items:
                    if isinstance(item, dict):
                        error_detail = _error_message(item.get("error"))
                    if error_detail:
                        break
                return {
                    "provider": provider,
                    "status": "warn",
                    "detail": error_detail or f"codexbar exited {result.returncode}",
                    "item_count": 0,
                    "items": [],
                }
            return {
                "provider": provider,
                "status": "ok",
                "detail": f"{len(successful)} account(s)",
                "item_count": len(successful),
                "items": successful,
            }
        except subprocess.TimeoutExpired:
            return {
                "provider": provider,
                "status": "warn",
                "detail": f"timed out after {self.timeout}s",
                "item_count": 0,
                "items": [],
            }
        except (json.JSONDecodeError, FileNotFoundError) as exc:
            return {
                "provider": provider,
                "status": "warn",
                "detail": exc.__class__.__name__,
                "item_count": 0,
                "items": [],
            }

    def _fetch_one(self, provider: str, extra_flags: list[str]) -> list[dict] | None:
        """Run codexbar for one provider; return parsed success items or None."""
        status = self._fetch_status(provider, extra_flags)
        if status["status"] != "ok":
            return None
        return status["items"]

    def fetch_provider_statuses(self) -> list[dict]:
        """Return sanitized per-provider CodexBar diagnostics for doctor output."""
        if not self.available:
            return []

        providers = _selected_providers()
        with ThreadPoolExecutor(max_workers=max(1, len(providers))) as pool:
            futures = {
                provider: pool.submit(self._fetch_status, provider, extra)
                for provider, _label, extra in providers
            }
            statuses = []
            for provider, label, _extra in providers:
                try:
                    status = futures[provider].result()
                except Exception as exc:
                    status = {
                        "provider": provider,
                        "status": "warn",
                        "detail": exc.__class__.__name__,
                        "item_count": 0,
                        "items": [],
                    }
                statuses.append(
                    {
                        "provider": provider,
                        "label": label,
                        "status": status["status"],
                        "detail": status["detail"],
                        "item_count": status["item_count"],
                    }
                )
        return statuses

    def fetch_rate_windows(self) -> dict[str, dict]:
        """Return {provider: {label, primary_pct, secondary_pct, ...}} for each live provider."""
        if not self.available:
            return {}

        out = {}
        providers = _selected_providers()
        with ThreadPoolExecutor(max_workers=max(1, len(providers))) as pool:
            futures = {
                provider: pool.submit(self._fetch_one, provider, extra)
                for provider, _label, extra in providers
            }

            ordered_items = []
            for provider, label, _extra in providers:
                try:
                    items = futures[provider].result()
                except Exception:
                    items = None
                ordered_items.append((provider, label, items or []))

        for provider, label, items in ordered_items:
            seen = 0
            for item in items:
                usage = item.get("usage", {})
                if not usage:
                    continue
                primary = usage.get("primary") or {}
                secondary = usage.get("secondary") or {}
                seen += 1
                key = provider if seen == 1 else f"{provider}#{seen}"
                account_label = self._account_index(item)
                provider_cost = usage.get("providerCost") or {}
                credit_limit = (item.get("credits") or {}).get("codexCreditLimit") or {}
                out[key] = {
                    "label": label if seen == 1 else f"{label}{seen}",
                    "provider": provider,
                    "account": account_label,
                    "primary_pct": float(primary.get("usedPercent", 0)),
                    "secondary_pct": float(secondary.get("usedPercent", 0)),
                    "primary_resets_at": primary.get("resetsAt"),
                    "primary_reset_desc": primary.get("resetDescription"),
                    "primary_window_minutes": _as_int(primary.get("windowMinutes"), 300),
                    "provider_cost_used": provider_cost.get("used"),
                    "provider_cost_limit": provider_cost.get("limit"),
                    "provider_cost_period": provider_cost.get("period"),
                    "credit_used": credit_limit.get("used"),
                    "credit_limit": credit_limit.get("limit"),
                    "credit_remaining": credit_limit.get("remaining"),
                    "credit_remaining_pct": credit_limit.get("remainingPercent"),
                    "credit_resets_at": credit_limit.get("resetsAt"),
                    "source": item.get("source"),
                }
        return out

    def format_tmux(self, windows: dict) -> str:
        """Format rate windows for tmux status-right."""
        parts = []
        for _provider, info in windows.items():
            pct = int(info["primary_pct"])
            label = info["label"]
            if pct >= 90:
                color = "#[fg=red,bold]"
            elif pct >= 80:
                color = "#[fg=yellow]"
            elif pct >= 50:
                color = "#[fg=cyan]"
            else:
                color = "#[fg=green]"
            parts.append(f"{color}{label}:{pct}%#[default]")
        return " ".join(parts)

    def enrich_usage_data(self, data: UsageData, windows: dict) -> UsageData:
        """Merge CodexBar rate windows into a UsageData object."""
        claude = windows.get("claude", {})
        if claude:
            data.rate_windows["primary"] = RateWindow(
                window_minutes=claude.get("primary_window_minutes", 300),
                used_percent=claude.get("primary_pct", 0),
                resets_at=claude.get("primary_resets_at"),
                reset_description=claude.get("primary_reset_desc"),
            )
            data.rate_windows["secondary"] = RateWindow(
                window_minutes=10080,
                used_percent=claude.get("secondary_pct", 0),
            )
        return data
