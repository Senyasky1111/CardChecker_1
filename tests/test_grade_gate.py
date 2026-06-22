"""Unit tests for src/grade_gate — the auth + billing gate on the paid /grade endpoint.

The gate is the security-critical new code (it physically prevents budget drain), so it
gets hard coverage: shared-secret auth, atomic credit decrement + 402, daily cap, refund,
per-user rate limit, and idempotency. Uses a throwaway SQLite file; no app, no API calls.
"""
import importlib

import pytest
from fastapi import HTTPException


@pytest.fixture
def gate(tmp_path, monkeypatch):
    """Fresh grade_gate bound to a temp DB with caches cleared and env reset."""
    import src.grade_gate as g
    importlib.reload(g)
    monkeypatch.setattr(g, "DB_PATH", tmp_path / "credits.db")
    g._rate.clear()
    g._idem.clear()
    for k in ("GRADE_API_SECRET", "GRADE_FREE_CREDITS", "GRADE_RATE_PER_MIN", "GRADE_DAILY_CAP"):
        monkeypatch.delenv(k, raising=False)
    g.init_db()
    return g


# ----------------------------------------------------------------- auth

def test_auth_dev_mode_when_no_secret(gate):
    assert gate.authenticate(None, None) == "dev"
    assert gate.authenticate(None, "u1") == "u1"


def test_auth_requires_matching_secret(gate, monkeypatch):
    monkeypatch.setenv("GRADE_API_SECRET", "s3cret")
    with pytest.raises(HTTPException) as e:
        gate.authenticate(None, "u1")
    assert e.value.status_code == 401
    with pytest.raises(HTTPException) as e:
        gate.authenticate("wrong", "u1")
    assert e.value.status_code == 401


def test_auth_requires_user_when_secret_set(gate, monkeypatch):
    monkeypatch.setenv("GRADE_API_SECRET", "s3cret")
    with pytest.raises(HTTPException) as e:
        gate.authenticate("s3cret", None)
    assert e.value.status_code == 400
    assert gate.authenticate("s3cret", "u1") == "u1"


# ----------------------------------------------------------------- credits

def test_reserve_seeds_then_decrements_to_402(gate, monkeypatch):
    monkeypatch.setenv("GRADE_FREE_CREDITS", "2")
    gate.reserve("u1")                       # 2 -> 1
    assert gate.remaining("u1") == 1
    gate.reserve("u1")                       # 1 -> 0
    assert gate.remaining("u1") == 0
    with pytest.raises(HTTPException) as e:  # 0 -> 402, no spend
        gate.reserve("u1")
    assert e.value.status_code == 402
    assert gate.remaining("u1") == 0


def test_refund_restores_a_credit(gate, monkeypatch):
    monkeypatch.setenv("GRADE_FREE_CREDITS", "1")
    gate.reserve("u1")
    assert gate.remaining("u1") == 0
    gate.refund("u1")
    assert gate.remaining("u1") == 1


def test_daily_cap_blocks_with_429(gate, monkeypatch):
    monkeypatch.setenv("GRADE_FREE_CREDITS", "100")
    monkeypatch.setenv("GRADE_DAILY_CAP", "2")
    gate.reserve("u1")
    gate.reserve("u2")
    with pytest.raises(HTTPException) as e:   # global cap hit regardless of user balance
        gate.reserve("u3")
    assert e.value.status_code == 429


def test_grant_sets_balance(gate):
    gate.grant("u1", 7)
    assert gate.remaining("u1") == 7
    gate.grant("u1", 3)                       # overwrite (the Base44/Stripe seam)
    assert gate.remaining("u1") == 3


# ----------------------------------------------------------------- rate limit

def test_rate_limit_trips_at_threshold(gate, monkeypatch):
    monkeypatch.setenv("GRADE_RATE_PER_MIN", "3")
    for _ in range(3):
        gate.enforce_rate_limit("u1")
    with pytest.raises(HTTPException) as e:
        gate.enforce_rate_limit("u1")
    assert e.value.status_code == 429
    # a different user is unaffected
    gate.enforce_rate_limit("u2")


# ----------------------------------------------------------------- idempotency

def test_idempotency_replays_then_misses(gate, monkeypatch):
    k = gate.idem_key("u1", b"front", b"back")
    assert gate.idem_get(k) is None
    gate.idem_put(k, {"ok": True})
    assert gate.idem_get(k) == {"ok": True}
    # different images -> different key -> miss
    assert gate.idem_get(gate.idem_key("u1", b"front", b"OTHER")) is None
    # expired -> miss
    monkeypatch.setattr(gate, "_IDEM_TTL", -1.0)
    assert gate.idem_get(k) is None
