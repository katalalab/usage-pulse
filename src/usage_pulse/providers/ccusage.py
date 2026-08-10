"""ccusage provider: fetches AI usage via `ccusage daily --json`."""

import json
import shutil
import subprocess
from datetime import UTC, date, datetime
from typing import Any

from .base import ModelBreakdown, UsageData

# Short display names for known models (update when adding providers)
MODEL_SHORT = {
    # Claude
    "claude-opus-4-8": "Op4.8",
    "claude-sonnet-4-6": "So4.6",
    "claude-haiku-4-5": "Ha4.5",
    "claude-fable-5": "Fb5",
    "claude-3.5-sonnet": "S3.5",
    # OpenAI / Codex
    "gpt-5.5": "GP5.5",
    "gpt-4o": "GP4o",
    "gpt-4o-mini": "4oMini",
    "gpt-4.1": "GP4.1",
    "o3": "O3",
    "o4-mini": "O4m",
    "codex-auto-review": "CXRev",
    # Gemini
    "gemini-2.5-pro": "Gm2.5",
    "gemini-2.5-flash": "Gm2.5F",
    "gemini-2.0-flash": "Gm2F",
    # Qwen (Amp / OpenCode / Qwen provider)
    "qwen2.5-coder-32b-instruct": "Qw2.5",
    "qwen-plus": "QwPls",
    "qwen-max": "QwMax",
    # Kimi / Moonshot
    "kimi-k2": "KimiK2",
    "moonshot-v1-8k": "Moon8k",
    # Hermes (Nous Research via various providers)
    "hermes-3-llama-3.1-70b": "Hrm70",
}


def _model_short(name: str) -> str:
    return MODEL_SHORT.get(name, name[:6])


class CcusageProvider:
    """Fetch usage data via ccusage CLI (cross-platform, background-safe)."""

    def __init__(self, bunx_path: str | None = None, timeout: int = 30):
        if bunx_path is not None:
            self.command = [bunx_path, "ccusage"]
        elif ccusage := shutil.which("ccusage"):
            self.command = [ccusage]
        else:
            self.command = [shutil.which("bunx") or "bunx", "ccusage"]
        self.timeout = timeout
        # fetch_today() has five distinct failure modes that all return None. The launchd
        # sync job's only signal is one constant stderr line, so without this the reason
        # for a failed run is unrecoverable after the fact.
        self.last_error: str | None = None

    @staticmethod
    def _as_float(value: Any) -> float:
        try:
            return float(value or 0)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _as_int(value: Any) -> int:
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _entry_date(entry: dict[str, Any]) -> str:
        return str(entry.get("period") or entry.get("date") or "")

    def _select_day(self, daily: list[dict[str, Any]]) -> dict[str, Any] | None:
        if not daily:
            return None

        today = date.today().isoformat()
        for entry in daily:
            if self._entry_date(entry) == today:
                return entry

        dated = [entry for entry in daily if self._entry_date(entry)]
        if dated:
            return max(dated, key=self._entry_date)
        return daily[-1]

    def _parse_day(self, entry: dict[str, Any]) -> UsageData:
        breakdowns = [
            ModelBreakdown(
                model_name=str(m.get("modelName", "unknown")),
                cost_usd=self._as_float(m.get("cost")),
                input_tokens=self._as_int(m.get("inputTokens")),
                output_tokens=self._as_int(m.get("outputTokens")),
                cache_read_tokens=self._as_int(m.get("cacheReadTokens")),
                cache_creation_tokens=self._as_int(m.get("cacheCreationTokens")),
            )
            for m in entry.get("modelBreakdowns", [])
            if isinstance(m, dict)
        ]

        total_tokens = entry.get("totalTokens")
        return UsageData(
            date=self._entry_date(entry) or datetime.now(UTC).strftime("%Y-%m-%d"),
            cost_usd=self._as_float(entry.get("totalCost", entry.get("cost"))),
            input_tokens=self._as_int(entry.get("inputTokens")),
            output_tokens=self._as_int(entry.get("outputTokens")),
            cache_read_tokens=self._as_int(entry.get("cacheReadTokens")),
            cache_creation_tokens=self._as_int(entry.get("cacheCreationTokens")),
            total_tokens_reported=self._as_int(total_tokens) if total_tokens is not None else None,
            model_breakdowns=breakdowns,
            source="ccusage",
            fetched_at=datetime.now(UTC),
        )

    def fetch_today(self) -> UsageData | None:
        self.last_error = None
        try:
            result = subprocess.run(
                [*self.command, "daily", "--json"],
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
            if result.returncode != 0:
                self.last_error = f"exit {result.returncode}: {result.stderr.strip()[:200]}"
                return None
            raw = result.stdout.strip()
            if not raw:
                self.last_error = "empty stdout"
                return None
            data = json.loads(raw)
        except subprocess.TimeoutExpired:
            self.last_error = f"timeout after {self.timeout}s"
            return None
        except json.JSONDecodeError as exc:
            self.last_error = f"invalid JSON: {exc}"
            return None
        except FileNotFoundError:
            self.last_error = f"command not found: {self.command[0]}"
            return None

        daily = data.get("daily", [])
        if not daily:
            self.last_error = "no daily entries"
            return None

        today = self._select_day([entry for entry in daily if isinstance(entry, dict)])
        if today is None:
            self.last_error = "no usable daily entry"
            return None
        return self._parse_day(today)

    def format_tmux(self, data: UsageData, cost_threshold: float = 50.0) -> str:
        """Return tmux-colored status string."""
        cost = data.cost_usd
        tokens_k = data.total_tokens // 1000

        if cost >= cost_threshold:
            color = "#[fg=red,bold]"
        elif cost >= cost_threshold * 0.7:
            color = "#[fg=yellow]"
        elif cost >= cost_threshold * 0.3:
            color = "#[fg=cyan]"
        else:
            color = "#[fg=green]"

        top = [_model_short(m.model_name) for m in data.top_models[:2] if m.cost_usd > 0]
        model_str = "+".join(top)

        parts = [f"{color}${cost:.2f}#[default]"]
        if tokens_k > 0:
            parts.append(f"{tokens_k}K")
        if model_str:
            parts.append(f"[{model_str}]")
        return " ".join(parts)
