"""Base44 identity + credit integration for the paid /grade endpoint.

The webapp forwards the user's Base44 JWT as `Authorization: Bearer <token>`. We verify it
with one call to Base44's REST "me" endpoint (which returns identity + tier in one shot), then
enforce the per-tier grade limit against the Base44 `CreditTransaction` ledger — the SAME
counter the webapp shows the user — and write the spend back as a `CreditTransaction` AFTER a
successful grade. This makes Base44 the source of truth for credits (closing the old
client-only, trivially-bypassable gate) instead of a separate backend silo.

Charge-after-success means no reserve/refund dance: if the Claude call fails we simply never
write the transaction. Concurrency note: the count→charge window is not atomic in Base44, so
two simultaneous same-user requests could overspend by 1; the per-user rate limit
(src/grade_gate) makes that negligible for beta. Move to a server-side atomic counter if it
ever matters.

Env:
  BASE44_APP_ID      live app id (default = the production CardChecker app).
  BASE44_SERVER_URL  REST base (default https://base44.app/api).
  GRADE_BETA_ADMIN_ONLY  "1" (default) => only role==admin may grade (beta gate, server-side).
"""
from __future__ import annotations

import json
import os

import requests
from fastapi import HTTPException

APP_ID = os.getenv("BASE44_APP_ID", "68ea74b77adcd0f5e1c2008e")
SERVER = os.getenv("BASE44_SERVER_URL", "https://base44.app/api").rstrip("/")
_TIMEOUT = 8.0

# Mirror of the webapp's src/config/tiers.js (grade limits per tier). inf = unlimited on that axis.
TIER_LIMITS = {
    "free": {"week": 3, "month": 12},
    "plus": {"week": float("inf"), "month": 50},
    "pro":  {"week": float("inf"), "month": 300},
}
GRADE_REASON = "grade"   # CreditTransaction.reason the webapp uses to count a grade


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "X-App-Id": APP_ID,
            "Content-Type": "application/json"}


def verify_user(token: str) -> dict:
    """Validate the bearer token with Base44 and return the User record (id, email, role,
    subscription_tier). Raises 401 on any failure — we never trust an unverified caller."""
    if not token:
        raise HTTPException(status_code=401, detail="Missing authentication")
    url = f"{SERVER}/apps/{APP_ID}/entities/User/me"
    try:
        r = requests.get(url, headers=_headers(token), timeout=_TIMEOUT)
    except requests.RequestException as e:
        # identity provider unreachable — fail closed (can't safely spend money for an unknown user)
        raise HTTPException(status_code=503, detail="Auth service unavailable") from e
    if r.status_code in (401, 403):
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    if r.status_code != 200:
        raise HTTPException(status_code=502, detail="Auth check failed")
    try:
        return r.json()
    except ValueError as e:
        raise HTTPException(status_code=502, detail="Auth check returned bad data") from e


def assert_beta_access(user: dict) -> None:
    """During beta, only admins may grade (server-side mirror of the webapp's admin route gate)."""
    if os.getenv("GRADE_BETA_ADMIN_ONLY", "1") == "1" and user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Pregrading is in limited beta")


def grade_counts(token: str, email: str) -> tuple[int, int]:
    """Return (grades_this_week, grades_this_month) from the Base44 CreditTransaction ledger,
    mirroring useSubscription.jsx (filter by created_by + reason=='grade', count by date window).

    Counting is done in-process over the most recent rows (the webapp pulls up to 500), so we
    don't depend on Base44's date-filter query syntax. On a read error we raise 503 (fail closed)
    — the caller may choose to fall back to the local ledger."""
    import datetime as _dt
    url = f"{SERVER}/apps/{APP_ID}/entities/CreditTransaction"
    params = {"q": json.dumps({"created_by": email}), "sort": "-created_date", "limit": 500}
    try:
        r = requests.get(url, headers=_headers(token), params=params, timeout=_TIMEOUT)
        r.raise_for_status()
        rows = r.json()
    except (requests.RequestException, ValueError) as e:
        raise HTTPException(status_code=503, detail="Credit check unavailable") from e
    if isinstance(rows, dict):                      # some shapes wrap in {"items"/"data": [...]}
        rows = rows.get("items") or rows.get("data") or rows.get("entities") or []
    now = _dt.datetime.now(_dt.timezone.utc)
    week_start = now - _dt.timedelta(days=7)
    month_start = now - _dt.timedelta(days=30)
    wk = mo = 0
    for t in rows:
        if t.get("reason") != GRADE_REASON:
            continue
        cd = t.get("created_date") or t.get("created_at") or ""
        try:
            ts = _dt.datetime.fromisoformat(str(cd).replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=_dt.timezone.utc)
        except ValueError:
            continue
        if ts >= month_start:
            mo += 1
            if ts >= week_start:
                wk += 1
    return wk, mo


def within_limit(tier: str | None, week: int, month: int) -> bool:
    lim = TIER_LIMITS.get((tier or "free").lower(), TIER_LIMITS["free"])
    return week < lim["week"] and month < lim["month"]


def remaining(tier: str | None, week: int, month: int) -> int:
    lim = TIER_LIMITS.get((tier or "free").lower(), TIER_LIMITS["free"])
    left = min(lim["week"] - week, lim["month"] - month)
    return int(left) if left != float("inf") else 9999


def charge_grade(token: str, reference_id: str | None = None) -> None:
    """Write the grade spend to Base44 AFTER a successful grade. Best-effort: a charge failure
    is logged but does not fail the user's already-completed grade (we don't want to 500 after
    delivering a result). Surfaces as a metric to reconcile."""
    url = f"{SERVER}/apps/{APP_ID}/entities/CreditTransaction"
    body = {"reason": GRADE_REASON, "amount": 0, "balance_after": 0}
    if reference_id:
        body["reference_id"] = reference_id
    try:
        r = requests.post(url, headers=_headers(token), json=body, timeout=_TIMEOUT)
        r.raise_for_status()
    except (requests.RequestException, ValueError) as e:
        print(f"[base44] WARNING: failed to record grade charge: {type(e).__name__}: {e}")
