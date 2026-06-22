"""Integration test for the POST /grade endpoint wiring (no Claude calls, no app lifespan).

Calls the async endpoint function directly with a mocked grader + mocked grade_card, a temp
credit DB, and real in-memory UploadFiles. Covers the gate ordering: auth -> rate-limit ->
idempotency -> reserve -> grade -> (refund on failure / cache on success), plus the negatives
(single-side rejected, exhausted -> 402, grader unconfigured -> 503).
"""
import asyncio
import io

import pytest
from PIL import Image
from fastapi import HTTPException
from starlette.datastructures import Headers, UploadFile

import src.api as api
import src.grade_gate as gate
import src.pregrade_service as svc
import src.base44_auth as b44


def _png() -> bytes:
    b = io.BytesIO()
    Image.new("RGB", (64, 64), (200, 100, 50)).save(b, "PNG")
    return b.getvalue()


def _upload(name: str, data: bytes) -> UploadFile:
    return UploadFile(filename=name, file=io.BytesIO(data),
                      headers=Headers({"content-type": "image/png"}))


def _call(front: UploadFile, back: UploadFile, user="u1", authorization=None):
    return asyncio.run(api.grade_card_endpoint(
        file=front, back_file=back, x_grade_secret=None, x_user_id=user,
        authorization=authorization))


@pytest.fixture
def wired(tmp_path, monkeypatch):
    """Temp credit DB, mocked grader + grade_card, env reset. Returns the call counter."""
    monkeypatch.setattr(gate, "DB_PATH", tmp_path / "credits.db")
    gate._rate.clear()
    gate._idem.clear()
    for k in ("GRADE_API_SECRET", "GRADE_FREE_CREDITS", "GRADE_RATE_PER_MIN", "GRADE_DAILY_CAP"):
        monkeypatch.delenv(k, raising=False)
    gate.init_db()
    monkeypatch.setattr(api, "_claude_grader", object())  # not None -> "configured"

    calls = {"n": 0, "raise": False}

    def fake_grade_card(grader, front_bytes, back_bytes, card_id="card",
                        front_centering_off=None, back_centering_off=None,
                        front_geo=None, back_geo=None):
        calls["n"] += 1
        if calls["raise"]:
            raise RuntimeError("simulated grader failure")
        return {"overall": {"most_likely": 6.0, "bucket": "EX", "label": "Excellent",
                            "distribution": [{"grade": 6, "prob": 1.0}]},
                "safety_floor": {"front": False, "back": False}}

    monkeypatch.setattr(svc, "grade_card", fake_grade_card)
    return calls


def test_happy_path_grades_and_decrements(wired, monkeypatch):
    monkeypatch.setenv("GRADE_FREE_CREDITS", "5")
    r = _call(_upload("f.png", _png()), _upload("b.png", _png()))
    assert r["overall"]["most_likely"] == 6.0
    assert wired["n"] == 1
    assert gate.remaining("u1") == 4


def test_idempotent_retry_does_not_recharge(wired, monkeypatch):
    monkeypatch.setenv("GRADE_FREE_CREDITS", "5")
    f, b = _png(), _png()
    _call(_upload("f.png", f), _upload("b.png", b))
    _call(_upload("f.png", f), _upload("b.png", b))   # same bytes -> cached replay
    assert wired["n"] == 1                              # grader called only once
    assert gate.remaining("u1") == 4                    # charged only once


def test_single_side_rejected_before_spend(wired):
    with pytest.raises(HTTPException) as e:
        _call(_upload("f.png", _png()), _upload("", b""))  # empty back
    assert e.value.status_code == 400
    assert wired["n"] == 0                              # never reached the grader
    assert gate.remaining("u1") is None                # never even seeded a credit row


def test_exhausted_returns_402_without_spend(wired, monkeypatch):
    monkeypatch.setenv("GRADE_FREE_CREDITS", "0")
    with pytest.raises(HTTPException) as e:
        _call(_upload("f.png", _png()), _upload("b.png", _png()))
    assert e.value.status_code == 402
    assert wired["n"] == 0


def test_grader_failure_refunds_credit(wired, monkeypatch):
    monkeypatch.setenv("GRADE_FREE_CREDITS", "5")
    wired["raise"] = True
    with pytest.raises(HTTPException) as e:
        _call(_upload("f.png", _png()), _upload("b.png", _png()))
    assert e.value.status_code == 502
    assert wired["n"] == 1
    assert gate.remaining("u1") == 5                    # reserved then refunded


def test_unconfigured_grader_returns_503(wired, monkeypatch):
    monkeypatch.setattr(api, "_claude_grader", None)
    with pytest.raises(HTTPException) as e:
        _call(_upload("f.png", _png()), _upload("b.png", _png()))
    assert e.value.status_code == 503


# ---------------------------------------------------------------- Base44 mode (token auth)

@pytest.fixture
def b44_wired(wired, monkeypatch):
    """On top of `wired`: mock the Base44 calls so no network happens. Returns counters."""
    monkeypatch.setenv("GRADE_BETA_ADMIN_ONLY", "1")
    state = {"charges": 0, "counts": (0, 0), "user": {"email": "a@x.com", "role": "admin",
                                                      "subscription_tier": "plus"}}
    monkeypatch.setattr(b44, "verify_user", lambda token: state["user"])
    monkeypatch.setattr(b44, "grade_counts", lambda token, email: state["counts"])

    def fake_charge(token, ref=None):
        state["charges"] += 1
    monkeypatch.setattr(b44, "charge_grade", fake_charge)
    return state


def test_base44_happy_path_charges_after_success(b44_wired, wired):
    r = _call(_upload("f.png", _png()), _upload("b.png", _png()), authorization="Bearer tok")
    assert r["overall"]["most_likely"] == 6.0
    assert wired["n"] == 1               # grader ran
    assert b44_wired["charges"] == 1     # Base44 charged exactly once, after success


def test_base44_over_limit_returns_402_no_spend(b44_wired, wired):
    b44_wired["counts"] = (50, 50)       # plus month limit is 50 -> over
    with pytest.raises(HTTPException) as e:
        _call(_upload("f.png", _png()), _upload("b.png", _png()), authorization="Bearer tok")
    assert e.value.status_code == 402
    assert wired["n"] == 0
    assert b44_wired["charges"] == 0


def test_base44_non_admin_blocked_in_beta(b44_wired, wired):
    b44_wired["user"] = {"email": "u@x.com", "role": "user", "subscription_tier": "plus"}
    with pytest.raises(HTTPException) as e:
        _call(_upload("f.png", _png()), _upload("b.png", _png()), authorization="Bearer tok")
    assert e.value.status_code == 403
    assert wired["n"] == 0


def test_require_base44_rejects_tokenless_call(wired, monkeypatch):
    monkeypatch.setenv("GRADE_REQUIRE_BASE44", "1")          # prod posture
    with pytest.raises(HTTPException) as e:
        _call(_upload("f.png", _png()), _upload("b.png", _png()))  # no Authorization
    assert e.value.status_code == 401
    assert wired["n"] == 0


def test_base44_failure_does_not_charge(b44_wired, wired):
    wired["raise"] = True
    with pytest.raises(HTTPException) as e:
        _call(_upload("f.png", _png()), _upload("b.png", _png()), authorization="Bearer tok")
    assert e.value.status_code == 502
    assert b44_wired["charges"] == 0     # never charged on failure
