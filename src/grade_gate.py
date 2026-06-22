"""Auth + billing gate for the paid /grade endpoint.

Self-contained server-side ENFORCEMENT layer that stops the two real risks of a
money-spending endpoint: (1) anonymous callers burning the Anthropic budget, and
(2) concurrent / retry double-spend. It is deliberately independent of Base44/Stripe —
those stay the product-facing source of truth (tiers, purchases, the UI counter); this
is the backstop that physically prevents overspend even if the client is wrong or hostile.

RECONCILIATION SEAM (TZ B4): Base44 is the live counter the user sees. This ledger is the
authoritative *spend* gate. Wire them by either (a) seeding/topping this ledger from Base44
on plan change / purchase (webhook), or (b) replacing reserve()/refund() with a Base44
atomic-decrement call. Until that sync exists, this ledger enforces a per-user allowance so
the budget can't be drained; the frontend ALSO gates via Base44 (defense in depth).

Env config (all optional; unset => permissive dev mode, logged loudly at first use):
  GRADE_API_SECRET   shared secret the webapp must send as the X-Grade-Secret header.
                     If set, requests without a matching secret are 401. If UNSET, auth is
                     disabled (local dev) and the caller's user id (or 'dev') is trusted.
  GRADE_FREE_CREDITS per-user grade allowance seeded on first sight (default 5).
  GRADE_RATE_PER_MIN max grades per user per minute (default 5).
  GRADE_DAILY_CAP    global daily grade cap across all users — cost circuit-breaker (default 500).

NOTE: rate-limit + idempotency caches are in-process (fine for a single uvicorn worker / beta).
With multiple workers, move them to the DB or Redis. The credit + daily-cap ledger IS durable
and cross-process safe (single atomic SQLite UPDATE ... WHERE remaining > 0).
"""
from __future__ import annotations

import os
import sqlite3
import threading
import time
import hashlib
from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException

DB_PATH = Path("./data/grade_credits.db")

_lock = threading.Lock()
_rate: dict[str, list[float]] = {}          # user_id -> recent grade timestamps (sliding window)
_idem: dict[str, tuple[float, dict]] = {}   # idem_key -> (ts, result)
_IDEM_TTL = 120.0                            # seconds a result is replayable for a retry
_warned_no_secret = False


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH, timeout=10)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA busy_timeout=5000")
    return c


def init_db() -> None:
    with _conn() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS credits (
                user_id   TEXT PRIMARY KEY,
                remaining INTEGER NOT NULL,
                updated   TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS daily_usage (
                day   TEXT PRIMARY KEY,
                count INTEGER NOT NULL
            );
            """
        )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


# ------------------------------------------------------------------ auth

def authenticate(secret_header: str | None, user_id_header: str | None) -> str:
    """Return the caller's user id, or raise 401/400. Shared-secret auth.

    The webapp holds GRADE_API_SECRET and sends it as X-Grade-Secret; the Base44 user id
    rides along in X-User-Id. We trust the user id because the secret proves the caller is
    our webapp (not an anonymous internet client). If the secret is unset we're in dev mode.
    """
    global _warned_no_secret
    expected = os.getenv("GRADE_API_SECRET")
    if expected:
        if not secret_header or secret_header != expected:
            raise HTTPException(status_code=401, detail="Unauthorized")
        if not user_id_header:
            raise HTTPException(status_code=400, detail="Missing user identity")
        return user_id_header
    # dev mode — no secret configured
    if not _warned_no_secret:
        print("[grade_gate] WARNING: GRADE_API_SECRET unset — /grade auth disabled (dev mode). "
              "Set it before exposing /grade publicly.")
        _warned_no_secret = True
    return user_id_header or "dev"


# ------------------------------------------------------------------ rate limit

def enforce_rate_limit(user_id: str) -> None:
    """Per-user sliding-window limit (in-process). Raises 429 when exceeded."""
    per_min = _env_int("GRADE_RATE_PER_MIN", 5)
    now = time.time()
    with _lock:
        hits = [t for t in _rate.get(user_id, []) if now - t < 60.0]
        if len(hits) >= per_min:
            raise HTTPException(status_code=429, detail="Too many grade requests, slow down")
        hits.append(now)
        _rate[user_id] = hits


# ------------------------------------------------------------------ idempotency

def idem_key(user_id: str, front_bytes: bytes, back_bytes: bytes) -> str:
    h = hashlib.sha256()
    h.update(user_id.encode())
    h.update(b"\x00")
    h.update(front_bytes)
    h.update(b"\x00")
    h.update(back_bytes)
    return h.hexdigest()


def idem_get(key: str) -> dict | None:
    now = time.time()
    with _lock:
        hit = _idem.get(key)
        if hit and now - hit[0] < _IDEM_TTL:
            return hit[1]
        if hit:
            _idem.pop(key, None)
    return None


def idem_put(key: str, result: dict) -> None:
    now = time.time()
    with _lock:
        _idem[key] = (now, result)
        # opportunistic cleanup
        for k in [k for k, v in _idem.items() if now - v[0] >= _IDEM_TTL]:
            _idem.pop(k, None)


# ------------------------------------------------------------------ credits (durable, atomic)

def reserve(user_id: str) -> None:
    """Atomically reserve one grade credit + bump the global daily cap BEFORE spending money.

    Raises 402 when the user is out of credits, 429 when the global daily cap is hit. The
    decrement is a single atomic SQLite UPDATE ... WHERE remaining > 0 (no read-then-write
    race), so concurrent requests can't overspend. Seeds a new user with GRADE_FREE_CREDITS.
    """
    free = _env_int("GRADE_FREE_CREDITS", 5)
    daily_cap = _env_int("GRADE_DAILY_CAP", 500)
    day = _today()
    with _conn() as c:
        c.execute("BEGIN IMMEDIATE")
        # global daily circuit-breaker
        row = c.execute("SELECT count FROM daily_usage WHERE day = ?", (day,)).fetchone()
        used_today = row[0] if row else 0
        if used_today >= daily_cap:
            c.execute("ROLLBACK")
            raise HTTPException(status_code=429, detail="Daily grading capacity reached, try again tomorrow")
        # seed new user
        c.execute("INSERT OR IGNORE INTO credits(user_id, remaining, updated) VALUES (?, ?, ?)",
                  (user_id, free, _now_iso()))
        # atomic decrement
        cur = c.execute("UPDATE credits SET remaining = remaining - 1, updated = ? "
                        "WHERE user_id = ? AND remaining > 0", (_now_iso(), user_id))
        if cur.rowcount != 1:
            c.execute("ROLLBACK")
            raise HTTPException(status_code=402, detail="No grade credits remaining")
        # commit the daily usage only after the user decrement succeeded
        c.execute("INSERT INTO daily_usage(day, count) VALUES (?, 1) "
                  "ON CONFLICT(day) DO UPDATE SET count = count + 1", (day,))
        c.execute("COMMIT")


def daily_reserve() -> None:
    """Atomically bump ONLY the global daily cap (used in Base44 mode, where per-user credits
    live in Base44 but we still want a server-side cost circuit-breaker). Raises 429 when hit."""
    daily_cap = _env_int("GRADE_DAILY_CAP", 500)
    day = _today()
    with _conn() as c:
        c.execute("BEGIN IMMEDIATE")
        row = c.execute("SELECT count FROM daily_usage WHERE day = ?", (day,)).fetchone()
        if (row[0] if row else 0) >= daily_cap:
            c.execute("ROLLBACK")
            raise HTTPException(status_code=429, detail="Daily grading capacity reached, try again tomorrow")
        c.execute("INSERT INTO daily_usage(day, count) VALUES (?, 1) "
                  "ON CONFLICT(day) DO UPDATE SET count = count + 1", (day,))
        c.execute("COMMIT")


def daily_refund() -> None:
    """Roll back a daily-cap reservation when the paid call failed (Base44 mode)."""
    day = _today()
    try:
        with _conn() as c:
            c.execute("UPDATE daily_usage SET count = MAX(count - 1, 0) WHERE day = ?", (day,))
            c.commit()
    except Exception as e:
        print(f"[grade_gate] daily_refund failed: {type(e).__name__}: {e}")


def refund(user_id: str) -> None:
    """Give back a reserved credit when the paid call failed (idempotent per request: the
    endpoint only calls this once, on the failure path). Also rolls back the daily counter."""
    day = _today()
    try:
        with _conn() as c:
            c.execute("BEGIN IMMEDIATE")
            c.execute("UPDATE credits SET remaining = remaining + 1, updated = ? WHERE user_id = ?",
                      (_now_iso(), user_id))
            c.execute("UPDATE daily_usage SET count = MAX(count - 1, 0) WHERE day = ?", (day,))
            c.execute("COMMIT")
    except Exception as e:  # refund must never mask the original error
        print(f"[grade_gate] refund failed for {user_id}: {type(e).__name__}: {e}")


def remaining(user_id: str) -> int | None:
    with _conn() as c:
        row = c.execute("SELECT remaining FROM credits WHERE user_id = ?", (user_id,)).fetchone()
        return row[0] if row else None


def grant(user_id: str, credits: int) -> None:
    """Set/seed a user's balance — the seam Base44/Stripe calls on purchase/plan-change."""
    with _conn() as c:
        c.execute("INSERT INTO credits(user_id, remaining, updated) VALUES (?, ?, ?) "
                  "ON CONFLICT(user_id) DO UPDATE SET remaining = excluded.remaining, updated = excluded.updated",
                  (user_id, credits, _now_iso()))
        c.commit()
