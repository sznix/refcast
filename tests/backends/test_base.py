"""Tests for refcast.backends.base — Protocol conformance + BackendError."""

from refcast.backends.base import BackendAdapter, BackendError
from refcast.models import RecoveryEnum


class _StubAdapter:
    id = "stub"
    capabilities = frozenset({"search"})

    async def execute(self, query, corpus_id=None, constraints=None):
        raise NotImplementedError


def test_stub_adapter_satisfies_protocol():
    a: BackendAdapter = _StubAdapter()  # type: ignore[assignment]
    assert a.id == "stub"
    assert "search" in a.capabilities


def test_backend_error_carries_all_fields():
    err = BackendError(
        RecoveryEnum.AUTH_INVALID,
        "no api key",
        backend="stub",
        recovery_action="user_action",
        retry_after_ms=1000,
        raw={"status": 401},
    )
    assert err.code == RecoveryEnum.AUTH_INVALID
    assert err.backend == "stub"
    assert err.recovery_action == "user_action"
    assert err.retry_after_ms == 1000
    assert err.raw == {"status": 401}
    assert str(err) == "no api key"


def test_backend_error_defaults():
    err = BackendError(RecoveryEnum.UNKNOWN, "boom", backend="x")
    assert err.recovery_action == "fallback"
    assert err.retry_after_ms is None
    assert err.raw == {}
