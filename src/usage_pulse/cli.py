"""usage-pulse CLI entry point."""

import json
import os
import platform
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

import click

from .analysis.advisor import ModelAdvisor
from .analysis.roi import compute_roi, format_roi_table
from .display.notify import Notifier
from .handshake import STATE_FILE, write_state
from .providers.ccusage import CcusageProvider
from .providers.codexbar import CodexbarProvider


def _usage_payload(data, rec, windows=None) -> dict:
    return {
        "date": data.date,
        "source": data.source,
        "fetched_at": data.fetched_at.isoformat() if data.fetched_at else None,
        "today": {
            "cost_usd": round(data.cost_usd, 6),
            "tokens": data.total_tokens,
            "input_tokens": data.input_tokens,
            "output_tokens": data.output_tokens,
            "cache_read_tokens": data.cache_read_tokens,
            "cache_creation_tokens": data.cache_creation_tokens,
            "top_models": [
                {
                    "model": m.model_name,
                    "cost_usd": round(m.cost_usd, 6),
                    "tokens": m.total_tokens,
                    "input_tokens": m.input_tokens,
                    "output_tokens": m.output_tokens,
                    "cache_read_tokens": m.cache_read_tokens,
                    "cache_creation_tokens": m.cache_creation_tokens,
                }
                for m in data.top_models[:5]
                if m.cost_usd > 0
            ],
        },
        "rate_windows": {
            "claude_5min_pct": round(data.primary_rate_pct, 1),
            "claude_weekly_pct": round(data.weekly_rate_pct, 1),
            "providers": windows or {},
        },
        "recommendation": {
            "model": rec.model,
            "reason": rec.reason,
            "urgency": rec.urgency,
        },
    }


def _echo_json(payload: dict) -> None:
    click.echo(json.dumps(payload, ensure_ascii=False, indent=2))


def _gate_threshold(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except ValueError:
        return default


def _cache_paths() -> tuple[Path, Path]:
    cache_dir = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "usage-pulse"
    return cache_dir / "statusline", cache_dir / "statusline.time"


@click.group()
@click.version_option()
def main():
    """usage-pulse — AI tool usage monitor (Mac/Win/Linux)."""
    pass


@main.command()
@click.option(
    "--threshold",
    default=50.0,
    envvar="USAGE_PULSE_THRESHOLD",
    help="Daily cost threshold for color/alert (USD, default 50)",
)
@click.option("--no-cache", is_flag=True, help="Skip cache, fetch fresh data")
def statusline(threshold, no_cache):
    """Output tmux status-right string (cached, non-blocking)."""
    import time

    cache_file, cache_time_file = _cache_paths()
    cache_dir = cache_file.parent
    ttl = int(os.environ.get("USAGE_PULSE_CACHE_TTL", "60"))

    cache_dir.mkdir(parents=True, exist_ok=True)

    now = int(time.time())
    cached_time = 0
    if cache_time_file.exists():
        try:
            cached_time = int(cache_time_file.read_text().strip())
        except ValueError:
            pass

    if no_cache or (now - cached_time) >= ttl:
        # Refresh in background
        import subprocess

        subprocess.Popen(
            [
                sys.executable,
                "-m",
                "usage_pulse._refresh_worker",
                str(cache_file),
                str(cache_time_file),
                str(threshold),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

    # Return cached result immediately
    if cache_file.exists():
        print(cache_file.read_text().rstrip(), end="")
    sys.stdout.flush()


@main.command()
@click.option("--threshold", default=50.0, envvar="USAGE_PULSE_THRESHOLD")
@click.option("--json", "json_output", is_flag=True, help="Print machine-readable JSON")
@click.option("--quiet", is_flag=True, help="Suppress human-readable output")
def sync(threshold, json_output, quiet):
    """Update agent handshake state file with current usage."""
    provider = CcusageProvider()
    data = provider.fetch_today()
    if data is None:
        click.echo("Error: could not fetch usage data", err=True)
        sys.exit(1)

    advisor = ModelAdvisor()
    rec = advisor.recommend(data, threshold)
    write_state(data, rec)

    notifier = Notifier()
    if data.cost_usd >= threshold:
        notifier.send_once(
            "cost-threshold",
            "Usage Alert",
            f"Today: ${data.cost_usd:.2f} (threshold ${threshold:.0f})",
        )
    else:
        notifier.reset("cost-threshold")

    if json_output:
        _echo_json(_usage_payload(data, rec))
        return
    if quiet:
        return

    click.echo(f"Synced: ${data.cost_usd:.2f} / {data.total_tokens // 1000}K tokens")
    click.echo(f"Recommend: {rec.model} — {rec.reason}")
    click.echo(f"State: {STATE_FILE}")


@main.command()
@click.option("--threshold", default=50.0, envvar="USAGE_PULSE_THRESHOLD")
@click.option("--json", "json_output", is_flag=True, help="Print machine-readable JSON")
def summary(threshold, json_output):
    """Print today's usage summary."""
    ccusage = CcusageProvider()
    data = ccusage.fetch_today()
    if data is None:
        click.echo("Error: could not fetch usage data", err=True)
        sys.exit(1)

    # Enrich with real-time rate windows from CodexBar (TTY-free per-provider calls)
    cb = CodexbarProvider()
    if cb.available:
        windows = cb.fetch_rate_windows()
        data = cb.enrich_usage_data(data, windows)
    else:
        windows = {}

    advisor = ModelAdvisor()
    rec = advisor.recommend(data, threshold)

    if json_output:
        _echo_json(_usage_payload(data, rec, windows))
        return

    click.echo(f"\n{'=' * 50}")
    click.echo(f"  usage-pulse  —  {data.date}")
    click.echo(f"{'=' * 50}")
    click.echo(f"  Cost today:   ${data.cost_usd:.4f}")
    click.echo(f"  Tokens:       {data.total_tokens:,} ({data.total_tokens // 1000}K)")
    click.echo(f"  Input:        {data.input_tokens:,}")
    click.echo(f"  Output:       {data.output_tokens:,}")
    click.echo(f"  Cache read:   {data.cache_read_tokens:,}")
    click.echo(f"  5min rate:    {data.primary_rate_pct:.1f}%")
    click.echo(f"  Weekly rate:  {data.weekly_rate_pct:.1f}%")

    if windows:
        click.echo()
        click.echo("  Rate windows (CodexBar):")
        for prov, info in windows.items():
            click.echo(
                f"    {info['label']} {prov}: "
                f"primary={info['primary_pct']:.1f}% "
                f"secondary={info['secondary_pct']:.1f}%"
                + (f"  [{info['primary_reset_desc']}]" if info.get("primary_reset_desc") else "")
            )

    urgency_emoji = {"ok": "✅", "caution": "⚠️", "warning": "🟠", "critical": "🔴"}
    click.echo(f"\n  Recommended:  {urgency_emoji.get(rec.urgency, '')} {rec.model}")
    click.echo(f"  Reason:       {rec.reason}")
    click.echo(f"{'=' * 50}\n")


@main.command()
@click.option("--json", "json_output", is_flag=True, help="Print machine-readable JSON")
@click.option("--skip-live", is_flag=True, help="Skip live provider fetch checks")
def doctor(json_output, skip_live):
    """Diagnose local installation, providers, cache, and state paths."""
    checks = []

    def add(name: str, status: str, detail: str, **extra) -> None:
        checks.append({"name": name, "status": status, "detail": detail, **extra})

    add(
        "python",
        "ok" if sys.version_info >= (3, 11) else "fail",
        platform.python_version(),
    )

    ccusage = CcusageProvider()
    ccusage_exe = ccusage.command[0]
    add(
        "ccusage_command",
        "ok" if shutil.which(ccusage_exe) or Path(ccusage_exe).exists() else "fail",
        " ".join(ccusage.command),
    )

    codexbar = CodexbarProvider()
    add(
        "codexbar",
        "ok" if codexbar.available else "warn",
        shutil.which("codexbar") or "not available",
        timeout_seconds=codexbar.timeout,
    )

    cache_file, cache_time_file = _cache_paths()
    add("cache_path", "ok", str(cache_file), exists=cache_file.exists())
    add("cache_time_path", "ok", str(cache_time_file), exists=cache_time_file.exists())
    add("state_path", "ok", str(STATE_FILE), exists=STATE_FILE.exists())

    if skip_live:
        add("ccusage_live", "warn", "skipped")
    else:
        started = datetime.now(UTC)
        data = ccusage.fetch_today()
        elapsed_ms = int((datetime.now(UTC) - started).total_seconds() * 1000)
        if data is None:
            add("ccusage_live", "fail", "fetch returned no data", elapsed_ms=elapsed_ms)
        else:
            add(
                "ccusage_live",
                "ok",
                f"{data.date} ${data.cost_usd:.2f} / {data.total_tokens:,} tokens",
                elapsed_ms=elapsed_ms,
            )
        if codexbar.available:
            for provider_status in codexbar.fetch_provider_statuses():
                add(
                    f"codexbar_{provider_status['provider']}",
                    provider_status["status"],
                    provider_status["detail"],
                    label=provider_status["label"],
                    item_count=provider_status["item_count"],
                )

    status = "fail" if any(c["status"] == "fail" for c in checks) else "ok"
    payload = {
        "status": status,
        "generated_at": datetime.now(UTC).isoformat(),
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
        },
        "checks": checks,
    }

    if json_output:
        _echo_json(payload)
    else:
        click.echo(f"usage-pulse doctor: {status}")
        for check in checks:
            click.echo(f"  {check['status']:4} {check['name']}: {check['detail']}")

    if status == "fail":
        sys.exit(1)


@main.command()
@click.argument("engine")
def gate(engine):
    """Return subscription usage gate status for agent-dispatch."""
    normalized = engine.strip().lower()
    provider_by_engine = {
        "claude": "claude",
        "codex": "codex",
        "gpt": "codex",
        "opencode-go": "opencodego",
        "opencodego": "opencodego",
    }
    if normalized in {"free", "local", "ollama"}:
        click.echo(f"OK|{normalized}|free/local engine")
        return

    provider_name = provider_by_engine.get(normalized)
    if not provider_name:
        click.echo(f"WARN|{normalized}|no gate mapping")
        sys.exit(10)

    cb = CodexbarProvider()
    if not cb.available:
        click.echo(f"WARN|{normalized}|codexbar not available")
        sys.exit(10)

    previous_providers = os.environ.get("USAGE_PULSE_CODEXBAR_PROVIDERS")
    os.environ["USAGE_PULSE_CODEXBAR_PROVIDERS"] = provider_name
    try:
        statuses = cb.fetch_provider_statuses()
        windows = cb.fetch_rate_windows()
    finally:
        if previous_providers is None:
            os.environ.pop("USAGE_PULSE_CODEXBAR_PROVIDERS", None)
        else:
            os.environ["USAGE_PULSE_CODEXBAR_PROVIDERS"] = previous_providers

    ok_statuses = [status for status in statuses if status["status"] == "ok"]
    if not ok_statuses:
        detail = statuses[0]["detail"] if statuses else "no provider status"
        click.echo(f"WARN|{normalized}|{detail}")
        sys.exit(10)

    relevant = [info for info in windows.values() if info.get("provider") == provider_name]
    if not relevant:
        click.echo(f"WARN|{normalized}|no rate window returned")
        sys.exit(10)

    warn_pct = _gate_threshold("USAGE_PULSE_GATE_WARN_PCT", 80.0)
    hold_pct = _gate_threshold("USAGE_PULSE_GATE_HOLD_PCT", 95.0)
    credit_warn_pct = _gate_threshold("USAGE_PULSE_GATE_CREDIT_WARN_PCT", 10.0)
    credit_hold_pct = _gate_threshold("USAGE_PULSE_GATE_CREDIT_HOLD_PCT", 2.0)
    include_credits = os.environ.get("USAGE_PULSE_GATE_INCLUDE_CREDITS", "1") == "1"

    max_primary = max(float(info.get("primary_pct", 0.0)) for info in relevant)
    max_secondary = max(float(info.get("secondary_pct", 0.0)) for info in relevant)
    credit_remaining_values = [
        float(info["credit_remaining_pct"])
        for info in relevant
        if include_credits and info.get("credit_remaining_pct") is not None
    ]
    min_credit_remaining = min(credit_remaining_values) if credit_remaining_values else None

    detail = f"primary={max_primary:.1f}% secondary={max_secondary:.1f}%"
    if min_credit_remaining is not None:
        detail += f" credit_remaining={min_credit_remaining:.1f}%"

    if max_primary >= hold_pct or max_secondary >= hold_pct:
        click.echo(f"HOLD|{normalized}|{detail}")
        sys.exit(20)
    if min_credit_remaining is not None and min_credit_remaining <= credit_hold_pct:
        click.echo(f"HOLD|{normalized}|{detail}")
        sys.exit(20)
    if max_primary >= warn_pct or max_secondary >= warn_pct:
        click.echo(f"WARN|{normalized}|{detail}")
        sys.exit(10)
    if min_credit_remaining is not None and min_credit_remaining <= credit_warn_pct:
        click.echo(f"WARN|{normalized}|{detail}")
        sys.exit(10)

    click.echo(f"OK|{normalized}|{detail}")


@main.command()
def rates():
    """Show real-time rate windows for all providers (via CodexBar)."""
    cb = CodexbarProvider()
    if not cb.available:
        click.echo(
            "CodexBar not available (macOS only). Install: brew install trycodeday/tap/codexbar"
        )
        return

    windows = cb.fetch_rate_windows()
    if not windows:
        click.echo("No provider data returned.")
        return

    click.echo(f"\n{'=' * 55}")
    click.echo("  Rate Windows  —  CodexBar")
    click.echo(f"{'=' * 55}")
    for prov, info in windows.items():
        p_pct = info["primary_pct"]
        s_pct = info["secondary_pct"]
        reset = info.get("primary_reset_desc", "")
        bar_len = int(p_pct / 5)  # 20-char bar
        bar = "█" * bar_len + "░" * (20 - bar_len)
        click.echo(
            f"  {info['label']:2}  {prov:<12}  [{bar}] {p_pct:5.1f}%"
            + (f"  weekly={s_pct:.1f}%" if s_pct > 0 else "")
            + (f"  {reset}" if reset else "")
        )
    click.echo(f"{'=' * 55}\n")


@main.command()
def roi():
    """Show token ROI table by model."""
    provider = CcusageProvider()
    data = provider.fetch_today()
    if data is None:
        click.echo("Error: could not fetch usage data", err=True)
        sys.exit(1)

    rois = compute_roi(data.model_breakdowns)
    click.echo(f"\nToken ROI — {data.date}\n")
    click.echo(format_roi_table(rois))
    click.echo()


@main.command()
@click.option("--cost-threshold", default=50.0, envvar="USAGE_PULSE_THRESHOLD")
@click.option(
    "--poll-interval",
    default=60,
    envvar="USAGE_PULSE_POLL_INTERVAL",
    help="Seconds between updates (default 60)",
)
def tray(cost_threshold, poll_interval):
    """Start cross-platform system tray daemon (Mac/Win/Linux)."""
    from .display.tray import run_tray

    run_tray(cost_threshold=cost_threshold, poll_interval=poll_interval)


@main.command()
def setup():
    """Interactive setup: install tmux hook and Claude Code integration."""
    import subprocess
    from pathlib import Path

    click.echo("\n=== usage-pulse setup ===\n")

    # Check dependencies
    import shutil

    checks = {
        "tmux": shutil.which("tmux"),
        "bunx (ccusage)": shutil.which("bunx"),
        "python3": shutil.which("python3"),
        "codexbar (Mac only)": shutil.which("codexbar"),
    }
    for name, path in checks.items():
        status = "✅" if path else "❌"
        click.echo(f"  {status} {name}: {path or 'not found'}")

    click.echo()
    if click.confirm("Install tmux statusline integration?", default=True):
        script_dir = Path(__file__).parent.parent.parent.parent / "scripts"
        install_script = script_dir / "install-tmux.sh"
        if install_script.exists():
            subprocess.run(["bash", str(install_script)])
        else:
            click.echo("  Run scripts/install-tmux.sh manually")

    if click.confirm("Install Claude Code hook (PostToolUse sync)?", default=True):
        script_dir = Path(__file__).parent.parent.parent.parent / "scripts"
        hook_script = script_dir / "install-claude-hook.sh"
        if hook_script.exists():
            subprocess.run(["bash", str(hook_script)])
        else:
            click.echo("  Run scripts/install-claude-hook.sh manually")

    click.echo("\nSetup complete. Run `usage-pulse summary` to verify.")
