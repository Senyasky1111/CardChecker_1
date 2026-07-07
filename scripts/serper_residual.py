from __future__ import annotations

"""
Serper residual runner — Google-fill the cards the offline catalogs missed.

Reads scripts/_residual.json (EN+JA cards lacking a direct link, per platform),
builds ONE site:-scoped query per missing (card, platform), parses the product
URL, verifies (collector number present in slug/url), and records a write.

Two modes:
  --measure N   stratified sample (~N per stratum) to learn find-rate per
                (lang, era, platform) before committing to a full/paid run.
  --full        every missing (card, platform) up to --budget queries.

Stratum = lang(en/ja) x era(modern/old) x platform. Era(ja): "old" if the set is
DP/BW/XY/L/HS/MC/promo era, else "modern". Applies nothing to prod — writes
scripts/_serper_residual_writes.json + prints a scorecard.

Usage:
  ./venv/Scripts/python.exe scripts/serper_residual.py --measure 50
  ./venv/Scripts/python.exe scripts/serper_residual.py --full --budget 1200
"""

import argparse
import json
import re
import sys
import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.serper_link_pilot import (  # noqa: E402
    build_query, serper_search, pick_product_url, verify, load_key,
)

RESIDUAL = ROOT / "scripts" / "_residual.json"
WRITES = ROOT / "scripts" / "_serper_residual_writes.json"
RESULTS = ROOT / "scripts" / "_serper_residual_results.json"

OLD_JA = re.compile(r"^(DP|BW|XY|L[0-9]|L-|HS|MC|EP|PP|WCP|MPS|DS|SC$|Bk|Br|SO|Em)", re.I)
PROMO = re.compile(r"(-P$|^.{0,3}P$|Promo|BWP|XYP|SMP|SVP|LP$|M-P|S-P)", re.I)


def era(lang: str, set_id: str) -> str:
    if lang == "en":
        return "en"
    if OLD_JA.match(set_id) or PROMO.search(set_id):
        return "old"
    return "modern"


def card_for_query(c: dict) -> dict:
    d = dict(c)
    d["set_abbr"] = c.get("abbreviation") or ""
    return d


def platform_write(platform: str, lang: str, tcgdex_id: str,
                   url: str, ident: str) -> dict | None:
    if platform == "tcgplayer":
        return {"tcgdex_id": tcgdex_id, "language": lang,
                "tcgplayer_id": int(ident), "tcgplayer_url": url}
    if platform == "pricecharting":
        return {"tcgdex_id": tcgdex_id, "language": lang,
                "pricecharting_url": url}
    if platform == "cardmarket":
        # slug = path after /Singles/
        m = re.search(r"/Singles/(.+)$", url)
        slug = m.group(1).split("?")[0].rstrip("/") if m else ident
        return {"tcgdex_id": tcgdex_id, "language": lang, "cm_url_slug": slug}
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--measure", type=int, default=0, help="~N per stratum")
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--budget", type=int, default=1200)
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--sleep", type=float, default=0.12)
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    key = load_key()
    if not key:
        print("ERROR: no SERPER_API_KEY", file=sys.stderr)
        return 2

    data = json.loads(RESIDUAL.read_text(encoding="utf-8"))
    # build tasks: (stratum, platform, card)
    tasks = []
    for lang in ("en", "ja"):
        for c in data[lang]:
            e = era(lang, c["set_id"])
            for plat, flag in (("cardmarket", "miss_cm"),
                               ("tcgplayer", "miss_tcg"),
                               ("pricecharting", "miss_pc")):
                if c.get(flag):
                    tasks.append((f"{e}:{plat}", plat, c))

    # stratified sampling for --measure (deterministic: stride, no RNG)
    if args.measure:
        by = defaultdict(list)
        for t in tasks:
            by[t[0]].append(t)
        picked = []
        for stratum, lst in sorted(by.items()):
            step = max(1, len(lst) // args.measure)
            picked.extend(lst[::step][: args.measure])
        tasks = picked
    if len(tasks) > args.budget:
        tasks = tasks[: args.budget]

    print(f"running {len(tasks)} Serper queries "
          f"({'measure' if args.measure else 'full'}) x{args.workers} workers...")

    writes = []
    results = []
    agg = defaultdict(lambda: [0, 0, 0])  # stratum -> [n, found, verified]
    lock = threading.Lock()
    done = [0]

    def work(task):
        stratum, plat, c = task
        card = card_for_query(c)
        q = build_query(card, plat)
        organic = serper_search(q, key)
        url, ident = pick_product_url(plat, organic, card)
        if not url:
            q2 = build_query(card, plat, with_set=False)
            if q2 != q:
                organic = serper_search(q2, key)
                url, ident = pick_product_url(plat, organic, card)
        title = ""
        if url:
            for h in organic:
                if h.get("link") == url:
                    title = h.get("title", "")
                    break
        verified = None
        if url:
            verified, _sig, _sug = verify(card, url, ident or "", title)
        w = None
        if verified is True:
            w = platform_write(plat, c["language"], c["tcgdex_id"], url, ident)
        with lock:
            cell = agg[stratum]
            cell[0] += 1
            if url:
                cell[1] += 1
            if verified is True:
                cell[2] += 1
                if w:
                    writes.append(w)
            results.append({"tcgdex_id": c["tcgdex_id"], "stratum": stratum,
                            "platform": plat, "url": url, "verified": verified})
            done[0] += 1
            if done[0] % 500 == 0:
                print(f"  {done[0]}/{len(tasks)}  (verified {len(writes)})",
                      flush=True)

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        list(ex.map(work, tasks))

    WRITES.write_text(json.dumps(writes, ensure_ascii=False), encoding="utf-8")
    RESULTS.write_text(json.dumps(results, ensure_ascii=False), encoding="utf-8")

    print("\n================ SERPER RESIDUAL — SCORECARD ================")
    print(f"{'stratum':22s}{'n':>6}{'found':>10}{'verified':>12}")
    tot = [0, 0, 0]
    for stratum in sorted(agg):
        n, f, v = agg[stratum]
        tot[0] += n; tot[1] += f; tot[2] += v
        print(f"{stratum:22s}{n:>6}{f:>7}({100*f//max(n,1):3d}%){v:>8}({100*v//max(n,1):3d}%)")
    print(f"{'TOTAL':22s}{tot[0]:>6}{tot[1]:>7}({100*tot[1]//max(tot[0],1):3d}%)"
          f"{tot[2]:>8}({100*tot[2]//max(tot[0],1):3d}%)")
    print(f"\nverified direct links found: {len(writes)}  -> {WRITES}")
    print(f"Serper queries used (approx): {len(tasks)} + codeless retries")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
