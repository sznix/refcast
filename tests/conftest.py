"""Shared pytest fixtures for refcast test suite."""

import pytest


@pytest.fixture
def sample_gemini_api_key() -> str:
    """Fake Gemini API key for unit tests."""
    return "AIzaSy_test_gemini_key_0000000000000"


@pytest.fixture
def sample_exa_api_key() -> str:
    """Fake Exa API key for unit tests."""
    return "exa_test_0000000000000000000000000000"
