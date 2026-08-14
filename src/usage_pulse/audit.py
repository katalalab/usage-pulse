"""Read-only AI runtime/configuration audit helpers."""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import socket
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .analysis.roi import compute_roi
from .providers.ccusage import CcusageProvider

AI_PROCESS_RE = re.compile(
    r"\b(codex|claude|cursor-agent|opencode|gemini|ollama|openclaw|shirokuma|ccusage)\b",
    re.IGNORECASE,
)

SAFE_CONFIG_KEYS = {
    "model",
    "small_model",
    "defaultModel",
    "preferredNotifChannel",
    "disableAllHooks",
    "autoupdate",
    "theme",
    "approval_policy",
    "sandbox_mode",
    "profile",
    "profiles",
    "provider",
    "permission",
    "permissions",
    "statusLine",
    "hooks",
    "mcpServers",
}

SENSITIVE_KEY_RE = re.compile(
    r"(api|auth|bearer|cookie|credential|key|password|secret|session|token)", re.IGNORECASE
)


@dataclass(frozen=True)
class ToolSpec:
    name: str
    command: str
    version_args: tuple[str, ...]
    config_paths: tuple[str, ...] = ()
    instruction_paths: tuple[str, ...] = ()


TOOL_SPECS = (
    ToolSpec(
        "codex",
        "codex",
        ("--version",),
        ("~/.codex/config.toml", ".codex/config.toml"),
        ("AGENTS.md", "AGENTS.MD"),
    ),
    ToolSpec(
        "claude",
        "claude",
        ("--version",),
        ("~/.claude/settings.json",),
        ("CLAUDE.md",),
    ),
    ToolSpec(
        "cursor-agent",
        "cursor-agent",
        ("--version",),
        (
            "~/.cursor/mcp.json",
            ".cursor/rules",
        ),
        ("AGENTS.md", ".cursor/rules"),
    ),
    ToolSpec(
        "opencode",
        "opencode",
        ("--version",),
        (
            "~/.config/opencode/opencode.json",
            "~/.config/opencode/opencode.jsonc",
            "~/.config/opencode/config.json",
            "opencode.json",
            "opencode.jsonc",
        ),
        ("AGENTS.md",),
    ),
    ToolSpec(
        "gemini",
        "gemini",
        ("--version",),
        ("~/.gemini/settings.json",),
        ("GEMINI.md",),
    ),
    ToolSpec("ccusage", "ccusage", ("--version",), ("~/.ccusage/config.json",)),
    ToolSpec("ollama", "ollama", ("--version",)),
)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _run(command: list[str], timeout: int = 5) -> dict[str, Any]:
    started = datetime.now(UTC)
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        elapsed_ms = int((datetime.now(UTC) - started).total_seconds() * 1000)
        output = (result.stdout or result.stderr).strip().splitlines()
        return {
            "ok": result.returncode == 0,
            "returncode": result.returncode,
            "elapsed_ms": elapsed_ms,
            "first_line": output[0][:240] if output else "",
        }
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        elapsed_ms = int((datetime.now(UTC) - started).total_seconds() * 1000)
        return {
            "ok": False,
            "returncode": None,
            "elapsed_ms": elapsed_ms,
            "first_line": exc.__class__.__name__,
        }


def _expand_path(raw_path: str, cwd: Path) -> Path:
    path = Path(os.path.expanduser(raw_path))
    return path if path.is_absolute() else cwd / path


def _strip_jsonc(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    lines = []
    for line in text.splitlines():
        lines.append(re.sub(r"(^|[^:])//.*$", r"\1", line))
    without_comments = "\n".join(lines)
    return re.sub(r",\s*([}\]])", r"\1", without_comments)


def _redact_command(command: str) -> str:
    command = re.sub(
        r"((?:--?|/)(?:api-?key|auth|cookie|password|secret|session-id|settings|token)\s+)"
        r"((?:'[^']*')|(?:\"[^\"]*\")|\S+)",
        r"\1[redacted]",
        command,
        flags=re.IGNORECASE,
    )
    command = re.sub(
        r"(\b(?:api|auth|cookie|password|secret|token)[A-Z0-9_-]*=)\S+",
        r"\1[redacted]",
        command,
        flags=re.IGNORECASE,
    )
    command = re.sub(r"\{(?:[^{}]|\{[^{}]*\}){40,}\}", "[json-redacted]", command)
    return command[:260]


def _safe_scalar(value: Any) -> Any:
    if isinstance(value, str):
        if SENSITIVE_KEY_RE.search(value) or len(value) > 120:
            return "[redacted]"
        return value
    if isinstance(value, bool | int | float) or value is None:
        return value
    return None


def _safe_config_summary(value: Any, depth: int = 0) -> Any:
    if depth > 3:
        return "[truncated]"
    if isinstance(value, dict):
        summary: dict[str, Any] = {}
        for key, item in value.items():
            key_str = str(key)
            if SENSITIVE_KEY_RE.search(key_str):
                continue
            if key_str in SAFE_CONFIG_KEYS or depth > 0:
                safe = _safe_config_summary(item, depth + 1)
                if safe not in (None, {}, []):
                    summary[key_str] = safe
        return summary
    if isinstance(value, list):
        safe_items = [_safe_config_summary(item, depth + 1) for item in value[:8]]
        return [item for item in safe_items if item not in (None, {}, [])]
    return _safe_scalar(value)


def _read_config(path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {"path": str(path), "exists": path.exists()}
    if not path.exists() or path.is_dir():
        return result
    result["size_bytes"] = path.stat().st_size
    if path.stat().st_size > 200_000:
        result["status"] = "skipped_large_file"
        return result

    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        result["status"] = "skipped_non_utf8"
        return result

    suffix = path.suffix.lower()
    try:
        if suffix in {".json", ".jsonc"}:
            parsed = json.loads(_strip_jsonc(text))
            result["summary"] = _safe_config_summary(parsed)
        elif suffix == ".toml":
            import tomllib

            parsed = tomllib.loads(text)
            result["summary"] = _safe_config_summary(parsed)
        else:
            result["line_count"] = len(text.splitlines())
        result["status"] = "ok"
    except Exception as exc:
        result["status"] = "parse_error"
        result["error"] = exc.__class__.__name__
    return result


def _instruction_summary(path: Path) -> dict[str, Any]:
    result = {"path": str(path), "exists": path.exists()}
    if path.exists() and path.is_file():
        result["size_bytes"] = path.stat().st_size
    elif path.exists() and path.is_dir():
        result["type"] = "directory"
    return result


def collect_tools(cwd: Path | None = None) -> list[dict[str, Any]]:
    cwd = cwd or Path.cwd()
    tools: list[dict[str, Any]] = []
    for spec in TOOL_SPECS:
        executable = shutil.which(spec.command)
        tool: dict[str, Any] = {
            "name": spec.name,
            "command": spec.command,
            "path": executable,
            "available": executable is not None,
            "version": None,
            "configs": [_read_config(_expand_path(path, cwd)) for path in spec.config_paths],
            "instructions": [
                _instruction_summary(_expand_path(path, cwd)) for path in spec.instruction_paths
            ],
        }
        if executable is not None:
            tool["version"] = _run([executable, *spec.version_args])
        tools.append(tool)
    return tools


def collect_processes(limit: int = 80) -> dict[str, Any]:
    command = ["ps", "-axo", "pid,ppid,pcpu,pmem,etime,command"]
    result = _run(command, timeout=8)
    if not result["ok"]:
        return {"status": "unavailable", "error": result["first_line"], "items": []}

    proc = subprocess.run(command, capture_output=True, text=True, timeout=8)
    items: list[dict[str, Any]] = []
    for line in proc.stdout.splitlines()[1:]:
        if not AI_PROCESS_RE.search(line):
            continue
        parts = line.split(None, 5)
        if len(parts) < 6:
            continue
        try:
            pcpu = float(parts[2])
            pmem = float(parts[3])
        except ValueError:
            pcpu = pmem = 0.0
        items.append(
            {
                "pid": int(parts[0]),
                "ppid": int(parts[1]),
                "cpu_pct": pcpu,
                "mem_pct": pmem,
                "etime": parts[4],
                "command": _redact_command(parts[5]),
            }
        )
    items.sort(key=lambda item: float(item["cpu_pct"]), reverse=True)
    return {"status": "ok", "items": items[:limit], "truncated": len(items) > limit}


def collect_tmux() -> dict[str, Any]:
    tmux = shutil.which("tmux")
    if tmux is None:
        return {"status": "missing", "items": []}
    result = subprocess.run(
        [
            tmux,
            "list-panes",
            "-a",
            "-F",
            "#{session_name}:#{window_index}.#{pane_index} pid=#{pane_pid} "
            "cmd=#{pane_current_command} cwd=#{pane_current_path}",
        ],
        capture_output=True,
        text=True,
        timeout=8,
    )
    if result.returncode != 0:
        return {"status": "unavailable", "error": result.stderr.strip()[:240], "items": []}
    items = [line for line in result.stdout.splitlines() if line.strip()]
    ai_items = [line for line in items if AI_PROCESS_RE.search(line)]
    return {
        "status": "ok",
        "pane_count": len(items),
        "ai_pane_count": len(ai_items),
        "items": ai_items[:80],
    }


def collect_usage(skip_live: bool = False) -> dict[str, Any]:
    if skip_live:
        return {"status": "skipped"}
    provider = CcusageProvider()
    started = datetime.now(UTC)
    data = provider.fetch_today()
    elapsed_ms = int((datetime.now(UTC) - started).total_seconds() * 1000)
    if data is None:
        return {"status": "unavailable", "elapsed_ms": elapsed_ms, "command": provider.command}
    rois = compute_roi(data.model_breakdowns)
    return {
        "status": "ok",
        "elapsed_ms": elapsed_ms,
        "command": provider.command,
        "date": data.date,
        "source": data.source,
        "cost_usd": round(data.cost_usd, 6),
        "tokens": data.total_tokens,
        "input_tokens": data.input_tokens,
        "output_tokens": data.output_tokens,
        "cache_read_tokens": data.cache_read_tokens,
        "cache_creation_tokens": data.cache_creation_tokens,
        "models": [
            {
                "model": roi.model_name,
                "cost_usd": round(roi.cost_usd, 6),
                "output_tokens": roi.output_tokens,
                "cost_per_1k_output": round(roi.cost_per_1k_output, 6),
                "cache_efficiency": round(roi.cache_efficiency, 6),
            }
            for roi in rois[:10]
        ],
    }


def _load_average() -> dict[str, Any]:
    try:
        one, five, fifteen = os.getloadavg()  # type: ignore[attr-defined]  # Unix-only
        return {"available": True, "one": one, "five": five, "fifteen": fifteen}
    except (AttributeError, OSError):
        return {"available": False}


def analyze_bottlenecks(payload: dict[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    cpu_count = payload["host"].get("cpu_count") or 1
    load = payload["host"].get("load_average", {})
    if load.get("available") and load.get("one", 0) > cpu_count:
        findings.append(
            {
                "severity": "warning",
                "code": "host_load_high",
                "detail": f"1min load {load['one']:.2f} exceeds cpu_count {cpu_count}",
            }
        )

    tools = {tool["name"]: tool for tool in payload.get("tools", [])}
    if not tools.get("ccusage", {}).get("available"):
        findings.append(
            {
                "severity": "warning",
                "code": "ccusage_missing",
                "detail": "token/cost efficiency cannot be verified without ccusage or equivalent logs",
            }
        )
    if payload.get("usage", {}).get("status") == "unavailable":
        findings.append(
            {
                "severity": "warning",
                "code": "usage_unavailable",
                "detail": "ccusage command exists but returned no usable usage data",
            }
        )

    for proc in payload.get("processes", {}).get("items", []):
        if proc["cpu_pct"] >= 100:
            findings.append(
                {
                    "severity": "warning",
                    "code": "ai_process_cpu_high",
                    "detail": f"pid {proc['pid']} uses {proc['cpu_pct']:.1f}% cpu: {proc['command'][:80]}",
                }
            )

    tmux = payload.get("tmux", {})
    if tmux.get("ai_pane_count", 0) >= 10:
        findings.append(
            {
                "severity": "info",
                "code": "many_ai_tmux_panes",
                "detail": f"{tmux['ai_pane_count']} tmux panes look AI-related",
            }
        )

    usage = payload.get("usage", {})
    for model in usage.get("models", []):
        if model.get("cache_efficiency", 0) < 0.05 and model.get("output_tokens", 0) > 100_000:
            findings.append(
                {
                    "severity": "info",
                    "code": "low_cache_efficiency",
                    "detail": f"{model['model']} has low cache efficiency",
                }
            )
    return findings


def collect_audit(
    skip_live: bool = False, include_processes: bool = True, cwd: Path | None = None
) -> dict[str, Any]:
    cwd = cwd or Path.cwd()
    payload: dict[str, Any] = {
        "schema_version": 1,
        "generated_at": _now_iso(),
        "cwd": str(cwd),
        "host": {
            "hostname": socket.gethostname(),
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "python": platform.python_version(),
            "cpu_count": os.cpu_count(),
            "load_average": _load_average(),
        },
        "tools": collect_tools(cwd),
        "usage": collect_usage(skip_live=skip_live),
        "tmux": collect_tmux(),
    }
    if include_processes:
        payload["processes"] = collect_processes()
    else:
        payload["processes"] = {"status": "skipped", "items": []}
    payload["bottlenecks"] = analyze_bottlenecks(payload)
    return payload


def run_remote_audit(host: str, remote_command: str, timeout: int = 30) -> dict[str, Any]:
    started = datetime.now(UTC)
    command = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=8",
        host,
        remote_command,
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"host": host, "status": "timeout", "elapsed_ms": timeout * 1000}

    elapsed_ms = int((datetime.now(UTC) - started).total_seconds() * 1000)
    if result.returncode != 0:
        return {
            "host": host,
            "status": "fail",
            "elapsed_ms": elapsed_ms,
            "stderr": result.stderr.strip()[:500],
        }
    try:
        audit = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {
            "host": host,
            "status": "invalid_json",
            "elapsed_ms": elapsed_ms,
            "stdout_head": result.stdout[:500],
        }
    return {"host": host, "status": "ok", "elapsed_ms": elapsed_ms, "audit": audit}
