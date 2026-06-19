"""Model-based whitening (edge/corner wear) on a rectified card — restricted to the border ring.

Uses the trained 7-class defect heatmap (models/defect_heatmap_best.pt). edge_wear (F1 0.93) and
corner_wear (0.71) were its strongest classes = exactly whitening. The full-card flood is bounded
because we only sample the BORDER ring after rectification and keep only the corner/edge channels.
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image
import torchvision.transforms as T

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

CKPT = Path("models/defect_heatmap_best.pt")
CH_CORNER, CH_EDGE = 0, 1          # channel indices in the 7-class model
_NORM = T.Compose([T.ToTensor(), T.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])])
_model = None


def _load():
    global _model
    if _model is not None:
        return _model
    import pathlib
    from train_defect_heatmap import HeatmapNet  # 7-class NC=7
    _p = pathlib.PosixPath
    pathlib.PosixPath = pathlib.WindowsPath
    try:
        ckpt = torch.load(CKPT, map_location="cpu", weights_only=False)
    finally:
        pathlib.PosixPath = _p
    m = HeatmapNet(ckpt.get("args", {}).get("backbone", "hrnet_w32"), pretrained=False)
    m.load_state_dict(ckpt["model"]); m.eval()
    _model = m
    return m


@torch.no_grad()
def detect_whitening_model(warped: Image.Image, outer: dict, tile: int = 512, stride: int = 384,
                           thr: float = 0.35, ring_frac: float = 0.07, native_w: int = 4463) -> dict:
    """The model was trained on 512px tiles cropped from ~4463px-wide native cards (a 512 tile
    ≈ 11% of card width). Our rectified canvas is ~1260px wide, so a 512 tile would cover ~40% —
    4x the wrong scale and the model fires nothing. Upscale the rectified card to ~native width
    so the tile scale matches training."""
    model = _load()
    cw0 = outer["right"] - outer["left"]
    up = max(1.0, native_w / max(cw0, 1))      # scale so card width ~= native_w
    if up > 1.0:
        warped = warped.resize((int(warped.width * up), int(warped.height * up)), Image.LANCZOS)
        outer = {k: v * up for k, v in outer.items()}
    rgb = np.asarray(warped.convert("RGB"))
    Hc, Wc = rgb.shape[:2]
    ol, ot, orr, ob = int(outer["left"]), int(outer["top"]), int(outer["right"]), int(outer["bottom"])
    cw, ch = orr - ol, ob - ot
    rw = max(8, int(ring_frac * min(cw, ch)))

    # accumulate corner/edge heatmaps at stride-4 over the whole canvas
    accH, accW = Hc // 4, Wc // 4
    acc = np.zeros((accH, accW), np.float32)
    xs = sorted(set([x for x in range(0, max(1, Wc - tile + 1), stride)] + [max(0, Wc - tile)]))
    ys = sorted(set([y for y in range(0, max(1, Hc - tile + 1), stride)] + [max(0, Hc - tile)]))
    for y0 in ys:
        for x0 in xs:
            # skip interior tiles entirely (only border tiles matter -> bounds compute & flood)
            if (x0 + tile <= ol + rw or x0 >= orr - rw) and (y0 + tile <= ot + rw or y0 >= ob - rw):
                pass  # corner-ish tiles still wanted; don't skip
            crop = warped.crop((x0, y0, x0 + tile, y0 + tile))
            x = _NORM(crop).unsqueeze(0)
            hm = torch.sigmoid(model(x).float())[0].numpy()      # (7,128,128)
            wear = np.maximum(hm[CH_CORNER], hm[CH_EDGE])         # corner OR edge wear
            ay, ax = y0 // 4, x0 // 4
            sl = acc[ay:ay + wear.shape[0], ax:ax + wear.shape[1]]
            np.maximum(sl, wear[:sl.shape[0], :sl.shape[1]], out=sl)

    # upsample acc to canvas, restrict to the border ring, threshold
    heat = np.asarray(Image.fromarray((acc * 255).astype(np.uint8)).resize((Wc, Hc))) / 255.0
    card = np.zeros((Hc, Wc), bool); card[ot:ob, ol:orr] = True
    inner = np.zeros((Hc, Wc), bool); inner[ot + rw:ob - rw, ol + rw:orr - rw] = True
    ring = card & ~inner
    mask = ((heat > thr) & ring).astype(np.uint8) * 255

    def frac(y0, y1, x0, x1):
        sr = ring[y0:y1, x0:x1]
        return 0.0 if sr.sum() == 0 else round(float((mask[y0:y1, x0:x1] > 0).sum()) / float(sr.sum()), 3)

    cs = max(rw * 2, int(0.16 * min(cw, ch)))
    regions = {
        "edge_top": frac(ot, ot + rw, ol, orr), "edge_bottom": frac(ob - rw, ob, ol, orr),
        "edge_left": frac(ot, ob, ol, ol + rw), "edge_right": frac(ot, ob, orr - rw, orr),
        "corner_tl": frac(ot, ot + cs, ol, ol + cs), "corner_tr": frac(ot, ot + cs, orr - cs, orr),
        "corner_bl": frac(ob - cs, ob, ol, ol + cs), "corner_br": frac(ob - cs, ob, orr - cs, orr),
    }
    overall = round(float((mask > 0).sum()) / max(float(ring.sum()), 1.0), 3)
    return {"mask": mask, "heat": heat, "regions": regions, "overall": overall}
