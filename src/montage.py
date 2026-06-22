"""Zone-montage builder for the Claude condition grader.

Single source of truth for the 8-zone labeled montage (4 corners + 4 edges per side)
that the grader sees. Extracted from scripts/build_grade_test.py so the /grade endpoint
and the offline test-set builder share identical image logic (golden regression stays valid).

Pure image ops — no TAG ground-truth / scoring concerns (those stay in the script).
"""
import numpy as np
import cv2
from PIL import Image, ImageFile

from src.card_detector import detect_outer_quad

ImageFile.LOAD_TRUNCATED_IMAGES = True


def card_box(img):
    """Robust card bounding box via BACKGROUND segmentation.

    TAG scans have a uniform orange/coral background; sample the 4 image corners as the
    bg color, card = pixels far from bg. Falls back to outer-quad detection if that fails.
    Returns (x0, y0, x1, y1). ⚠️ Assumes a near-uniform background — unreliable on real
    phone photos (the phone-photo gate must screen those before grading).
    """
    rgb = np.asarray(img).astype(np.float32)
    H, W = rgb.shape[:2]
    s = max(20, int(0.04 * min(W, H)))
    corners = np.concatenate([rgb[:s, :s].reshape(-1, 3), rgb[:s, -s:].reshape(-1, 3),
                              rgb[-s:, :s].reshape(-1, 3), rgb[-s:, -s:].reshape(-1, 3)])
    bg = np.median(corners, axis=0)
    dist = np.linalg.norm(rgb - bg, axis=2)
    m = (dist > 60).astype(np.uint8) * 255
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((9, 9), np.uint8))
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((25, 25), np.uint8))
    n, lab, st, _ = cv2.connectedComponentsWithStats(m, 8)
    if n <= 1:
        q = detect_outer_quad(np.asarray(img))
        W, H = img.size
        if q is None:
            return 0, 0, W, H
        xs, ys = q[:, 0], q[:, 1]
        return int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())
    i = 1 + int(np.argmax(st[1:, cv2.CC_STAT_AREA]))
    x0, y0 = st[i, cv2.CC_STAT_LEFT], st[i, cv2.CC_STAT_TOP]
    x1, y1 = x0 + st[i, cv2.CC_STAT_WIDTH], y0 + st[i, cv2.CC_STAT_HEIGHT]
    return int(x0), int(y0), int(x1), int(y1)


def _tile(a, sz, label):
    a = cv2.resize(a, (sz, sz), interpolation=cv2.INTER_AREA)
    bar = np.full((30, sz, 3), 20, np.uint8)
    cv2.putText(bar, label, (6, 21), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (255, 255, 255), 2, cv2.LINE_AA)
    return np.vstack([bar, a])


def _extract_zones(img, rim=False, box=None):
    """Cut the 8 analyzed regions (4 corners + 4 edges) from one side. Single source of the
    crop geometry — used by make_montage (grader+detector input) and zone_crops (report display),
    so the report crops are EXACTLY what the grader saw. Returns (corners, edges, sz).

    `box` = (x0,y0,x1,y1) card edges. When given (the USER-confirmed outer rect from the
    interactive centering step, on the rectified card) we use it instead of background
    segmentation (`card_box`) — precise on phone photos, where card_box breaks."""
    rgb = np.asarray(img)
    H, W = rgb.shape[:2]
    bx0, by0, bx1, by1 = box if box is not None else card_box(img)
    bw, bh = bx1 - bx0, by1 - by0
    mg = int(0.02 * min(bw, bh))                    # outward margin so the cut edge is always in frame
    bx0 = max(0, bx0 - mg); by0 = max(0, by0 - mg)
    bx1 = min(W, bx1 + mg); by1 = min(H, by1 + mg)
    bw, bh = bx1 - bx0, by1 - by0
    if rim:
        strip = max(8, int(0.05 * min(bw, bh))); cs = max(24, int(0.09 * bw)); sz = 560
    else:
        strip = max(12, int(0.09 * min(bw, bh))); cs = max(24, int(0.17 * bw)); sz = 440

    def cr(x0, y0, x1, y1):
        c = rgb[max(0, y0):y1, max(0, x0):x1]
        return c if c.size else np.zeros((10, 10, 3), np.uint8)

    corners = {"TL": cr(bx0, by0, bx0 + cs, by0 + cs), "TR": cr(bx1 - cs, by0, bx1, by0 + cs),
               "BL": cr(bx0, by1 - cs, bx0 + cs, by1), "BR": cr(bx1 - cs, by1 - cs, bx1, by1)}
    edges = {"TOP": cr(bx0, by0, bx1, by0 + strip), "BOTTOM": cr(bx0, by1 - strip, bx1, by1),
             "LEFT": cr(bx0, by0, bx0 + strip, by1), "RIGHT": cr(bx1 - strip, by0, bx1, by1)}
    return corners, edges, sz


def zone_crops(img, rim=False, box=None):
    """Return the 8 analyzed zone crops as {label: RGB np.array} for the report — the same
    corners/edges the grader sees. Edge strips are rotated to a viewable horizontal orientation."""
    corners, edges, _ = _extract_zones(img, rim=rim, box=box)
    out = dict(corners)
    for k, v in edges.items():
        out[k] = np.rot90(v) if k in ("LEFT", "RIGHT") else v
    return out


def make_montage(img, cardid, side, rim=False, box=None):
    """Build the labeled 8-zone montage (numpy RGB array) for one side of a card.

    img: PIL RGB image. side: "front"/"back". rim=True is the EXP-1 tight-crop variant
    (worse — kept only for reproducibility; production uses rim=False). box = user-confirmed
    card edges (see _extract_zones)."""
    corners, edges, sz = _extract_zones(img, rim=rim, box=box)
    crow = np.hstack([_tile(corners[k], sz, f"{k} CORNER") for k in ("TL", "TR", "BL", "BR")])

    def estrip(a, name):
        if name in ("LEFT", "RIGHT"):
            a = np.rot90(a)
        a = cv2.resize(a, (sz, sz), interpolation=cv2.INTER_AREA)
        bar = np.full((30, sz, 3), 20, np.uint8)
        cv2.putText(bar, f"{name} EDGE", (6, 21), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (255, 255, 255), 2, cv2.LINE_AA)
        return np.vstack([bar, a])

    erow = np.hstack([estrip(edges[k], k) for k in ("TOP", "BOTTOM", "LEFT", "RIGHT")])
    title = np.full((34, crow.shape[1], 3), 60, np.uint8)
    cv2.putText(title, f"{cardid}  {side.upper()}  (zones we analyze)", (8, 24),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2, cv2.LINE_AA)
    return np.vstack([title, crow, np.full((6, crow.shape[1], 3), 255, np.uint8), erow])


def save_montage(img, cardid, side, out_path, rim=False, box=None):
    """Build the montage and write it to out_path (PNG). Returns out_path."""
    Image.fromarray(make_montage(img, cardid, side, rim=rim, box=box)).save(out_path)
    return out_path
