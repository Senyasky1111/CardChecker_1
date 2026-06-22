import sys, os, json
from pathlib import Path
import numpy as np, cv2
from PIL import Image, ImageFile
ImageFile.LOAD_TRUNCATED_IMAGES = True
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
for ln in Path(".env").read_text().splitlines():
    if ln.strip() and not ln.startswith("#") and "=" in ln:
        k, v = ln.split("=", 1); os.environ.setdefault(k.strip(), v.strip())
from src.claude_grade import ClaudeGrader, _card_box, prep_full_card
R = Path("runs/realcard")

def tile(a, sz, label):
    a = cv2.resize(a, (sz, sz), interpolation=cv2.INTER_AREA)
    bar = np.full((30, sz, 3), 20, np.uint8)
    cv2.putText(bar, label, (6, 21), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2, cv2.LINE_AA)
    return np.vstack([bar, a])

def montage(name):
    img = Image.open(R / f"{name}.png").convert("RGB"); rgb = np.asarray(img); H, W = rgb.shape[:2]
    bx0, by0, bx1, by1 = _card_box(img); bw, bh = bx1 - bx0, by1 - by0
    strip = max(10, int(0.09 * min(bw, bh))); cs = max(24, int(0.17 * bw)); sz = 440
    def cr(x0, y0, x1, y1):
        c = rgb[max(0, y0):y1, max(0, x0):x1]; return c if c.size else np.zeros((10, 10, 3), np.uint8)
    cor = {"TL": cr(bx0, by0, bx0 + cs, by0 + cs), "TR": cr(bx1 - cs, by0, bx1, by0 + cs),
           "BL": cr(bx0, by1 - cs, bx0 + cs, by1), "BR": cr(bx1 - cs, by1 - cs, bx1, by1)}
    edg = {"TOP": cr(bx0, by0, bx1, by0 + strip), "BOTTOM": cr(bx0, by1 - strip, bx1, by1),
           "LEFT": cr(bx0, by0, bx0 + strip, by1), "RIGHT": cr(bx1 - strip, by0, bx1, by1)}
    crow = np.hstack([tile(cor[k], sz, f"{k} CORNER") for k in ("TL", "TR", "BL", "BR")])
    def es(a, nm):
        if nm in ("LEFT", "RIGHT"): a = np.rot90(a)
        a = cv2.resize(a, (sz, sz), interpolation=cv2.INTER_AREA); bar = np.full((30, sz, 3), 20, np.uint8)
        cv2.putText(bar, f"{nm} EDGE", (6, 21), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2, cv2.LINE_AA)
        return np.vstack([bar, a])
    erow = np.hstack([es(edg[k], k) for k in ("TOP", "BOTTOM", "LEFT", "RIGHT")])
    mp = R / f"{name}_montage.png"
    Image.fromarray(np.vstack([crow, np.full((6, crow.shape[1], 3), 255, np.uint8), erow])).save(mp)
    return str(mp)

fm = montage("front"); bm = montage("back")
ff = prep_full_card(str(R / "front.png"), str(R / "front_full.png"))
bf = prep_full_card(str(R / "back.png"), str(R / "back_full.png"))
g = ClaudeGrader(thinking=True)
det = g.detect_zones(fm, bm, front_full=ff, back_full=bf)
hol = g.grade_montages(fm, bm, front_full=ff, back_full=bf)
json.dump({"detector": det, "holistic": hol}, open(R / "result.json", "w"), indent=2)
def clip(x): return max(1.0, min(10.0, x))
print("=" * 60); print("DETECTOR (per-zone severity):"); print("=" * 60)
for side in ("front", "back"):
    z = det.get(side) or {}
    print(f"  {side.upper()}: " + "  ".join(f"{k}={v}" for k, v in z.items()))
    mh = [k for k, v in z.items() if v in ("MODERATE", "HEAVY")]
    print(f"    -> MODERATE+: {mh or 'none'}")
print("=" * 60); print("HOLISTIC GRADER  (user says TRUE grade = 9, ~no whitening):"); print("=" * 60)
print(f"  overall raw={hol['overall_grade']} -> calibrated={round(clip(1.58*hol['overall_grade']-4.88),1)}")
b = hol.get("back")
print(f"  front={hol['front']['grade']}  back={b['grade'] if b else '-'}")
if b:
    print(f"  back pillars: cent={b['centering']} corners={b['corners']} edges={b['edges']} surf={b['surface']}  worn={b['worn_zones']}")
dist = hol.get("grade_distribution") or []
print("  dist:", " ".join(f"{x['grade']}:{x['prob']}" for x in dist))
print("  explanation:", hol["explanation"][:240])
