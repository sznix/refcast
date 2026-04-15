"""refcast CLI — init/auth/doctor commands."""
from __future__ import annotations

from pathlib import Path

import typer

app = typer.Typer(help="refcast — portable research substrate CLI", no_args_is_help=True)

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

    gemini = typer.prompt("GEMINI_API_KEY", default="", show_default=False)
    exa = typer.prompt("EXA_API_KEY", default="", show_default=False)

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


@app.command(hidden=True)
def _noop() -> None:  # pragma: no cover
    """Placeholder — to be replaced in subsequent commits."""
