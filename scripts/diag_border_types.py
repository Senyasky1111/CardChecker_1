"""Robustness diagnostic: quantify how common each BORDER TYPE is on real TAG cards,
and measure the two flood signals (foil sparkle, dark-low-contrast) directly.

For each sampled card (FRONT + BACK), rectify with the SAME function the product uses
(rectify_for_centering), extract the outer border ring (the colored band we cut for
centering), and compute per-side stats:

  - sat_med        : median HSV saturation of the ring (0..1). Low+bright = matte-light;
                     low+dark = matte-dark/black; mid/high = colored or holo.
  - val_med        : median Value/brightness (0..1).
  - spec_frac      : fraction of ring pixels that are BOTH bright (V>0.85) AND desaturated
                     (S<0.20) -> "white-ish". On matte borders this ~ real whitening + tiny.
                     On FOIL/HOLO this EXPLODES (sparkle reads as white) -> the false-white flood.
  - hi_freq_energy : high-frequency texture energy in the ring (Laplacian std on V).
                     Foil/holo has high micro-contrast sparkle even where color is uniform.
  - spec_cluster   : are the bright-desat pixels spatially CLUSTERED (real wear, contiguous)
                     or SCATTERED (sparkle)? measured as (n_components / n_bright_px).
                     Scattered (high ratio) => sparkle; clustered (low) => wear.

Border-type rule (heuristic, to REPORT the split, not the final model):
  foil_holo : hi_freq_energy high AND spec pixels scattered (many tiny components)
  matte_dark: val_med low (dark border) -> black-dirt flood risk (no contrast)
  matte_light: otherwise (tractable case the naive detector handles)

Outputs a table + aggregate split. Opens 2 images/card max (FRONT_MAIN, BACK_MAIN).
"""
import sys, json, csv
from pathlib import Path
import numpy as np
import cv2
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.card_detector import rectify_for_centering  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
TAG = ROOT / "data" / "tag_raw"


def ring_mask(outer, shape, frac=0.05):
    ol, ot, orr, ob = outer["left"], outer["top"], outer["right"], outer["bottom"]
    cw, ch = orr - ol, ob - ot
    rw = max(6, int(frac * min(cw, ch)))
    card = np.zeros(shape, np.uint8); card[ot:ob, ol:orr] = 1
    inner = np.zeros(shape, np.uint8); inner[ot + rw:ob - rw, ol + rw:orr - rw] = 1
    return ((card == 1) & (inner == 0)), rw


def analyze_side(pil):
    rec = rectify_for_centering(pil)
    warped = np.asarray(rec["warped"].convert("RGB"))
    H, W = warped.shape[:2]
    ring, rw = ring_mask(rec["outer"], (H, W))
    if ring.sum() < 200:
        return None
    hsv = cv2.cvtColor(warped, cv2.COLOR_RGB2HSV).astype(np.float32)
    S = hsv[..., 1] / 255.0
    V = hsv[..., 2] / 255.0
    rs, rv = S[ring], V[ring]
    sat_med = float(np.median(rs))
    val_med = float(np.median(rv))
    # white-ish (whitening OR sparkle) pixels in ring
    bright_desat = ring & (V > 0.85) & (S < 0.20)
    spec_frac = float(bright_desat.sum()) / float(ring.sum())
    # high-frequency texture energy on V within the ring (foil sparkle)
    lap = cv2.Laplacian((V * 255).astype(np.uint8), cv2.CV_32F, ksize=3)
    hi_freq = float(np.std(lap[ring]))
    # spatial clustering of the bright-desat pixels: scattered sparkle vs contiguous wear
    bm = (bright_desat.astype(np.uint8)) * 255
    n_comp, _, stats, _ = cv2.connectedComponentsWithStats(bm, 8)
    n_bright = int(bright_desat.sum())
    # fraction of bright px in components smaller than ~ (rw/2)^2 i.e. tiny specks
    tiny_thr = max(4, (rw // 2) ** 2)
    tiny_px = sum(stats[i, cv2.CC_STAT_AREA] for i in range(1, n_comp)
                  if stats[i, cv2.CC_STAT_AREA] < tiny_thr)
    scatter = float(tiny_px) / float(n_bright) if n_bright > 0 else 0.0
    return dict(sat_med=sat_med, val_med=val_med, spec_frac=spec_frac,
                hi_freq=hi_freq, scatter=scatter, n_bright=n_bright)


def classify(st):
    # thresholds calibrated below from observed distribution; report-level heuristic
    if st["val_med"] < 0.32:
        base = "matte_dark"
    else:
        base = "matte_light"
    # foil/holo overrides: strong micro-texture + scattered bright specks
    if st["hi_freq"] > 22 and st["spec_frac"] > 0.04 and st["scatter"] > 0.45:
        return "foil_holo"
    if st["hi_freq"] > 30 and st["scatter"] > 0.55:
        return "foil_holo"
    return base


def main():
    certs = [l.strip() for l in open(ROOT / "data" / "_wseg" / "have_front.txt")][:60]
    rows = []
    for c in certs:
        for side in ("FRONT", "BACK"):
            p = TAG / c / "images" / f"{side}_MAIN.jpg"
            if not p.exists():
                continue
            try:
                pil = Image.open(p)
                st = analyze_side(pil)
                if st is None:
                    continue
                st["cert"] = c; st["side"] = side
                st["type"] = classify(st)
                rows.append(st)
            except Exception as e:
                print(f"ERR {c} {side}: {e}", file=sys.stderr)
    # aggregate
    from collections import Counter
    cnt = Counter(r["type"] for r in rows)
    tot = len(rows)
    print(f"\n=== BORDER-TYPE SPLIT (n={tot} card-sides, {len(certs)} certs sampled) ===")
    for k in ("matte_light", "matte_dark", "foil_holo"):
        print(f"  {k:12s}: {cnt.get(k,0):3d}  ({100*cnt.get(k,0)/tot:.1f}%)")
    # spec_frac (false-white flood proxy) by type
    print("\n=== spec_frac (bright-desat ring fraction = whitening+sparkle) by type ===")
    for k in ("matte_light", "matte_dark", "foil_holo"):
        vals = [r["spec_frac"] for r in rows if r["type"] == k]
        if vals:
            print(f"  {k:12s}: median={np.median(vals):.3f}  p90={np.percentile(vals,90):.3f}  max={np.max(vals):.3f}")
    print("\n=== hi_freq (micro-texture/sparkle) by type ===")
    for k in ("matte_light", "matte_dark", "foil_holo"):
        vals = [r["hi_freq"] for r in rows if r["type"] == k]
        if vals:
            print(f"  {k:12s}: median={np.median(vals):.1f}  p90={np.percentile(vals,90):.1f}")
    print("\n=== val_med (border brightness) overall ===")
    vv = [r["val_med"] for r in rows]
    print(f"  median={np.median(vv):.2f}  frac<0.32(dark)={np.mean([v<0.32 for v in vv]):.2f}")
    # dump csv
    out = ROOT / "data" / "_wseg" / "border_type_diag.csv"
    out.parent.mkdir(exist_ok=True)
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["cert","side","type","sat_med","val_med","spec_frac","hi_freq","scatter","n_bright"])
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
