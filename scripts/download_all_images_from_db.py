"""Download every card's face image from the DB `image_url` into the layout that
build_embedding_index.py expects: data/cardmarket/images/{set_id}/{lang}_{tcgdex_id}.jpg

Works locally AND on a fresh RunPod box (avoids uploading the multi-GB image dir —
the pod just re-downloads from the CDN). Skips files already present.

TCGdex asset URLs (https://assets.tcgdex.net/.../{n}) have no extension -> append /high.jpg.
JP/TW scraped URLs are already full image URLs -> used as-is.

Usage: PYTHONUTF8=1 python scripts/download_all_images_from_db.py [--workers 16] [--limit N]
"""
import sys, argparse
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.db import get_connection

IMAGES = Path("data/cardmarket/images")
ap = argparse.ArgumentParser()
ap.add_argument("--workers", type=int, default=16)
ap.add_argument("--limit", type=int, default=0)
args = ap.parse_args()

c = get_connection(None)
q = "SELECT tcgdex_id, set_id, language, image_url FROM cards WHERE image_url IS NOT NULL AND image_url!=''"
if args.limit:
    q += f" LIMIT {args.limit}"
rows = c.execute(q).fetchall()
print(f"cards with image_url: {len(rows)}")

s = requests.Session(); s.headers.update({"User-Agent": "CardChecker/1.0"})

def url_for(image_url):
    u = image_url.strip()
    if "assets.tcgdex.net" in u and not u.lower().endswith((".jpg", ".png", ".webp")):
        return u.rstrip("/") + "/high.jpg"
    return u

def dl(row):
    tid, sid, lang, image_url = row["tcgdex_id"], row["set_id"], row["language"], row["image_url"]
    d = IMAGES / (sid or "misc");
    fn = d / f"{lang}_{tid}.jpg"
    if fn.exists() and fn.stat().st_size > 0:
        return "skip"
    try:
        d.mkdir(parents=True, exist_ok=True)
        r = s.get(url_for(image_url), timeout=30)
        if r.status_code == 200 and r.content:
            fn.write_bytes(r.content); return "ok"
        # tcgdex fallback to png
        if "assets.tcgdex.net" in image_url:
            r = s.get(image_url.rstrip("/") + "/high.png", timeout=30)
            if r.status_code == 200 and r.content:
                fn.write_bytes(r.content); return "ok"
        return f"fail{r.status_code}"
    except Exception as e:
        return f"err:{type(e).__name__}"

ok = skip = fail = 0
with ThreadPoolExecutor(max_workers=args.workers) as pool:
    futs = [pool.submit(dl, r) for r in rows]
    for i, f in enumerate(as_completed(futs)):
        st = f.result()
        if st == "ok": ok += 1
        elif st == "skip": skip += 1
        else:
            fail += 1
            if fail <= 20: print("  ", st)
        if (i + 1) % 5000 == 0:
            print(f"  {i+1}/{len(rows)}  ok={ok} skip={skip} fail={fail}")
print(f"DONE ok={ok} skip={skip} fail={fail}")
