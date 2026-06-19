"""Whitening detection on a rectified card — the ONE flat-visible defect class that works.

Whitening = the white cardstock showing through where the colored border/corner has worn.
It is bright + desaturated (near-neutral), unlike the (saturated) border color. After
rectification the border is a known ring, so we only look there → tractable and robust.

Approach (no model, $0):
  whiteness = Value * (1 - Saturation)   # high on white/grey, low on saturated yellow/blue
  In a ring just inside the card edge, flag pixels whose whiteness exceeds a high local
  percentile (so we adapt per-card to dark vs light borders), clean up, keep edge/corner blobs.
Outputs a mask + per-edge/corner severity (whitened fraction of each region).
"""
from __future__ import annotations
import numpy as np
import cv2
from PIL import Image


def _whiteness(rgb: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV).astype(np.float32)
    S = hsv[..., 1] / 255.0
    V = hsv[..., 2] / 255.0
    return V * (1.0 - S)


def detect_whitening(warped: Image.Image, outer: dict, ring_frac: float = 0.05,
                     delta: float = 0.20, floor: float = 0.33) -> dict:
    """Detect whitening in the border ring of a rectified card.

    Whitening is RELATIVE: the border has a base whiteness (dark blue ~0.13, etc.) and wear shows
    as pixels much whiter than that local baseline. So threshold = max(floor, ring_median + delta),
    which adapts per-card to dark vs light borders (calibrated on worn cards: baselines 0.13-0.25,
    corner wear peaks 0.5-0.98).

    Args:
        warped: rectified card (with margin).
        outer: {left,top,right,bottom} card-edge rect in canvas px.
        ring_frac: ring width as a fraction of the shorter card side.
        delta: how far above the border's median whiteness counts as wear.
        floor: absolute minimum whiteness to ever count (suppresses dark-card noise).
    Returns: {"mask": HxW uint8, "regions": {...severity 0..1...}, "overall": float}
    """
    rgb = np.asarray(warped.convert("RGB"))
    Hc, Wc = rgb.shape[:2]
    ol, ot, orr, ob = int(outer["left"]), int(outer["top"]), int(outer["right"]), int(outer["bottom"])
    cw, ch = orr - ol, ob - ot
    rw = max(6, int(ring_frac * min(cw, ch)))

    white = _whiteness(rgb)
    mask = np.zeros((Hc, Wc), np.uint8)

    # Wear signal = the RIM is whiter than the border immediately BEHIND it. For each edge,
    # compare the outer rim slab to a reference slab one rim-width inward (per perpendicular
    # line). A uniform light/holo border cancels (rim≈inner); real wear pops. `floor` is an
    # absolute gate so faint variation on dark borders isn't over-counted.
    def mark_v(x_rim0, x_rim1, x_ref0, x_ref1):  # vertical edge (left/right): ref per row
        rim = white[ot:ob, x_rim0:x_rim1]
        ref = np.median(white[ot:ob, x_ref0:x_ref1], axis=1, keepdims=True)
        hit = (rim > ref + delta) & (rim > floor)
        mask[ot:ob, x_rim0:x_rim1][hit] = 255

    def mark_h(y_rim0, y_rim1, y_ref0, y_ref1):  # horizontal edge (top/bottom): ref per col
        rim = white[y_rim0:y_rim1, ol:orr]
        ref = np.median(white[y_ref0:y_ref1, ol:orr], axis=0, keepdims=True)
        hit = (rim > ref + delta) & (rim > floor)
        mask[y_rim0:y_rim1, ol:orr][hit] = 255

    mark_v(ol, ol + rw, ol + rw, ol + 2 * rw)            # left
    mark_v(orr - rw, orr, orr - 2 * rw, orr - rw)         # right
    mark_h(ot, ot + rw, ot + rw, ot + 2 * rw)             # top
    mark_h(ob - rw, ob, ob - 2 * rw, ob - rw)             # bottom

    card = np.zeros((Hc, Wc), np.uint8); card[ot:ob, ol:orr] = 1
    inner = np.zeros((Hc, Wc), np.uint8); inner[ot + rw:ob - rw, ol + rw:orr - rw] = 1
    ring = (card & (1 - inner)).astype(bool)
    if ring.sum() < 50:
        return {"mask": np.zeros((Hc, Wc), np.uint8), "regions": {}, "overall": 0.0}
    # clean: drop salt noise, keep contiguous wear
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, k, iterations=1)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k, iterations=1)
    # remove tiny blobs (< 0.02% of card area)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    min_area = max(20, int(0.0002 * cw * ch))
    out = np.zeros_like(mask)
    for i in range(1, n):
        if stats[i, cv2.CC_STAT_AREA] >= min_area:
            out[lab == i] = 255

    # per-region severity = whitened fraction of that region's ring band
    def frac(y0, y1, x0, x1):
        sub_ring = ring[y0:y1, x0:x1]
        if sub_ring.sum() == 0:
            return 0.0
        return round(float((out[y0:y1, x0:x1] > 0).sum()) / float(sub_ring.sum()), 3)

    cs = max(rw * 3, int(0.18 * min(cw, ch)))  # corner box size
    regions = {
        "edge_top": frac(ot, ot + rw, ol, orr),
        "edge_bottom": frac(ob - rw, ob, ol, orr),
        "edge_left": frac(ot, ob, ol, ol + rw),
        "edge_right": frac(ot, ob, orr - rw, orr),
        "corner_tl": frac(ot, ot + cs, ol, ol + cs),
        "corner_tr": frac(ot, ot + cs, orr - cs, orr),
        "corner_bl": frac(ob - cs, ob, ol, ol + cs),
        "corner_br": frac(ob - cs, ob, orr - cs, orr),
    }
    overall = round(float((out > 0).sum()) / max(float(ring.sum()), 1.0), 3)
    return {"mask": out, "regions": regions, "overall": overall, "ring_px": rw}


def overlay_whitening(warped: Image.Image, mask: np.ndarray, color=(255, 45, 85)) -> Image.Image:
    """Tint the whitened pixels for display."""
    rgb = np.asarray(warped.convert("RGB")).copy()
    m = mask > 0
    rgb[m] = (0.45 * rgb[m] + 0.55 * np.array(color)).astype(np.uint8)
    return Image.fromarray(rgb)
