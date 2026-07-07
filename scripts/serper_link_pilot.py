from __future__ import annotations

"""
Serper link-sourcing PILOT.

Goal: measure how well a Google SERP (via Serper.dev) recovers *direct product
URLs* on CardMarket / PriceCharting / TCGplayer for our cards — especially the
JP/TW cards where our own coverage is near zero.

Approach (validated by hand first):
  * one query PER PLATFORM using a `site:` domain filter — this is what makes
    CardMarket surface (a blended 3-platform query buries it).
  * pick the first organic result whose URL matches that platform's *product*
    URL shape (not a search/category/species page).
  * verify by matching the card's collector number against the digits in the
    product slug/title. Number-less cards can't self-verify -> flagged manual,
    but we record the number the SERP *suggests* (backfill candidate).

Reads the stratified sample built from prod (scripts/_link_pilot_sample.json).
Writes scripts/_link_pilot_results.json + prints a scorecard.

API key: env SERPER_API_KEY, else a line `SERPER_API_KEY=...` in .env.serper
(repo root) or data/.env.serper. NEVER commit the key.

Usage:
  ./venv/Scripts/python.exe scripts/serper_link_pilot.py --dry-run        # preview queries only
  ./venv/Scripts/python.exe scripts/serper_link_pilot.py                  # full run (needs key)
  ./venv/Scripts/python.exe scripts/serper_link_pilot.py --limit 20       # small run
  ./venv/Scripts/python.exe scripts/serper_link_pilot.py --platforms cardmarket,tcgplayer
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SAMPLE_DEFAULT = ROOT / "scripts" / "_link_pilot_sample.json"
OUT_DEFAULT = ROOT / "scripts" / "_link_pilot_results.json"

SERPER_ENDPOINT = "https://google.serper.dev/search"

DOMAINS = {
    "cardmarket": "cardmarket.com",
    "pricecharting": "pricecharting.com",
    "tcgplayer": "tcgplayer.com",
}

# --- product-URL patterns (accept only real product pages) -----------------
# CardMarket product: /{loc}/Pokemon/Products/Singles/{Expansion}/{Slug}
#   (two path segments after Singles -> reject bare category page)
CM_PRODUCT = re.compile(
    r"cardmarket\.com/[^/]+/Pokemon/Products/Singles/[^/]+/[^/?#]+", re.I
)
# PriceCharting product: /game/{console-slug}/{card-slug}
PC_PRODUCT = re.compile(r"pricecharting\.com/game/[^/]+/[^/?#]+", re.I)
# TCGplayer product: /product/{id}/...
TCG_PRODUCT = re.compile(r"tcgplayer\.com/product/(\d+)", re.I)

PC_REJECT = ("/search-products", "/console/", "/category/", "/pop/")


def load_key() -> str | None:
    key = os.environ.get("SERPER_API_KEY")
    if key:
        return key.strip()
    for p in (ROOT / ".env.serper", ROOT / "data" / ".env.serper"):
        if p.exists():
            for line in p.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("SERPER_API_KEY="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def clean_name(name: str) -> str:
    name = re.sub(r"\s*\[.*?\]", "", name or "")
    name = re.sub(r"\s*\(.*?\)", "", name)
    return name.strip()


def strip_set_prefix(set_id: str) -> str:
    return re.sub(r"^(tw-|jp-)", "", set_id or "")


def build_query(card: dict, platform: str, with_set: bool = True) -> str:
    """Build a `site:`-scoped Google query for one card + platform.

    with_set=False drops the set reference — a fallback for when our internal
    set-code doesn't match the platform's naming and actively hurts recall.
    """
    lang = card.get("language", "en")
    name = clean_name(card.get("eng_name") or card.get("name") or "")

    num = card.get("collector_number")
    total = card.get("set_total")
    num_ref = ""
    if num not in (None, ""):
        num_ref = f"{num}/{total}" if total else str(num)

    if lang == "en":
        set_ref = card.get("set_name") or strip_set_prefix(card.get("set_id", ""))
        lang_hint = ""
    elif lang == "ja":
        # JP: the set *code* (CP6, SV9, M-P) matches CM/TCG far better than the
        # Japanese set name; add "japanese" as a disambiguator.
        set_ref = strip_set_prefix(card.get("set_id", ""))
        lang_hint = "japanese"
    else:  # zh-tw -> matched via its JP/EN-equivalent product; code beats CN name
        set_ref = strip_set_prefix(card.get("set_id", ""))
        lang_hint = "japanese"  # TW cards live under JP/EN products, not "chinese"

    if not with_set:
        set_ref = ""
    parts = [name, set_ref, num_ref, lang_hint, "pokemon",
             f"site:{DOMAINS[platform]}"]
    return " ".join(p for p in parts if p).strip()


def serper_search(q: str, key: str, gl: str = "us", hl: str = "en",
                  retries: int = 3) -> list[dict]:
    body = json.dumps({"q": q, "gl": gl, "hl": hl, "num": 10}).encode()
    req = urllib.request.Request(
        SERPER_ENDPOINT, data=body, method="POST",
        headers={"X-API-KEY": key, "Content-Type": "application/json"},
    )
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r).get("organic", []) or []
        except urllib.error.HTTPError as e:
            if e.code == 429 or e.code >= 500:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise
        except (urllib.error.URLError, TimeoutError):
            time.sleep(1.0 * (attempt + 1))
    return []


TCG_JUNK = ("deck", "sealed", "booster", "-box", "bundle", "case", "tin",
            "collection-box", "elite-trainer")


def _num_forms(card: dict) -> set[str]:
    num = card.get("collector_number")
    if num in (None, ""):
        return set()
    num = str(num)
    forms = {num, num.lstrip("0") or num}
    if num.isdigit():
        forms.add(f"{int(num):03d}")
    return forms


def pick_product_url(platform: str, organic: list[dict],
                     card: dict) -> tuple[str | None, str | None]:
    """Return (product_url, id_or_slug).

    Collect all product-shaped hits, then prefer the one whose url/title carries
    the card's collector number (disambiguates same-name prints); else first.
    TCGplayer: drop sealed/deck/box products (they poison same-name matches).
    """
    cands: list[tuple[str, str, str]] = []  # (url, ident, title)
    for hit in organic:
        url = hit.get("link", "") or ""
        title = hit.get("title", "") or ""
        if platform == "cardmarket":
            if CM_PRODUCT.search(url) and "/Cards/" not in url:
                cands.append((url, url.rstrip("/").split("/")[-1].split("?")[0], title))
        elif platform == "pricecharting":
            if PC_PRODUCT.search(url) and not any(b in url for b in PC_REJECT):
                cands.append((url, url.rstrip("/").split("/")[-1].split("?")[0], title))
        elif platform == "tcgplayer":
            m = TCG_PRODUCT.search(url)
            if m and not any(j in (url + " " + title).lower() for j in TCG_JUNK):
                cands.append((url, m.group(1), title))
    if not cands:
        return None, None
    forms = _num_forms(card)
    if forms:
        for url, ident, title in cands:
            raw = (url + " " + title).lower()
            if any(re.search(rf"(?<!\d){re.escape(f)}(?!\d)", raw) for f in forms):
                return url, ident
    return cands[0][0], cands[0][1]


def digit_runs(text: str) -> list[str]:
    return re.findall(r"\d+", text or "")


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def set_tokens(card: dict) -> set[str]:
    """Distinctive set identifiers to look for in a result (code, abbr, name words)."""
    toks = set()
    for v in (strip_set_prefix(card.get("set_id", "")), card.get("set_abbr")):
        n = _norm(v or "")
        if len(n) >= 2:
            toks.add(n)
    for w in re.findall(r"[A-Za-z]+", card.get("set_name") or ""):
        if len(w) >= 4:  # skip "of", "the", "&" etc.
            toks.add(w.lower())
    return toks


def verify(card: dict, url: str, ident: str,
           title: str) -> tuple[bool | None, str, str | None]:
    """(verified, signal, suggested_number).

    signal ∈ {"number","set","none"} — HOW we confirmed the match.
    verified True/False when the card has a number; None for number-less cards
    (-> manual bucket), but we still extract a suggested number for backfill.

    TCGplayer titles often omit the collector number, so we fall back to a SET
    match (the set name/code is reliably present) instead of failing.
    """
    raw = f"{url} {title} {ident}".lower()
    hay = _norm(raw)
    num = card.get("collector_number")
    total = card.get("set_total")

    set_ok = any(t in hay for t in set_tokens(card))

    if num in (None, ""):
        suggested = digit_runs(ident) or digit_runs(title)
        return None, ("set" if set_ok else "none"), (suggested[-1] if suggested else None)

    num = str(num)
    forms = {num, num.lstrip("0") or num}
    if num.isdigit():
        forms.add(f"{int(num):03d}")
    # strong: "num/total"; medium: bare bounded number
    num_ok = False
    if total:
        if any(re.search(rf"(?<!\d){re.escape(f)}\s*[/\-]\s*{int(total)}", raw)
               for f in forms):
            num_ok = True
    if not num_ok:
        num_ok = any(re.search(rf"(?<!\d){re.escape(f)}(?!\d)", raw) for f in forms)

    if num_ok:
        return True, "number", None
    if set_ok:
        return True, "set", None
    return False, "none", None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", default=str(SAMPLE_DEFAULT))
    ap.add_argument("--out", default=str(OUT_DEFAULT))
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--platforms", default="cardmarket,pricecharting,tcgplayer")
    ap.add_argument("--langs", default="", help="comma list, e.g. ja,zh-tw")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the queries and exit; no API calls, no key needed")
    ap.add_argument("--sleep", type=float, default=0.15)
    args = ap.parse_args()

    platforms = [p.strip() for p in args.platforms.split(",") if p.strip()]
    cards = json.loads(Path(args.sample).read_text(encoding="utf-8"))
    if args.langs:
        want = {x.strip() for x in args.langs.split(",") if x.strip()}
        cards = [c for c in cards if c["language"] in want]
    if args.limit:
        cards = cards[: args.limit]

    if args.dry_run:
        for c in cards[:15]:
            print(f"\n{c['tcgdex_id']} [{c['_stratum']}] {c.get('eng_name') or c.get('name')}")
            for p in platforms:
                print(f"  {p:14s} {build_query(c, p)}")
        print(f"\n({len(cards)} cards x {len(platforms)} platforms = "
              f"{len(cards) * len(platforms)} queries)")
        return 0

    key = load_key()
    if not key:
        print("ERROR: no SERPER_API_KEY (env or .env.serper). See script header.",
              file=sys.stderr)
        return 2

    total_q = len(cards) * len(platforms)
    print(f"Running {len(cards)} cards x {len(platforms)} platforms = {total_q} queries...")
    results = []
    n_calls = 0
    for i, c in enumerate(cards, 1):
        row = {k: c.get(k) for k in
               ("tcgdex_id", "_stratum", "language", "name", "eng_name",
                "collector_number", "set_id", "set_total", "cm_id_product",
                "tcgplayer_id", "cm_share")}
        row["platforms"] = {}
        for p in platforms:
            q = build_query(c, p)
            organic = serper_search(q, key)
            n_calls += 1
            url, ident = pick_product_url(p, organic, c)
            # fallback: our set-code may not match the platform's naming -> retry
            # without it (name + number is often enough for a product hit)
            if not url:
                q2 = build_query(c, p, with_set=False)
                if q2 != q:
                    organic = serper_search(q2, key)
                    n_calls += 1
                    url, ident = pick_product_url(p, organic, c)
                    if url:
                        q = q2
            title = ""
            if url:
                for hit in organic:
                    if hit.get("link") == url:
                        title = hit.get("title", "")
                        break
            verified, signal, suggested = (None, "none", None)
            if url:
                verified, signal, suggested = verify(c, url, ident or "", title)
            row["platforms"][p] = {
                "query": q, "url": url, "id_or_slug": ident,
                "title": title, "verified": verified, "signal": signal,
                "suggested_number": suggested, "found": bool(url),
            }
            time.sleep(args.sleep)
        results.append(row)
        if i % 20 == 0:
            print(f"  {i}/{len(cards)} cards ({n_calls} calls)")

    Path(args.out).write_text(json.dumps(results, ensure_ascii=False, indent=2),
                              encoding="utf-8")

    # ---- scorecard -------------------------------------------------------
    print("\n================ SCORECARD ================")
    agg = defaultdict(lambda: defaultdict(lambda: [0, 0, 0, 0, 0]))
    # per (lang, platform): [n, found, verified_true, new_id, set_only_signal]
    for row in results:
        lang = row["language"]
        for p in platforms:
            pr = row["platforms"][p]
            cell = agg[lang][p]
            cell[0] += 1
            if pr["found"]:
                cell[1] += 1
            if pr["verified"] is True:
                cell[2] += 1
            if pr.get("signal") == "set":
                cell[4] += 1
            # "new" = we gain an id/link we didn't have
            if p == "tcgplayer" and pr["found"] and not row.get("tcgplayer_id"):
                cell[3] += 1
            if p == "cardmarket" and pr["found"]:
                cell[3] += 1  # slug URL we never stored (cm_url_slug is empty)
    for lang in ("en", "ja", "zh-tw"):
        if lang not in agg:
            continue
        print(f"\n[{lang}]")
        for p in platforms:
            n, found, ver, new, setonly = agg[lang][p]
            if not n:
                continue
            print(f"  {p:14s} found {found:3d}/{n:3d} ({100*found//max(n,1):3d}%)"
                  f"  verified {ver:3d}/{n:3d} ({100*ver//max(n,1):3d}%)"
                  f"  [set-sig {setonly:3d}]  new {new:3d}")
    print(f"\nTotal Serper calls: {n_calls}")
    print(f"Results: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
