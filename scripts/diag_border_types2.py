"""Border-type diagnostic v2 — fixes v1 contamination.

v1 bugs: (1) ring touched the rectified outer black-margin transition -> Laplacian flooded
uniformly; (2) Pokemon borders are SATURATED COLORS (yellow front / blue back), so
"matte-light vs dark" by brightness mislabels everything.

v2:
  - Ring is taken from a band that starts 1.5*rw INSIDE the card edge (skip the rectify
    margin transition) and is rw wide -> pure border-strip interior (the colored band).
  - Classify by (a) chroma/saturation, (b) micro-texture energy measured as
    local-std of V at small scale MINUS large-scale (band-pass, isolates sparkle from the
    smooth color), (c) brightness.
  - 'specular sparkle index' = fraction of band pixels that are local maxima much brighter
    than a 9px median (true specular highlights), which is what foil/holo produce and matte
    borders do not.

Types:
  foil_holo  : high sparkle_idx (specular highlights scattered through the band)
  dark       : low brightness (val_med<0.30) -> black-dirt no-contrast flood case
  matte      : everything else (the tractable colored/light matte border)
"""
import sys, csv
from pathlib import Path
from collections import Counter
import numpy as np
import cv2
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.card_detector import rectify_for_centering  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
TAG = ROOT / "data" / "tag_raw"


def border_band(outer, shape, inset_mult=1.5, width_frac=0.05):
    """A band of width rw, starting inset_mult*rw inside the card edge (avoids the
    rectify margin/edge transition)."""
    ol, ot, orr, ob = outer["left"], outer["top"], outer["right"], outer["bottom"]
    cw, ch = orr - ol, ob - ot
    rw = max(6, int(width_frac * min(cw, ch)))
    inset = int(inset_mult * rw)
    outerb = np.zeros(shape, np.uint8)
    outerb[ot + inset:ob - inset, ol + inset:orr - inset] = 1
    innerb = np.zeros(shape, np.uint8)
    innerb[ot + inset + rw:ob - inset - rw, ol + inset + rw:orr - inset - rw] = 1
    band = (outerb == 1) & (innerb == 0)
    return band, rw


def analyze_side(pil):
    rec = rectify_for_centering(pil)
    warped = np.asarray(rec["warped"].convert("RGB"))
    H, W = warped.shape[:2]
    band, rw = border_band(rec["outer"], (H, W))
    if band.sum() < 300:
        return None
    hsv = cv2.cvtColor(warped, cv2.COLOR_RGB2HSV).astype(np.float32)
    S = hsv[..., 1] / 255.0
    V = hsv[..., 2] / 255.0
    sat_med = float(np.median(S[band]))
    val_med = float(np.median(V[band]))

    Vu = (V * 255).astype(np.uint8)
    # POINT specular sparkle (foil): pixel much brighter than its 9x9 median AND tiny/scattered.
    # Real foil = many small high-contrast highlights. Diffuse glossy sheen on a blue back =
    # large smooth bright region (low high-freq), so we measure FINE-scale excess only.
    med9 = cv2.medianBlur(Vu, 9)
    fine_excess = (Vu.astype(np.int16) - med9.astype(np.int16))  # local high-freq brightness
    spec = band & (fine_excess > 35) & (V > 0.6)
    sparkle_idx = float(spec.sum()) / float(band.sum())
    # diffuse sheen vs point: coarse-scale brightness excess (15px) -> glossy laminate
    med15 = cv2.medianBlur(Vu, 15)
    coarse_bright = band & ((Vu.astype(np.int16) - cv2.medianBlur(med15, 15).astype(np.int16)) > 25) & (V > 0.55)
    sheen_idx = float(coarse_bright.sum()) / float(band.sum())
    # band-pass micro-texture
    blur_s = cv2.GaussianBlur(V, (0, 0), 1.0)
    blur_l = cv2.GaussianBlur(V, (0, 0), 6.0)
    micro = float(np.mean(np.abs(blur_s - blur_l)[band]))
    # whitening proxy: bright + desaturated, but CONTIGUOUS (open with 3x3)
    bd = (band & (V > 0.80) & (S < 0.25)).astype(np.uint8) * 255
    bd = cv2.morphologyEx(bd, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    white_frac = float((bd > 0).sum()) / float(band.sum())
    return dict(sat_med=sat_med, val_med=val_med, sparkle_idx=sparkle_idx,
                sheen_idx=sheen_idx, micro=micro, white_frac=white_frac)


def classify(st):
    # foil/holo = strong POINT sparkle (scattered fine highlights), the true false-white flood
    if st["sparkle_idx"] > 0.025:
        return "foil_holo"
    # dark = low brightness border -> black-dirt no-contrast flood case
    if st["val_med"] < 0.30:
        return "dark"
    # glossy (blue-back laminate sheen / mild holo bleed) - milder flood, still a risk
    if st["sheen_idx"] > 0.10 or st["sparkle_idx"] > 0.012:
        return "glossy"
    return "matte"


def main():
    certs = [l.strip() for l in open(ROOT / "data" / "_wseg" / "have_front.txt")][:60]
    rows = []
    for c in certs:
        for side in ("FRONT", "BACK"):
            p = TAG / c / "images" / f"{side}_MAIN.jpg"
            if not p.exists():
                continue
            try:
                st = analyze_side(Image.open(p))
                if st is None:
                    continue
                st["cert"] = c; st["side"] = side; st["type"] = classify(st)
                rows.append(st)
            except Exception as e:
                print(f"ERR {c} {side}: {e}", file=sys.stderr)
    cnt = Counter(r["type"] for r in rows)
    tot = len(rows)
    print(f"\n=== BORDER-TYPE SPLIT (n={tot} card-sides, {len(certs)} certs) ===")
    for k in ("matte", "dark", "foil_holo"):
        print(f"  {k:10s}: {cnt.get(k,0):3d}  ({100*cnt.get(k,0)/tot:.1f}%)")
    print("\n=== by FRONT/BACK ===")
    for side in ("FRONT", "BACK"):
        sc = Counter(r["type"] for r in rows if r["side"] == side)
        st_tot = sum(sc.values())
        print(f"  {side}: " + ", ".join(f"{k}={sc.get(k,0)}({100*sc.get(k,0)/st_tot:.0f}%)" for k in ("matte","dark","foil_holo")))
    print("\n=== sparkle_idx (specular highlight fraction) by type ===")
    for k in ("matte", "dark", "foil_holo"):
        v = [r["sparkle_idx"] for r in rows if r["type"] == k]
        if v:
            print(f"  {k:10s}: med={np.median(v):.4f} p90={np.percentile(v,90):.4f} max={np.max(v):.4f}")
    print("\n=== white_frac (whitening-proxy false positives) by type ===")
    for k in ("matte", "dark", "foil_holo"):
        v = [r["white_frac"] for r in rows if r["type"] == k]
        if v:
            print(f"  {k:10s}: med={np.median(v):.4f} p90={np.percentile(v,90):.4f} max={np.max(v):.4f}")
    out = ROOT / "data" / "_wseg" / "border_type_diag2.csv"
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["cert","side","type","sat_med","val_med","sparkle_idx","micro","white_frac"])
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
