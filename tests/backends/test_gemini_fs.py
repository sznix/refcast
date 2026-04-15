"""Tests for Gemini File Search adapter."""

import pytest

from refcast.backends.base import BackendError
from refcast.backends.gemini_fs import GeminiFSBackend
from refcast.models import RecoveryEnum


def test_adapter_id_and_capabilities():
    a = GeminiFSBackend(api_key="g_test")
    assert a.id == "gemini_fs"
    assert "search" in a.capabilities
    assert "upload" in a.capabilities
    assert "cite" in a.capabilities


def test_missing_api_key_raises_auth_invalid():
    with pytest.raises(BackendError) as exc:
        GeminiFSBackend(api_key=None)
    assert exc.value.code == RecoveryEnum.AUTH_INVALID
    assert exc.value.recovery_action == "user_action"
