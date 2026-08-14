"""Tests for ccusage provider schema parsing."""

import json
import subprocess
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from usage_pulse.providers.ccusage import CcusageProvider


def _mock_run(payload: dict, returncode: int = 0, stderr: str = ""):
    result = MagicMock()
    result.stdout = json.dumps(payload)
    result.returncode = returncode
    result.stderr = stderr
    return result


def test_fetch_today_selects_matching_period_and_total_cost():
    payload = {
        "daily": [
            {"period": "2026-06-18", "totalCost": 1, "totalTokens": 10},
            {
                "period": "2026-06-19",
                "totalCost": 12.5,
                "totalTokens": 123_456,
                "inputTokens": 100,
                "outputTokens": 200,
                "cacheReadTokens": 300,
                "cacheCreationTokens": 400,
                "modelBreakdowns": [
                    {
                        "modelName": "gpt-5.5",
                        "cost": 10.0,
                        "inputTokens": 50,
                        "outputTokens": 60,
                        "cacheReadTokens": 70,
                        "cacheCreationTokens": 80,
                    }
                ],
            },
        ]
    }

    provider = CcusageProvider(bunx_path="ccusage")
    with (
        patch("subprocess.run", return_value=_mock_run(payload)),
        patch("usage_pulse.providers.ccusage.date") as date_mock,
    ):
        date_mock.today.return_value.isoformat.return_value = "2026-06-19"
        data = provider.fetch_today()

    assert data is not None
    assert data.date == "2026-06-19"
    assert data.cost_usd == pytest.approx(12.5)
    assert data.total_tokens == 123_456
    assert data.model_breakdowns[0].total_tokens == 260


def test_fetch_today_falls_back_to_latest_period_when_today_missing():
    payload = {
        "daily": [
            {"period": "2026-06-17", "totalCost": 1},
            {"period": "2026-06-18", "totalCost": 2},
        ]
    }

    provider = CcusageProvider(bunx_path="ccusage")
    with (
        patch("subprocess.run", return_value=_mock_run(payload)),
        patch("usage_pulse.providers.ccusage.date") as date_mock,
    ):
        date_mock.today.return_value.isoformat.return_value = "2026-06-19"
        data = provider.fetch_today()

    assert data is not None
    assert data.date == "2026-06-18"
    assert data.cost_usd == pytest.approx(2)


def test_fetch_today_returns_none_on_nonzero_exit():
    provider = CcusageProvider(bunx_path="ccusage")
    with patch("subprocess.run", return_value=_mock_run({}, returncode=1)):
        assert provider.fetch_today() is None


@pytest.mark.parametrize(
    ("run_kwargs", "expected"),
    [
        ({"return_value": _mock_run({}, returncode=1, stderr="boom")}, "exit 1: boom"),
        (
            {"side_effect": subprocess.TimeoutExpired(cmd="ccusage", timeout=30)},
            "timeout after 30s",
        ),
        ({"side_effect": FileNotFoundError()}, "command not found: ccusage"),
        ({"return_value": _mock_run({})}, "no daily entries"),
        ({"return_value": _mock_run({"daily": ["not-a-dict"]})}, "no usable daily entry"),
    ],
)
def test_fetch_today_records_failure_reason(run_kwargs, expected):
    provider = CcusageProvider(bunx_path="ccusage")
    with patch("subprocess.run", **run_kwargs):
        assert provider.fetch_today() is None
    assert provider.last_error == expected


def test_fetch_today_records_invalid_json():
    result = MagicMock()
    result.returncode = 0
    result.stdout = "not json"
    provider = CcusageProvider(bunx_path="ccusage")
    with patch("subprocess.run", return_value=result):
        assert provider.fetch_today() is None
    assert provider.last_error is not None
    assert provider.last_error.startswith("invalid JSON:")


def test_fetch_today_clears_stale_failure_reason():
    provider = CcusageProvider(bunx_path="ccusage")
    with patch("subprocess.run", return_value=_mock_run({}, returncode=1, stderr="boom")):
        provider.fetch_today()
    assert provider.last_error == "exit 1: boom"

    payload = {"daily": [{"period": date.today().isoformat(), "totalCost": 1, "totalTokens": 10}]}
    with patch("subprocess.run", return_value=_mock_run(payload)):
        assert provider.fetch_today() is not None
    assert provider.last_error is None


def test_provider_prefers_direct_ccusage_binary():
    def fake_which(name):
        if name == "ccusage":
            return "/usr/local/bin/ccusage"
        if name == "bunx":
            return "/usr/local/bin/bunx"
        return None

    with patch("shutil.which", side_effect=fake_which):
        provider = CcusageProvider()

    assert provider.command == ["/usr/local/bin/ccusage"]
