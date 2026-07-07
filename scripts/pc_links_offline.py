from __future__ import annotations

"""
PriceCharting direct-URL resolver for JP/TW cards (offline-driven, HTTP-validated).

Reads the prod card dump (scripts/_prod_cards_eng.json), builds a candidate PC
direct URL for every card in a mapped set, then validates it via HTTP (PC
redirects to /search when the product doesn't exist -> we only keep URLs that
resolve to a real /game/ page). Validated URLs are written to
scripts/_pc_writes.json for a separate apply-to-prod step. NEVER writes a
non-existent/wrong link — invalid candidates are dropped (prod keeps its search
fallback).

Concurrency is modest + jittered to stay polite to PriceCharting.

Usage:
  ./venv/Scripts/python.exe scripts/pc_links_offline.py --langs ja,zh-tw
  ./venv/Scripts/python.exe scripts/pc_links_offline.py --langs ja --limit 300   # smoke
"""

import argparse
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from random import uniform

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.build_pricecharting_map import (  # noqa: E402
    JP_SET_SLUGS, TW_SET_SLUGS, PC_BASE, slugify_card_name,
)

CARDS = ROOT / "scripts" / "_prod_cards_eng.json"
OUT = ROOT / "scripts" / "_pc_writes.json"

_local = threading.local()


def _session() -> requests.Session:
    s = getattr(_local, "s", None)
    if s is None:
        s = requests.Session()
        s.headers["User-Agent"] = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120 Safari/537.36"
        )
        _local.s = s
    return s


def candidate_url(lang: str, set_id: str, eng: str, num) -> str | None:
    slug_map, prefix = (
        (JP_SET_SLUGS, "pokemon-japanese") if lang == "ja"
        else (TW_SET_SLUGS, "pokemon-chinese")
    )
    set_slug = slug_map.get(set_id)
    if not set_slug or not (eng or "").strip():
        return None
    card_slug = slugify_card_name(eng.strip())
    if not card_slug:
        return None
    if num is not None:
        try:
            card_slug = f"{card_slug}-{int(num)}"
        except (ValueError, TypeError):
            card_slug = f"{card_slug}-{num}"
    return f"{PC_BASE}/game/{prefix}-{set_slug}/{card_slug}"


def validate(url: str) -> bool:
    try:
        r = _session().get(url, timeout=12, allow_redirects=True)
        time.sleep(uniform(0.05, 0.2))
        return "/game/" in r.url and "/search" not in r.url
    except Exception:
        return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--langs", default="ja,zh-tw")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    cards = json.loads(CARDS.read_text(encoding="utf-8"))
    langs = [x.strip() for x in args.langs.split(",") if x.strip()]

    tasks = []  # (tcgdex_id, language, url)
    per_total = {}
    for lang in langs:
        rows = cards[lang]
        per_total[lang] = len(rows)
        for tcgdex_id, set_id, cnum, eng, cm_id, cm_slug in rows:
            u = candidate_url(lang, set_id, eng, cnum)
            if u:
                tasks.append((tcgdex_id, lang, u))
    if args.limit:
        tasks = tasks[: args.limit]

    print(f"candidates to validate: {len(tasks)} "
          f"(of {sum(per_total.values())} cards)")

    writes = []
    done = [0]
    valid = {l: 0 for l in langs}
    lock = threading.Lock()

    def work(t):
        tcgdex_id, lang, url = t
        ok = validate(url)
        with lock:
            done[0] += 1
            if ok:
                valid[lang] += 1
                writes.append({"tcgdex_id": tcgdex_id, "language": lang,
                               "pricecharting_url": url})
            if done[0] % 500 == 0:
                print(f"  {done[0]}/{len(tasks)} validated "
                      f"(valid so far: {dict(valid)})", flush=True)

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        list(ex.map(work, tasks))

    OUT.write_text(json.dumps(writes, ensure_ascii=False), encoding="utf-8")
    print("\n================ PC RESOLVE — RESULT ================")
    for lang in langs:
        tot = per_total[lang] or 1
        print(f"  {lang:6s} direct PC URLs validated: {valid[lang]}/{tot} "
              f"({100*valid[lang]//tot}%)")
    print(f"\nwrites: {OUT}  ({len(writes)} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
