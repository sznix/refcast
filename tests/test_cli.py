"""Tests for refcast.cli."""

from pathlib import Path
from unittest.mock import MagicMock, patch

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


# ---------------------------------------------------------------------------
# auth
# ---------------------------------------------------------------------------


def test_auth_env_creates_dotenv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, runner: CliRunner
) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["auth", "--store", "env"], input="g_key\ne_key\n")
    assert result.exit_code == 0
    env_text = (tmp_path / ".env").read_text()
    assert "GEMINI_API_KEY=g_key" in env_text
    assert "EXA_API_KEY=e_key" in env_text


def test_auth_env_absent_dotenv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, runner: CliRunner
) -> None:
    """auth --store env creates .env when it doesn't exist yet."""
    monkeypatch.chdir(tmp_path)
    assert not (tmp_path / ".env").exists()
    result = runner.invoke(app, ["auth", "--store", "env"], input="mygemini\n\n")
    assert result.exit_code == 0
    assert (tmp_path / ".env").exists()
    assert "GEMINI_API_KEY=mygemini" in (tmp_path / ".env").read_text()


def test_auth_env_replaces_existing_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, runner: CliRunner
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("GEMINI_API_KEY=old_g\nEXA_API_KEY=old_e\n")
    result = runner.invoke(app, ["auth", "--store", "env"], input="new_g\nnew_e\n")
    assert result.exit_code == 0
    env_text = (tmp_path / ".env").read_text()
    assert "GEMINI_API_KEY=new_g" in env_text
    assert "EXA_API_KEY=new_e" in env_text
    assert "old_g" not in env_text
    assert "old_e" not in env_text
    # Ensure no duplicate lines
    lines = [line for line in env_text.splitlines() if line.startswith("GEMINI_API_KEY=")]
    assert len(lines) == 1
    lines = [line for line in env_text.splitlines() if line.startswith("EXA_API_KEY=")]
    assert len(lines) == 1


def test_auth_keyring_calls_set_password(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, runner: CliRunner
) -> None:
    monkeypatch.chdir(tmp_path)
    mock_keyring = MagicMock()
    with patch.dict("sys.modules", {"keyring": mock_keyring}):
        result = runner.invoke(app, ["auth", "--store", "keyring"], input="g_key\ne_key\n")
    assert result.exit_code == 0
    mock_keyring.set_password.assert_any_call("refcast", "gemini_api_key", "g_key")
    mock_keyring.set_password.assert_any_call("refcast", "exa_api_key", "e_key")
    assert "OS keychain" in result.output


def test_auth_both_empty_exits_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, runner: CliRunner
) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["auth", "--store", "env"], input="\n\n")
    assert result.exit_code == 1


def test_auth_invalid_store_exits_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, runner: CliRunner
) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["auth", "--store", "s3"], input="g\ne\n")
    assert result.exit_code == 1


# ---------------------------------------------------------------------------
# doctor
# ---------------------------------------------------------------------------


def _make_cfg(*, gemini: str | None = None, exa: str | None = None) -> MagicMock:
    cfg = MagicMock()
    cfg.gemini_api_key = gemini
    cfg.exa_api_key = exa
    cfg.has_any.return_value = bool(gemini or exa)
    return cfg


def test_doctor_both_configured(runner: CliRunner) -> None:
    with patch("refcast.cli.load_config", return_value=_make_cfg(gemini="g", exa="e")):
        result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0
    assert "configured" in result.output
    assert "NOT configured" not in result.output


def test_doctor_no_credentials_exits_1(runner: CliRunner) -> None:
    with patch("refcast.cli.load_config", return_value=_make_cfg()):
        result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 1
    assert "No backends" in result.output


def test_doctor_partial_configured(runner: CliRunner) -> None:
    with patch("refcast.cli.load_config", return_value=_make_cfg(gemini="g")):
        result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0
    assert "Gemini: configured" in result.output
    assert "Exa:    NOT configured" in result.output
