"""Tests for refcast.config secret loading."""

from unittest.mock import patch

import pytest

from refcast.config import (
    MissingCredentialsError,
    load_config,
)


def test_load_config_from_env(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "g_env")
    monkeypatch.setenv("EXA_API_KEY", "e_env")
    cfg = load_config()
    assert cfg.gemini_api_key == "g_env"
    assert cfg.exa_api_key == "e_env"


def test_load_config_partial_registration(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "g_env")
    monkeypatch.delenv("EXA_API_KEY", raising=False)
    with patch("refcast.config.keyring.get_password", return_value=None):
        cfg = load_config()
    assert cfg.gemini_api_key == "g_env"
    assert cfg.exa_api_key is None


def test_load_config_all_missing_raises(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("EXA_API_KEY", raising=False)
    with (
        patch("refcast.config.keyring.get_password", return_value=None),
        pytest.raises(MissingCredentialsError),
    ):
        load_config(require_at_least_one=True)


def test_load_config_keyring_fallback(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("EXA_API_KEY", raising=False)
    with patch("refcast.config.keyring.get_password") as kr:
        kr.side_effect = lambda svc, key: "kr_g" if key == "gemini_api_key" else None
        cfg = load_config()
        assert cfg.gemini_api_key == "kr_g"
