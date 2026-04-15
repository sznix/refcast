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


@app.command(hidden=True)
def _noop() -> None:  # pragma: no cover
    """Placeholder — to be replaced in subsequent commits."""
