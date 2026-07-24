"""Tests for CodexbarProvider."""

import json
from unittest.mock import MagicMock, patch

import pytest

from usage_pulse.providers.codexbar import CodexbarProvider


def _mock_run(stdout: str, returncode: int = 0):
    result = MagicMock()
    result.stdout = stdout
    result.returncode = returncode
    return result


CLAUDE_JSON = json.dumps(
    [
        {
            "provider": "claude",
            "source": "web",
            "usage": {
                "primary": {
                    "windowMinutes": 300,
                    "usedPercent": 42.5,
                    "resetsAt": "2026-06-19T12:00:00Z",
                    "resetDescription": "Resets at noon",
                },
                "secondary": {
                    "windowMinutes": 10080,
                    "usedPercent": 30.0,
                },
            },
        }
    ]
)

ERROR_JSON = json.dumps([{"provider": "amp", "source": "auto", "error": {"message": "No cookie"}}])


@pytest.fixture()
def provider():
    return CodexbarProvider(timeout=5)


def test_fetch_one_parses_claude(provider):
    with patch("subprocess.run", return_value=_mock_run(CLAUDE_JSON)):
        items = provider._fetch_one("claude", [])
    assert items is not None
    assert items[0]["provider"] == "claude"
    assert items[0]["usage"]["primary"]["usedPercent"] == pytest.approx(42.5)


def test_fetch_one_returns_none_on_error_json(provider):
    with patch("subprocess.run", return_value=_mock_run(ERROR_JSON, returncode=1)):
        item = provider._fetch_one("amp", [])
    assert item is None


def test_fetch_status_reports_error_message(provider):
    with patch("subprocess.run", return_value=_mock_run(ERROR_JSON, returncode=1)):
        status = provider._fetch_status("amp", [])
    assert status["status"] == "warn"
    assert status["item_count"] == 0
    assert status["detail"] == "No cookie"


def test_fetch_one_returns_none_on_empty(provider):
    with patch("subprocess.run", return_value=_mock_run("")):
        item = provider._fetch_one("claude", [])
    assert item is None


def test_fetch_one_parses_json_after_codex_stderr_lines(provider):
    mixed = "\n".join(
        [
            '[codex stderr] {"level":"ERROR","fields":{"message":"noise"}}',
            CLAUDE_JSON,
        ]
    )
    with patch("subprocess.run", return_value=_mock_run(mixed)):
        items = provider._fetch_one("claude", [])
    assert items is not None
    assert items[0]["provider"] == "claude"


def test_default_timeout_can_be_overridden(monkeypatch):
    monkeypatch.setenv("USAGE_PULSE_CODEXBAR_TIMEOUT", "2")
    assert CodexbarProvider().timeout == 2


def test_default_timeout_ignores_invalid_env(monkeypatch):
    monkeypatch.setenv("USAGE_PULSE_CODEXBAR_TIMEOUT", "not-a-number")
    assert CodexbarProvider().timeout == 8


def test_fetch_rate_windows_aggregates(provider):
    def fake_run(cmd, **kwargs):
        provider_arg = cmd[cmd.index("--provider") + 1]
        if provider_arg == "claude":
            return _mock_run(CLAUDE_JSON)
        return _mock_run(ERROR_JSON, returncode=1)

    with (
        patch("subprocess.run", side_effect=fake_run),
        patch("platform.system", return_value="Darwin"),
        patch("shutil.which", return_value="/usr/bin/codexbar"),
    ):
        windows = provider.fetch_rate_windows()

    assert "claude" in windows
    assert windows["claude"]["primary_pct"] == pytest.approx(42.5)
    assert windows["claude"]["secondary_pct"] == pytest.approx(30.0)
    assert windows["claude"]["label"] == "CC"


def test_fetch_provider_statuses_returns_sanitized_records(provider):
    def fake_run(cmd, **kwargs):
        provider_arg = cmd[cmd.index("--provider") + 1]
        if provider_arg == "claude":
            return _mock_run(CLAUDE_JSON)
        return _mock_run(ERROR_JSON, returncode=1)

    with (
        patch("subprocess.run", side_effect=fake_run),
        patch("platform.system", return_value="Darwin"),
        patch("shutil.which", return_value="/usr/bin/codexbar"),
        patch.dict("os.environ", {"USAGE_PULSE_CODEXBAR_PROVIDERS": "claude,opencodego"}),
    ):
        statuses = provider.fetch_provider_statuses()

    assert statuses == [
        {
            "provider": "claude",
            "label": "CC",
            "status": "ok",
            "detail": "1 account(s)",
            "item_count": 1,
        },
        {
            "provider": "opencodego",
            "label": "OC",
            "status": "warn",
            "detail": "No cookie",
            "item_count": 0,
        },
    ]


def test_fetch_rate_windows_keeps_multiple_codex_accounts(provider):
    codex_json = json.dumps(
        [
            {
                "provider": "codex",
                "source": "codex-cli",
                "usage": {
                    "loginMethod": "pro",
                    "primary": {"usedPercent": 10.0, "windowMinutes": 300},
                    "secondary": {"usedPercent": 20.0},
                },
            },
            {
                "provider": "codex",
                "source": "web",
                "credits": {
                    "codexCreditLimit": {
                        "used": 900.0,
                        "limit": 1000.0,
                        "remaining": 100.0,
                        "remainingPercent": 10.0,
                        "resetsAt": "2026-08-01T00:00:00Z",
                    }
                },
                "usage": {
                    "loginMethod": "team",
                    "primary": {"usedPercent": 30.0, "windowMinutes": 300},
                    "secondary": {"usedPercent": 40.0},
                },
            },
        ]
    )

    def fake_run(cmd, **kwargs):
        assert "--all-accounts" in cmd
        return _mock_run(codex_json)

    with (
        patch("subprocess.run", side_effect=fake_run),
        patch("platform.system", return_value="Darwin"),
        patch("shutil.which", return_value="/usr/bin/codexbar"),
        patch.dict("os.environ", {"USAGE_PULSE_CODEXBAR_PROVIDERS": "codex"}),
    ):
        windows = provider.fetch_rate_windows()

    assert windows["codex"]["label"] == "CX"
    assert windows["codex"]["account"] == "pro"
    assert windows["codex#2"]["label"] == "CX2"
    assert windows["codex#2"]["account"] == "team"
    assert windows["codex#2"]["primary_pct"] == pytest.approx(30.0)
    assert windows["codex#2"]["credit_remaining_pct"] == pytest.approx(10.0)


def test_format_tmux_colors(provider):
    windows = {
        "claude": {"label": "CC", "primary_pct": 95.0, "secondary_pct": 30.0},
        "gemini": {"label": "GM", "primary_pct": 10.0, "secondary_pct": 0.0},
    }
    out = provider.format_tmux(windows)
    assert "red" in out  # 95% → red
    assert "green" in out  # 10% → green
    assert "CC:95%" in out
    assert "GM:10%" in out


def test_enrich_usage_data(provider):
    from usage_pulse.providers.base import UsageData

    data = UsageData(date="2026-06-19", cost_usd=5.0, input_tokens=10000, output_tokens=2000)
    windows = {
        "claude": {
            "label": "CC",
            "primary_pct": 42.5,
            "secondary_pct": 30.0,
            "primary_resets_at": "2026-06-19T12:00:00Z",
            "primary_reset_desc": "Resets at noon",
            "primary_window_minutes": 300,
        }
    }
    data = provider.enrich_usage_data(data, windows)
    assert data.primary_rate_pct == pytest.approx(42.5)
    assert data.weekly_rate_pct == pytest.approx(30.0)
