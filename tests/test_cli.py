"""Tests for CLI machine-readable commands."""

import json
import sys
from datetime import UTC, datetime

from click.testing import CliRunner

from usage_pulse.cli import main
from usage_pulse.providers.base import ModelBreakdown, UsageData


def _usage_data() -> UsageData:
    return UsageData(
        date="2026-06-19",
        cost_usd=12.345678,
        input_tokens=100,
        output_tokens=200,
        cache_read_tokens=300,
        cache_creation_tokens=400,
        total_tokens_reported=1234,
        model_breakdowns=[
            ModelBreakdown(
                model_name="gpt-5.5",
                cost_usd=12.0,
                input_tokens=100,
                output_tokens=200,
                cache_read_tokens=300,
                cache_creation_tokens=400,
            )
        ],
        source="ccusage",
        fetched_at=datetime(2026, 6, 19, tzinfo=UTC),
    )


def test_summary_json(monkeypatch):
    class FakeCcusageProvider:
        def fetch_today(self):
            return _usage_data()

    class FakeCodexbarProvider:
        available = False

    monkeypatch.setattr("usage_pulse.cli.CcusageProvider", FakeCcusageProvider)
    monkeypatch.setattr("usage_pulse.cli.CodexbarProvider", FakeCodexbarProvider)

    result = CliRunner().invoke(main, ["summary", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["date"] == "2026-06-19"
    assert payload["today"]["cost_usd"] == 12.345678
    assert payload["today"]["tokens"] == 1234
    assert payload["today"]["top_models"][0]["model"] == "gpt-5.5"
    assert payload["recommendation"]["model"]


def test_summary_text_renders_unicode(monkeypatch):
    """Human-readable summary prints the em-dash/emoji path that crashed on cp932."""

    class FakeCcusageProvider:
        def fetch_today(self):
            return _usage_data()

    class FakeCodexbarProvider:
        available = False

    monkeypatch.setattr("usage_pulse.cli.CcusageProvider", FakeCcusageProvider)
    monkeypatch.setattr("usage_pulse.cli.CodexbarProvider", FakeCodexbarProvider)

    result = CliRunner().invoke(main, ["summary"])

    assert result.exit_code == 0
    assert "—" in result.output


def test_sync_quiet_writes_state_without_output(monkeypatch, tmp_path):
    class FakeCcusageProvider:
        def fetch_today(self):
            return _usage_data()

    class FakeNotifier:
        def send_once(self, *_args, **_kwargs):
            return True

        def reset(self, *_args, **_kwargs):
            return None

    state_file = tmp_path / "current.json"
    monkeypatch.setattr("usage_pulse.cli.CcusageProvider", FakeCcusageProvider)
    monkeypatch.setattr("usage_pulse.cli.Notifier", FakeNotifier)
    monkeypatch.setattr("usage_pulse.handshake.STATE_FILE", state_file)
    monkeypatch.setattr("usage_pulse.handshake.STATE_DIR", tmp_path)
    monkeypatch.setattr("usage_pulse.cli.STATE_FILE", state_file)

    result = CliRunner().invoke(main, ["sync", "--quiet"])

    assert result.exit_code == 0
    assert result.output == ""
    assert state_file.exists()


def test_sync_json(monkeypatch, tmp_path):
    class FakeCcusageProvider:
        def fetch_today(self):
            return _usage_data()

    class FakeNotifier:
        def send_once(self, *_args, **_kwargs):
            return True

        def reset(self, *_args, **_kwargs):
            return None

    state_file = tmp_path / "current.json"
    monkeypatch.setattr("usage_pulse.cli.CcusageProvider", FakeCcusageProvider)
    monkeypatch.setattr("usage_pulse.cli.Notifier", FakeNotifier)
    monkeypatch.setattr("usage_pulse.handshake.STATE_FILE", state_file)
    monkeypatch.setattr("usage_pulse.handshake.STATE_DIR", tmp_path)
    monkeypatch.setattr("usage_pulse.cli.STATE_FILE", state_file)

    result = CliRunner().invoke(main, ["sync", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["today"]["tokens"] == 1234
    assert state_file.exists()


def test_doctor_json_skip_live(monkeypatch):
    class FakeCcusageProvider:
        command = [sys.executable]

    class FakeCodexbarProvider:
        available = False
        timeout = 4

    monkeypatch.setattr("usage_pulse.cli.CcusageProvider", FakeCcusageProvider)
    monkeypatch.setattr("usage_pulse.cli.CodexbarProvider", FakeCodexbarProvider)

    result = CliRunner().invoke(main, ["doctor", "--json", "--skip-live"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["status"] == "ok"
    assert {check["name"] for check in payload["checks"]} >= {
        "python",
        "ccusage_command",
        "codexbar",
        "ccusage_live",
    }
    assert next(c for c in payload["checks"] if c["name"] == "ccusage_live")["status"] == "warn"


def test_doctor_fails_when_ccusage_missing(monkeypatch):
    class FakeCcusageProvider:
        command = ["/definitely/missing/ccusage"]

    class FakeCodexbarProvider:
        available = False
        timeout = 4

    monkeypatch.setattr("usage_pulse.cli.CcusageProvider", FakeCcusageProvider)
    monkeypatch.setattr("usage_pulse.cli.CodexbarProvider", FakeCodexbarProvider)

    result = CliRunner().invoke(main, ["doctor", "--json", "--skip-live"])

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["status"] == "fail"
    assert next(c for c in payload["checks"] if c["name"] == "ccusage_command")["status"] == "fail"


def test_summary_exits_nonzero_when_usage_missing(monkeypatch):
    class FakeCcusageProvider:
        last_error = "timeout after 30s"

        def fetch_today(self):
            return None

    monkeypatch.setattr("usage_pulse.cli.CcusageProvider", FakeCcusageProvider)

    result = CliRunner().invoke(main, ["summary", "--json"])

    assert result.exit_code == 1
    assert "could not fetch usage data" in result.output
    assert "timeout after 30s" in result.output
