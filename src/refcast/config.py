"""Secret loading for refcast — dotenv → keyring → env var chain."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import keyring
from dotenv import load_dotenv


class MissingCredentialsError(RuntimeError):
    """Raised when no backend credentials can be located and at least one is required."""


_SERVICE = "refcast"


@dataclass(frozen=True)
class RefcastConfig:
    gemini_api_key: str | None
    exa_api_key: str | None

    def has_any(self) -> bool:
        return bool(self.gemini_api_key or self.exa_api_key)


def _lookup(env_var: str, keyring_key: str) -> str | None:
    if v := os.environ.get(env_var):
        return v
    return keyring.get_password(_SERVICE, keyring_key)


def load_config(
    env_file: Path | None = None,
    require_at_least_one: bool = False,
) -> RefcastConfig:
    """Load credentials. Chain: dotenv -> env -> keyring."""
    load_dotenv(env_file or Path.cwd() / ".env", override=False)

    cfg = RefcastConfig(
        gemini_api_key=_lookup("GEMINI_API_KEY", "gemini_api_key"),
        exa_api_key=_lookup("EXA_API_KEY", "exa_api_key"),
    )

    if require_at_least_one and not cfg.has_any():
        raise MissingCredentialsError(
            "No research backends could be initialized. Set at least one of:\n"
            "  - GEMINI_API_KEY  (https://aistudio.google.com/apikey)\n"
            "  - EXA_API_KEY     (https://dashboard.exa.ai/api-keys)\n"
            "Or run: refcast auth"
        )

    return cfg
