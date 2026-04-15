"""Tests for refcast.config secret loading."""

from pathlib import Path
from unittest.mock import patch

import pytest

from refcast.config import (
    MissingCredentialsError,
    RefcastConfig,
    load_config,
)

_NULL = Path("/dev/null")


def test_load_config_from_env(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "g_env")
    monkeypatch.setenv("EXA_API_KEY", "e_env")
    with patch("refcast.config.keyring.get_password", return_value=None):
        cfg = load_config(env_file=_NULL)
    assert cfg.gemini_api_key == "g_env"
    assert cfg.exa_api_key == "e_env"


def test_load_config_partial_registration(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "g_env")
    monkeypatch.delenv("EXA_API_KEY", raising=False)
    with patch("refcast.config.keyring.get_password", return_value=None):
        cfg = load_config(env_file=_NULL)
    assert cfg.gemini_api_key == "g_env"
    assert cfg.exa_api_key is None


def test_load_config_all_missing_raises(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("EXA_API_KEY", raising=False)
    with (
        patch("refcast.config.keyring.get_password", return_value=None),
        pytest.raises(MissingCredentialsError),
    ):
        load_config(env_file=_NULL, require_at_least_one=True)


def test_load_config_keyring_fallback(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("EXA_API_KEY", raising=False)
    with patch("refcast.config.keyring.get_password") as kr:
        kr.side_effect = lambda svc, key: "kr_g" if key == "gemini_api_key" else None
        cfg = load_config(env_file=_NULL)
    assert cfg.gemini_api_key == "kr_g"


def test_config_repr_masks_secrets():
    cfg = RefcastConfig(
        gemini_api_key="AIzaSy_sensitive_key_12345", exa_api_key="exa_sensitive_67890"
    )
    r = repr(cfg)
    assert "AIzaSy_sensitive_key_12345" not in r
    assert "exa_sensitive_67890" not in r
    assert "***" in r
    assert "gemini_api_key=***" in r
    assert "exa_api_key=***" in r


def test_config_repr_shows_none_when_missing():
    cfg = RefcastConfig(gemini_api_key=None, exa_api_key=None)
    r = repr(cfg)
    assert "gemini_api_key=None" in r
    assert "exa_api_key=None" in r
