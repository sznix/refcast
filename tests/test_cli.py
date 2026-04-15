"""Tests for refcast.cli."""
from pathlib import Path

import pytest
from typer.testing import CliRunner

from refcast.cli import app


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------


def test_init_creates_env_example(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, runner: CliRunner
) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0
    assert (tmp_path / ".env.example").exists()
    assert "GEMINI_API_KEY" in (tmp_path / ".env.example").read_text()


def test_init_does_not_overwrite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, runner: CliRunner
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env.example").write_text("EXISTING_CONTENT")
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0
    assert (tmp_path / ".env.example").read_text() == "EXISTING_CONTENT"
    assert "already exists" in result.output
