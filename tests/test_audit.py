"""Tests for read-only AI audit collection."""

import json

from click.testing import CliRunner

from usage_pulse.audit import _redact_command, analyze_bottlenecks, collect_tools
from usage_pulse.cli import main


def test_collect_tools_summarizes_safe_config_without_secret_values(tmp_path, monkeypatch):
    config_dir = tmp_path / ".codex"
    config_dir.mkdir()
    (config_dir / "config.toml").write_text(
        'model = "gpt-5.5"\napi_key = "sk-secret"\napproval_policy = "never"\n',
        encoding="utf-8",
    )

    monkeypatch.setattr("usage_pulse.audit.TOOL_SPECS", ())
    from usage_pulse import audit

    monkeypatch.setattr(
        audit,
        "TOOL_SPECS",
        (
            audit.ToolSpec(
                "codex",
                "definitely-missing-codex",
                ("--version",),
                (".codex/config.toml",),
            ),
        ),
    )

    tools = collect_tools(cwd=tmp_path)

    summary = tools[0]["configs"][0]["summary"]
    assert summary == {"model": "gpt-5.5", "approval_policy": "never"}
    assert "sk-secret" not in json.dumps(tools)


def test_collect_tools_accepts_jsonc_trailing_commas(tmp_path, monkeypatch):
    config_path = tmp_path / "opencode.jsonc"
    config_path.write_text(
        """
        {
          // local model choice
          "model": "opencode/test-model",
        }
        """,
        encoding="utf-8",
    )

    from usage_pulse import audit

    monkeypatch.setattr(
        audit,
        "TOOL_SPECS",
        (
            audit.ToolSpec(
                "opencode",
                "definitely-missing-opencode",
                ("--version",),
                ("opencode.jsonc",),
            ),
        ),
    )

    tools = collect_tools(cwd=tmp_path)

    assert tools[0]["configs"][0]["status"] == "ok"
    assert tools[0]["configs"][0]["summary"] == {"model": "opencode/test-model"}


def test_redact_command_hides_session_and_secret_arguments():
    command = 'claude --session-id abc123 --settings {"hooks":[{"command":"secret"}]} token=abc'

    redacted = _redact_command(command)

    assert "abc123" not in redacted
    assert '{"hooks"' not in redacted
    assert "token=abc" not in redacted
    assert "[redacted]" in redacted


def test_audit_json_skip_live(monkeypatch):
    monkeypatch.setattr(
        "usage_pulse.cli.collect_audit",
        lambda skip_live, include_processes: {
            "schema_version": 1,
            "generated_at": "2026-06-21T00:00:00+00:00",
            "host": {"hostname": "test-host"},
            "usage": {"status": "skipped"},
            "tools": [{"name": "codex", "available": True}],
            "tmux": {"status": "ok", "ai_pane_count": 0},
            "bottlenecks": [],
        },
    )

    result = CliRunner().invoke(main, ["audit", "--json", "--skip-live"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["schema_version"] == 1
    assert payload["usage"]["status"] == "skipped"


def test_fleet_audit_json(monkeypatch):
    def fake_remote(host, remote_command, timeout):
        return {
            "host": host,
            "status": "ok",
            "elapsed_ms": 1,
            "audit": {"host": {"hostname": f"{host}.local"}},
        }

    monkeypatch.setattr("usage_pulse.cli.run_remote_audit", fake_remote)

    result = CliRunner().invoke(
        main,
        ["fleet-audit", "--host", "home-mac-main", "--host", "nicolas2025", "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["status"] == "ok"
    assert [item["host"] for item in payload["results"]] == ["home-mac-main", "nicolas2025"]


def test_analyze_bottlenecks_detects_high_load_and_missing_usage():
    payload = {
        "host": {"cpu_count": 2, "load_average": {"available": True, "one": 5.0}},
        "tools": [{"name": "ccusage", "available": False}],
        "usage": {"status": "unavailable"},
        "processes": {"items": [{"pid": 123, "cpu_pct": 150.0, "command": "codex exec"}]},
        "tmux": {"ai_pane_count": 12},
    }

    findings = analyze_bottlenecks(payload)
    codes = {finding["code"] for finding in findings}

    assert codes >= {
        "host_load_high",
        "ccusage_missing",
        "usage_unavailable",
        "ai_process_cpu_high",
        "many_ai_tmux_panes",
    }
