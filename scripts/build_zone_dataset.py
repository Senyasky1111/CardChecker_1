"""Build a zone-crop dataset for binary whitening/wear classification.

8 square zones per side (4 corners + 4 edge-midpoints), cropped sharp from native TAG images.
  POSITIVE (label 1): a zone that TAG marked with corner/edge wear (placeholder-filtered).
  NEGATIVE (label 0): every zone of a GEM-MINT card (grade>=9.5, no defects) — trustworthy clean.
We deliberately SKIP unlabeled zones on worn cards (TAG labels are capped -> ambiguous), exactly
like EXP-1's trustworthy-negatives lesson. Split by cert hash (no leakage).

Output: data/zone_tiles/{train,val,test}/{0,1}/<cert>_<side>_<zone>.jpg  + manifest.jsonl

Usage:
  python scripts/build_zone_dataset.py --sample 60 --out data/_zone_dryrun
  python scripts/build_zone_dataset.py --max-pos 20000 --max-neg 20000 --out data/zone_tiles
"""
from __future__ import annotations
import argparse, glob, json, os, sys
from pathlib import Path
import numpy as np
from PIL import Image, ImageFile
ImageFile.LOAD_TRUNCATED_IMAGES = True
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.card_detector import detect_outer_quad   # noqa

NOM_W, NOM_H = 4463, 6161
ZONES = ["tl", "tr", "bl", "br", "top", "bottom", "left", "right"]


def is_ph(x, y, r=25):
    return (abs(x - 50) <= r and abs(y - 50) <= r) or (abs(x) <= r and abs(y) <= r)


def zone_of(nx, ny, t):
    t = t.lower()
    if "corner" in t:
        return ("t" if ny < 0.5 else "b") + ("l" if nx < 0.5 else "r")
    if "edge" in t:
        d = {"left": nx, "right": 1 - nx, "top": ny, "bottom": 1 - ny}
        return min(d, key=d.get)
    return None


def split_for(cert):
    h = sum(ord(c) for c in cert) % 10
    return "train" if h < 8 else ("val" if h == 8 else "test")


def bbox_of(img):
    q = detect_outer_quad(np.asarray(img))
    if q is None:
        W, H = img.size
        return 0, 0, W, H
    xs, ys = q[:, 0], q[:, 1]
    return int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())


def zone_windows(bx0, by0, bx1, by1):
    bw, bh = bx1 - bx0, by1 - by0
    cs = int(0.18 * bw)                 # square window side
    mx, my = (bx0 + bx1) // 2, (by0 + by1) // 2
    half = cs // 2
    centers = {
        "tl": (bx0 + half, by0 + half), "tr": (bx1 - half, by0 + half),
        "bl": (bx0 + half, by1 - half), "br": (bx1 - half, by1 - half),
        "top": (mx, by0 + half), "bottom": (mx, by1 - half),
        "left": (bx0 + half, my), "right": (bx1 - half, my),
    }
    return {z: (cx - half, cy - half, cx + half, cy + half) for z, (cx, cy) in centers.items()}, cs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("data/zone_tiles"))
    ap.add_argument("--size", type=int, default=224)
    ap.add_argument("--max-pos", type=int, default=20000)
    ap.add_argument("--max-neg", type=int, default=20000)
    ap.add_argument("--sample", type=int, default=None)
    args = ap.parse_args()
    for sp in ("train", "val", "test"):
        for lb in ("0", "1"):
            (args.out / sp / lb).mkdir(parents=True, exist_ok=True)
    man = open(args.out / "manifest.jsonl", "w")
    n_pos = n_neg = 0
    paths = glob.glob("data/tag_raw/*/metadata.json")

    def save(img, win, sp, lb, name):
        x0, y0, x1, y1 = win
        crop = img.crop((max(0, x0), max(0, y0), x1, y1)).resize((args.size, args.size), Image.LANCZOS)
        crop.save(args.out / sp / lb / f"{name}.jpg", quality=88)

    for p in paths:
        if n_pos >= args.max_pos and n_neg >= args.max_neg:
            break
        if args.sample and (n_pos + n_neg) >= args.sample:
            break
        try:
            meta = json.loads(Path(p).read_text(encoding="utf-8"))
        except Exception:
            continue
        cert = os.path.basename(os.path.dirname(p))
        sp = split_for(cert)
        grade = meta.get("grade")
        defects = meta.get("surface_defects") or []
        for side in ("front", "back"):
            ip = f"data/tag_raw/{cert}/images/{side.upper()}_MAIN.jpg"
            if not os.path.exists(ip):
                continue
            sd = [d for d in defects if d.get("side", "front") == side and not is_ph(d.get("x", 0), d.get("y", 0))
                  and ("corner" in (d.get("defect_type", "").lower()) or "edge" in (d.get("defect_type", "").lower()))]
            worn = set()
            for d in sd:
                z = zone_of(d["x"] / NOM_W, d["y"] / NOM_H, d.get("defect_type", ""))
                if z:
                    worn.add(z)
            gem = (grade is not None and grade >= 9.5 and len(sd) == 0)
            if not worn and not gem:
                continue                                   # ambiguous -> skip
            try:
                img = Image.open(ip).convert("RGB")
            except Exception:
                continue
            wins, cs = zone_windows(*bbox_of(img))
            if gem and n_neg < args.max_neg:
                for z in ZONES:
                    save(img, wins[z], sp, "0", f"{cert}_{side}_{z}")
                    man.write(json.dumps({"cert": cert, "side": side, "zone": z, "label": 0, "split": sp}) + "\n")
                    n_neg += 1
            elif worn and n_pos < args.max_pos:
                for z in worn:
                    save(img, wins[z], sp, "1", f"{cert}_{side}_{z}")
                    man.write(json.dumps({"cert": cert, "side": side, "zone": z, "label": 1, "split": sp}) + "\n")
                    n_pos += 1
    man.close()
    print(f"positives(worn)={n_pos}  negatives(clean)={n_neg}  -> {args.out}")


if __name__ == "__main__":
    main()
