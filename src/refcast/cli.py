"""refcast CLI — init/auth/doctor/monitor commands."""

from __future__ import annotations

import platform
import shutil
import subprocess
from pathlib import Path
from typing import Any

import typer

from refcast.config import load_config

app = typer.Typer(
    help="refcast — multi-backend research with unified citations",
    no_args_is_help=True,
)

ENV_EXAMPLE_CONTENT = """\
# Copy to .env and fill in.
# Get keys: https://aistudio.google.com/apikey  and  https://dashboard.exa.ai/api-keys
GEMINI_API_KEY=
EXA_API_KEY=
"""


@app.command()
def init() -> None:
    """Scaffold .env.example in the current directory."""
    target = Path.cwd() / ".env.example"
    if target.exists():
        typer.echo(f"{target} already exists — leaving untouched.")
        raise typer.Exit(code=0)
    target.write_text(ENV_EXAMPLE_CONTENT)
    typer.echo(f"Created {target}")
    typer.echo("Next steps:")
    typer.echo("  1. cp .env.example .env")
    typer.echo("  2. Fill in GEMINI_API_KEY and/or EXA_API_KEY")
    typer.echo("  3. Run: refcast doctor")


@app.command()
def auth(
    store: str = typer.Option("env", "--store", help="env|keyring"),
) -> None:
    """Interactively store API keys (in keyring or .env)."""
    import keyring  # noqa: PLC0415

    gemini = typer.prompt("GEMINI_API_KEY", default="", show_default=False, hide_input=True)
    exa = typer.prompt("EXA_API_KEY", default="", show_default=False, hide_input=True)

    if not gemini and not exa:
        typer.echo("No keys provided.", err=True)
        raise typer.Exit(code=1)

    if store == "keyring":
        if gemini:
            keyring.set_password("refcast", "gemini_api_key", gemini)
        if exa:
            keyring.set_password("refcast", "exa_api_key", exa)
        typer.echo("Stored in OS keychain.")
    elif store == "env":
        env_path = Path.cwd() / ".env"
        lines: list[str] = []
        if env_path.exists():
            lines = env_path.read_text().splitlines()
        # Drop any prior GEMINI_API_KEY/EXA_API_KEY lines, then append
        lines = [
            line
            for line in lines
            if not line.startswith("GEMINI_API_KEY=") and not line.startswith("EXA_API_KEY=")
        ]
        if gemini:
            lines.append(f"GEMINI_API_KEY={gemini}")
        if exa:
            lines.append(f"EXA_API_KEY={exa}")
        env_path.write_text("\n".join(lines) + "\n")
        typer.echo(f"Stored in {env_path}.")
    else:
        typer.echo(f"Unknown --store: {store}", err=True)
        raise typer.Exit(code=1)


_VERIFY_PATH_ARG = typer.Argument(..., help="Path to a JSON file containing an EvidencePack")


@app.command()
def verify(path: Path = _VERIFY_PATH_ARG) -> None:
    """Offline **integrity** verification of a saved EvidencePack.

    Exit code 0 if the pack's integrity is valid, 1 if invalid or malformed.
    Pure offline — no network, no API keys required.

    Scope: integrity only. This does NOT prove citations are correct, does NOT
    bind citations to the envelope (consumer must re-hash out-of-band), and
    does NOT prove the pack came from refcast (no signature, no signer).
    """
    import json as _json  # noqa: PLC0415

    from refcast.evidence import verify_evidence_pack  # noqa: PLC0415

    if not path.exists():
        typer.echo(f"ERROR: file not found: {path}", err=True)
        raise typer.Exit(code=1)

    try:
        data = _json.loads(path.read_text())
    except _json.JSONDecodeError as e:
        typer.echo(f"ERROR: not valid JSON: {e}", err=True)
        raise typer.Exit(code=1) from e

    # Accept either a raw EvidencePack or a full ResearchResult with .evidence_pack
    pack_candidate: object
    if isinstance(data, dict) and "evidence_pack" in data:
        pack_candidate = data["evidence_pack"]
    else:
        pack_candidate = data

    if not isinstance(pack_candidate, dict):
        typer.echo("ERROR: pack is not a dict", err=True)
        raise typer.Exit(code=1)

    pack: dict[str, Any] = pack_candidate
    integrity_valid, errors = verify_evidence_pack(pack)
    if integrity_valid:
        backends_list: list[dict[str, Any]] = pack.get("backends_used") or []
        backends_str = ", ".join(b.get("id", "?") for b in backends_list)
        typer.echo("Integrity-valid: transcript_cid matches canonical form")
        typer.echo(f"  transcript_cid:          {pack.get('transcript_cid')}")
        typer.echo(f"  citations:               {pack.get('citations_count')}")
        typer.echo(f"  backends:                {backends_str}")
        typer.echo(f"  timestamp:               {pack.get('timestamp')}")
        typer.echo(f"  cost:                    {pack.get('cost_cents')} cents")
        typer.echo("  binding_verified:        False (re-hash citations to confirm)")
        typer.echo("  authenticity_verified:   False (no signer in v0.3)")
        raise typer.Exit(code=0)
    else:
        typer.echo("INVALID: pack failed integrity verification", err=True)
        for err in errors:
            typer.echo(f"  - {err}", err=True)
        raise typer.Exit(code=1)


@app.command()
def doctor() -> None:
    """Report which backends are configured + reachable."""
    cfg = load_config()
    typer.echo("=== refcast doctor ===")
    typer.echo(f"Gemini: {'configured' if cfg.gemini_api_key else 'NOT configured'}")
    typer.echo(f"Exa:    {'configured' if cfg.exa_api_key else 'NOT configured'}")
    if not cfg.has_any():
        typer.echo("\nNo backends configured. Run: refcast auth", err=True)
        raise typer.Exit(code=1)
    typer.echo("\nNext: register the MCP server in your client config:")
    typer.echo('  "mcpServers": {"refcast": {"command": "refcast-mcp"}}')


# ─── Monitor ────────────────────────────────────────────


_MONITOR_SCRIPT = """\
#!/usr/bin/env bash
# refcast auth monitor — checks NotebookLM cookie health daily.
# Installed by: refcast monitor install
set -euo pipefail

NLM="{nlm_path}"
LOG="{log_path}"
TIMESTAMP=$(date "+%Y-%m-%dT%H:%M:%S")

mkdir -p "$(dirname "$LOG")"

if "$NLM" login --check > /dev/null 2>&1; then
    echo "$TIMESTAMP OK" >> "$LOG"
else
    echo "$TIMESTAMP EXPIRED" >> "$LOG"
    {notify_cmd}
fi

# Trim log to last 100 lines
if [ -f "$LOG" ] && [ "$(wc -l < "$LOG")" -gt 100 ]; then
    tail -50 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
fi
"""

_PLIST_TEMPLATE = """\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" \
"http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.refcast.auth-monitor</string>
    <key>Program</key>
    <string>{script_path}</string>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>{hour}</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>{log_path}</string>
    <key>StandardErrorPath</key>
    <string>{log_path}</string>
</dict>
</plist>
"""


def _find_nlm() -> str | None:
    """Find the nlm binary path."""
    return shutil.which("nlm")


def _monitor_paths() -> dict[str, Path]:
    """Return platform-appropriate paths for monitor files."""
    home = Path.home()
    return {
        "script": home / ".local" / "bin" / "refcast-auth-monitor.sh",
        "log": home / ".local" / "share" / "refcast-auth-monitor.log",
        "plist": home / "Library" / "LaunchAgents" / "com.refcast.auth-monitor.plist",
    }


@app.command()
def monitor(
    action: str = typer.Argument(..., help="install | status | remove"),
    hour: int = typer.Option(9, "--hour", help="Hour of day to check (0-23)"),
) -> None:
    """Set up daily NotebookLM cookie monitoring with notifications.

    Checks if your NotebookLM cookies are still valid once a day.
    If expired, sends a system notification so you can re-auth before
    your agent hits a cookie error mid-workflow.

    Requires 'nlm' CLI (notebooklm-mcp-cli) to be installed.
    """
    if action == "install":
        _monitor_install(hour)
    elif action == "status":
        _monitor_status()
    elif action == "remove":
        _monitor_remove()
    else:
        typer.echo(f"Unknown action: {action}. Use: install, status, or remove", err=True)
        raise typer.Exit(code=1)


def _monitor_install(hour: int) -> None:
    nlm = _find_nlm()
    if not nlm:
        typer.echo(
            "'nlm' not found. Install it first: uv tool install notebooklm-mcp-cli", err=True
        )
        raise typer.Exit(code=1)

    paths = _monitor_paths()
    is_mac = platform.system() == "Darwin"

    # Build notification command per platform
    if is_mac:
        notify = (
            "/usr/bin/osascript -e "
            '\'display notification "Run: nlm login" '
            'with title "NotebookLM cookies expired" '
            'sound name "Ping"\' 2>/dev/null || true'
        )
    else:
        # Linux: try notify-send, fall back to echo
        notify = (
            'notify-send "NotebookLM cookies expired" '
            '"Run: nlm login" 2>/dev/null || '
            'echo "ALERT: NotebookLM cookies expired — run: nlm login"'
        )

    # Write the check script
    script_content = _MONITOR_SCRIPT.format(
        nlm_path=nlm,
        log_path=str(paths["log"]),
        notify_cmd=notify,
    )
    paths["script"].parent.mkdir(parents=True, exist_ok=True)
    paths["script"].write_text(script_content)
    paths["script"].chmod(0o755)
    typer.echo(f"  Script: {paths['script']}")

    # Install the scheduler
    if is_mac:
        plist = _PLIST_TEMPLATE.format(
            script_path=str(paths["script"]),
            log_path=str(paths["log"]),
            hour=hour,
        )
        paths["plist"].parent.mkdir(parents=True, exist_ok=True)
        paths["plist"].write_text(plist)

        # Unload first if already loaded (ignore errors)
        subprocess.run(
            ["launchctl", "unload", str(paths["plist"])],
            capture_output=True,
        )
        subprocess.run(
            ["launchctl", "load", str(paths["plist"])],
            check=True,
            capture_output=True,
        )
        typer.echo(f"  Scheduler: macOS LaunchAgent (daily at {hour}:00)")
        typer.echo(f"  Plist: {paths['plist']}")
    else:
        # Linux: install crontab entry
        result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
        existing = result.stdout if result.returncode == 0 else ""
        marker = "# refcast-auth-monitor"

        if marker in existing:
            typer.echo("  Cron entry already exists — skipping.")
        else:
            new_cron = existing.rstrip() + (f"\n{marker}\n0 {hour} * * * {paths['script']}\n")
            subprocess.run(
                ["crontab", "-"],
                input=new_cron,
                text=True,
                check=True,
            )
            typer.echo(f"  Scheduler: cron (daily at {hour}:00)")

    typer.echo(f"  Log: {paths['log']}")
    typer.echo()
    typer.echo("Done. You'll get a notification when cookies expire.")
    typer.echo("Check status anytime: refcast monitor status")
    typer.echo("Remove: refcast monitor remove")


def _monitor_status() -> None:
    paths = _monitor_paths()

    typer.echo("=== refcast auth monitor ===")

    # Check script exists
    if paths["script"].exists():
        typer.echo(f"  Script: installed ({paths['script']})")
    else:
        typer.echo("  Script: NOT installed. Run: refcast monitor install")
        raise typer.Exit(code=1)

    # Check scheduler
    is_mac = platform.system() == "Darwin"
    if is_mac:
        result = subprocess.run(
            ["launchctl", "list"],
            capture_output=True,
            text=True,
        )
        if "com.refcast.auth-monitor" in result.stdout:
            typer.echo("  Scheduler: active (macOS LaunchAgent)")
        else:
            typer.echo("  Scheduler: NOT loaded")
    else:
        result = subprocess.run(
            ["crontab", "-l"],
            capture_output=True,
            text=True,
        )
        if "refcast-auth-monitor" in result.stdout:
            typer.echo("  Scheduler: active (cron)")
        else:
            typer.echo("  Scheduler: NOT installed")

    # Check log
    if paths["log"].exists():
        lines = paths["log"].read_text().strip().splitlines()
        typer.echo(f"  Log: {len(lines)} entries")
        if lines:
            last = lines[-1]
            typer.echo(f"  Last check: {last}")
    else:
        typer.echo("  Log: no checks yet")

    # Check nlm auth
    nlm = _find_nlm()
    if nlm:
        result = subprocess.run(
            [nlm, "login", "--check"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            typer.echo("  Cookies: valid")
        else:
            typer.echo("  Cookies: EXPIRED — run: nlm login")
    else:
        typer.echo("  nlm: not found")


def _monitor_remove() -> None:
    paths = _monitor_paths()
    is_mac = platform.system() == "Darwin"

    # Remove scheduler
    if is_mac and paths["plist"].exists():
        subprocess.run(
            ["launchctl", "unload", str(paths["plist"])],
            capture_output=True,
        )
        paths["plist"].unlink()
        typer.echo("  LaunchAgent: removed")
    elif not is_mac:
        result = subprocess.run(
            ["crontab", "-l"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and "refcast-auth-monitor" in result.stdout:
            lines = result.stdout.splitlines()
            cleaned = [ln for ln in lines if "refcast-auth-monitor" not in ln]
            subprocess.run(
                ["crontab", "-"],
                input="\n".join(cleaned) + "\n",
                text=True,
            )
            typer.echo("  Cron entry: removed")

    # Remove script
    if paths["script"].exists():
        paths["script"].unlink()
        typer.echo("  Script: removed")

    # Keep log (user's data)
    if paths["log"].exists():
        typer.echo(f"  Log kept: {paths['log']}")

    typer.echo("  Monitor removed. No more daily checks.")
