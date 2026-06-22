"""
Classical-CV white/black dot segmentation prototype for border strips + corners.

Thesis under test: border/corner *wear* (color worn to white cardstock = white specks;
ink/dirt = black specks) is ELEMENTARY blob segmentation on the rectified border, NOT
the failed point-supervised heatmap.

Pipeline per card:
  1. detect_outer_quad -> rectify card to a native-ish resolution canvas.
  2. Sample a thin rim (~RIM_FRAC of card width) all the way around + 4 corner squares.
  3. Kill halftone with median blur. On each strip, model the LOCAL baseline (median of the
     strip in whiteness and darkness channels) and segment blobs that deviate.
        whiteness = V*(1-S)   (bright + desaturated -> bare cardstock)
        darkness  = 255 - V    (dark specks: ink/dirt/scuff)
  4. Methods compared: top-hat/bottom-hat morphology, local-adaptive threshold, MSER.
  5. Score detected blobs against TAG CORNER/EDGE WEAR points (mapped into the rectified frame).

Run: ./venv/Scripts/python.exe scripts/seg_dot_prototype.py
"""
import json, os, sys, glob
import numpy as np
import cv2
from PIL import Image

sys.path.insert(0, os.path.abspath("."))
from src.card_detector import detect_outer_quad, order_corners

ROOT = "data/tag_raw"
OUT = "data/_seg_demo"
os.makedirs(OUT, exist_ok=True)

# rectified canvas — keep it high so a thin rim still has real pixels.
# native ~4442x6163; we rectify to half that to bound memory but keep detail.
RW, RH = 2200, 3050
RIM_FRAC = 0.03          # thin rim = 3% of card width
CORNER_FRAC = 0.06       # corner square = 6% of card width
HIT_TOL_FRAC = 0.04      # a TAG point counts as "hit" if a blob center is within 4% of card width


def load_quad_and_warp(cert, side="front"):
    fn = os.path.join(ROOT, cert, "images", f"{side.upper()}_MAIN.jpg")
    if not os.path.exists(fn):
        return None, None, None
    img = np.array(Image.open(fn).convert("RGB"))
    H0, W0 = img.shape[:2]
    quad = detect_outer_quad(img)
    if quad is None:
        quad = np.array([[0, 0], [W0, 0], [W0, H0], [0, H0]], np.float32)
        method = "full_frame"
    else:
        method = "bg_quad"
    ordered = order_corners(quad.astype(np.float32))
    # force portrait
    if np.linalg.norm(ordered[1]-ordered[0]) > np.linalg.norm(ordered[3]-ordered[0])*1.1:
        ordered = np.roll(ordered, -1, axis=0)
    dst = np.array([[0,0],[RW,0],[RW,RH],[0,RH]], np.float32)
    M = cv2.getPerspectiveTransform(ordered, dst)
    warped = cv2.warpPerspective(img, M, (RW, RH), flags=cv2.INTER_AREA)
    return warped, M, method


def map_points(pts_xy, M):
    """Map original-image (x,y) TAG points into the rectified canvas via M."""
    if not pts_xy:
        return np.zeros((0, 2))
    a = np.array(pts_xy, np.float32).reshape(-1, 1, 2)
    out = cv2.perspectiveTransform(a, M).reshape(-1, 2)
    return out


def rim_mask(rw, rh, rim_px):
    m = np.zeros((rh, rw), np.uint8)
    m[:] = 255
    m[rim_px:rh-rim_px, rim_px:rw-rim_px] = 0
    return m  # 255 on the rim band


def segment_dots(warped, rim_px):
    """Return white-blob list and black-blob list of (x,y,area) on the rim band.
    Uses top-hat / bottom-hat on the whiteness & darkness channels, baseline = rim median.
    """
    rgb = warped
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV).astype(np.float32)
    V = hsv[..., 2]; S = hsv[..., 1] / 255.0
    whiteness = (V * (1.0 - S)).astype(np.uint8)
    darkness = (255 - V).astype(np.uint8)

    # halftone kill: median blur (kills the regular dot screen) then keep
    wh = cv2.medianBlur(whiteness, 5)
    dk = cv2.medianBlur(darkness, 5)

    mask = rim_mask(warped.shape[1], warped.shape[0], rim_px)

    # structuring element ~ a "speck" bigger than halftone but smaller than the whole strip
    spk = max(7, rim_px // 4) | 1
    se = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (spk, spk))
    tophat = cv2.morphologyEx(wh, cv2.MORPH_TOPHAT, se)      # bright blobs vs local bg
    bothat = cv2.morphologyEx(dk, cv2.MORPH_TOPHAT, se)      # dark blobs (darkness is inverted V)

    blobs = {}
    for name, resp in (("white", tophat), ("black", bothat)):
        r = cv2.bitwise_and(resp, resp, mask=mask)
        vals = r[mask > 0]
        if vals.size == 0:
            blobs[name] = []
            continue
        # adaptive threshold relative to the rim's own response distribution
        thr = max(18, int(np.percentile(vals, 99.0)))
        bw = (r >= thr).astype(np.uint8) * 255
        bw = cv2.morphologyEx(bw, cv2.MORPH_OPEN,
                              cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)))
        n, lab, stats, cent = cv2.connectedComponentsWithStats(bw, 8)
        out = []
        amin = (spk * spk) * 0.4
        amax = (rim_px * rim_px) * 4
        for i in range(1, n):
            area = stats[i, cv2.CC_STAT_AREA]
            if amin <= area <= amax:
                cx, cy = cent[i]
                out.append((float(cx), float(cy), int(area)))
        blobs[name] = out
    return blobs, whiteness, darkness


def near_border(x, y, rw, rh, rim_px):
    band = rim_px * 1.8
    return (x < band or x > rw - band or y < band or y > rh - band)


def main():
    # curated set: vintage yellow border + holo + edge/corner wear + gem mint controls
    test = [
        ("C1192440", "vintage/charizard-yellow border (POOR grade 1)"),
        ("C1502312", "holo"),
        ("C1006930", "edge+corner wear g4"),
        ("C1083775", "edge wear g5"),
        ("C1101933", "edge wear g5.5"),
        ("C1029857", "corner wear g3.5"),
        ("C1045794", "corner wear g7"),
        ("C1002649", "GEM MINT 9.5+ control"),
        ("C1009540", "GEM MINT 9.5+ control"),
        ("C1017697", "GEM MINT 9.5+ control"),
    ]
    rows = []
    for cert, desc in test:
        mp = os.path.join(ROOT, cert, "metadata.json")
        if not os.path.exists(mp):
            rows.append((cert, desc, "NO METADATA", 0, 0, 0, 0, 0))
            continue
        m = json.load(open(mp))
        grade = m.get("grade")
        warped, M, method = load_quad_and_warp(cert, "front")
        if warped is None:
            rows.append((cert, desc, "NO IMAGE", 0, 0, 0, 0, 0))
            continue
        rim_px = int(RIM_FRAC * RW)
        blobs, whiteness, darkness = segment_dots(warped, rim_px)

        # TAG front points that are border/corner wear, drop near-origin placeholders
        tag = [d for d in (m.get("surface_defects") or [])
               if d.get("side") == "front"
               and ("WEAR" in d.get("defect_type", "").upper())
               and not (d.get("x", 0) < 120 and d.get("y", 0) < 120)]
        tag_xy = map_points([(d["x"], d["y"]) for d in tag], M)

        all_blobs = [(*b, "white") for b in blobs["white"]] + [(*b, "black") for b in blobs["black"]]
        # restrict to ones genuinely on the rim band (defensive)
        all_blobs = [b for b in all_blobs if near_border(b[0], b[1], RW, RH, rim_px)]

        tol = HIT_TOL_FRAC * RW
        hits = 0
        for (tx, ty) in tag_xy:
            if not near_border(tx, ty, RW, RH, rim_px):
                continue  # TAG point isn't on border -> not this detector's job
            d = min([np.hypot(bx-tx, by-ty) for (bx, by, *_ ) in all_blobs], default=1e9)
            if d <= tol:
                hits += 1
        tag_border = sum(1 for (tx, ty) in tag_xy if near_border(tx, ty, RW, RH, rim_px))

        # overlay
        ov = warped.copy()
        for (bx, by, area, col) in all_blobs:
            c = (0, 255, 0) if col == "white" else (255, 0, 255)
            cv2.circle(ov, (int(bx), int(by)), 14, c, 3)
        for (tx, ty) in tag_xy:
            cv2.drawMarker(ov, (int(tx), int(ty)), (255, 255, 0),
                           cv2.MARKER_CROSS, 40, 4)
        cv2.rectangle(ov, (rim_px, rim_px), (RW-rim_px, RH-rim_px), (60, 60, 60), 2)
        op = os.path.join(OUT, f"{cert}_front_overlay.jpg")
        Image.fromarray(ov).resize((RW//2, RH//2)).save(op, quality=85)

        nb = len(all_blobs)
        rows.append((cert, desc, f"g{grade}/{method}", len(tag_xy), tag_border,
                     len(blobs["white"]), len(blobs["black"]), hits, op))

    print("\n=== SEGMENTATION PROTOTYPE RESULTS (front) ===")
    print(f"{'cert':9} {'grade/meth':16} {'TAGpts':6} {'border':6} {'white':5} {'black':5} {'hits':4}  desc")
    for r in rows:
        if len(r) < 9:
            print(r); continue
        cert, desc, gm, ntag, nb_tag, nw, nbk, hits, op = r
        print(f"{cert:9} {gm:16} {ntag:6} {nb_tag:6} {nw:5} {nbk:5} {hits:4}  {desc}")
    print("\noverlays in", OUT)


if __name__ == "__main__":
    main()
