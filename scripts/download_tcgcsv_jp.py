from __future__ import annotations

"""
Download the Pokemon JAPAN TCGplayer catalog (TCGCSV category 85) for offline
tcgplayer_id matching — the JP analogue of data/tcgplayer/all_products.json (EN,
category 3). Free, public, daily-refreshed.

Each product keeps: productId, name, cleanName, groupId, groupName, url, number
(from extendedData "Number"). The group name carries the JP set code
(e.g. "M2a: High Class Pack: MEGA Dream ex m2a") -> lets us join on (code, number).

Writes data/tcgplayer/jp_products.json + jp_groups.json.

Usage:
  ./venv/Scripts/python.exe scripts/download_tcgcsv_jp.py
"""

import json
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "data" / "tcgplayer"
BASE = "https://tcgcsv.com/tcgplayer/85"


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    s = requests.Session()
    s.headers["User-Agent"] = "CardChecker/1.0"

    groups = s.get(f"{BASE}/groups", timeout=30).json()["results"]
    (OUT_DIR / "jp_groups.json").write_text(
        json.dumps(groups, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"groups: {len(groups)}")

    all_products = []
    for i, g in enumerate(groups, 1):
        gid, gname = g["groupId"], g["name"]
        try:
            prods = s.get(f"{BASE}/{gid}/products", timeout=30).json()["results"]
            for p in prods:
                number = None
                for ext in p.get("extendedData", []):
                    if ext.get("name") == "Number":
                        number = ext.get("value")
                        break
                all_products.append({
                    "productId": p["productId"], "name": p["name"],
                    "cleanName": p.get("cleanName", p["name"]),
                    "groupId": gid, "groupName": gname,
                    "url": p.get("url", ""), "number": number,
                })
        except Exception as e:
            print(f"  [{i}/{len(groups)}] {gname}: ERROR {e}", flush=True)
        if i % 50 == 0:
            print(f"  {i}/{len(groups)} groups, {len(all_products)} products", flush=True)
        time.sleep(0.2)

    (OUT_DIR / "jp_products.json").write_text(
        json.dumps(all_products, ensure_ascii=False), encoding="utf-8")
    print(f"\nTotal JP products: {len(all_products)} -> data/tcgplayer/jp_products.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
