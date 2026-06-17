"""Prep for the 'Claude-as-grader' test: export N TAG cards as ~1280px phone-style photos
and stash ground truth SEPARATELY (so the model predicts blind, then we score).

Outputs:
  runs/defect_full/llm_eval/claude_test/card_NN.jpg   (what Claude looks at)
  runs/defect_full/llm_eval/claude_test/_gt.json      (ground truth — DO NOT read until scored)
"""
from __future__ import annotations
import json, glob, os, random, re
from PIL import Image

NOM_W, NOM_H = 4463, 6161
OUT = "runs/defect_full/llm_eval/claude_test"


def is_placeholder(x, y, r=25):
    return (abs(x - 50) <= r and abs(y - 50) <= r) or (abs(x) <= r and abs(y) <= r)


def parse_ratio(s):
    if not s or "/" not in str(s):
        return None
    try:
        a, b = str(s).split("/")
        a = float(re.sub(r"[^0-9.]", "", a)); b = float(re.sub(r"[^0-9.]", "", b))
        if 90 <= a + b <= 110:
            return [round(a, 1), round(b, 1)]
    except Exception:
        return None
    return None


def front_defects(meta):
    return [[d["x"], d["y"], d.get("defect_type", "?")]
            for d in (meta.get("surface_defects") or [])
            if d.get("side", "front") == "front" and not is_placeholder(d.get("x", 0), d.get("y", 0))]


def main():
    os.makedirs(OUT, exist_ok=True)
    paths = glob.glob("data/tag_raw/*/metadata.json")
    random.Random(20).shuffle(paths)
    damaged, clean = [], []
    for p in paths:
        if len(damaged) >= 5 and len(clean) >= 3:
            break
        cert = os.path.basename(os.path.dirname(p))
        ip = f"data/tag_raw/{cert}/images/FRONT_MAIN.jpg"
        if not os.path.exists(ip):
            continue
        try:
            meta = json.load(open(p, encoding="utf-8"))
        except Exception:
            continue
        if parse_ratio(meta.get("centering_front_lr")) is None:
            continue
        fd = front_defects(meta)
        g = meta.get("grade") or 0
        if len(fd) >= 5 and len(damaged) < 5:
            damaged.append((cert, meta, fd, ip))
        elif g >= 9.5 and len(fd) == 0 and len(clean) < 3:
            clean.append((cert, meta, fd, ip))

    cards = damaged + clean
    random.Random(99).shuffle(cards)  # mix so I can't tell damaged vs clean by order
    gt = {}
    for i, (cert, meta, fd, ip) in enumerate(cards, 1):
        img = Image.open(ip).convert("RGB")
        img.thumbnail((1280, 1280))
        name = f"card_{i:02d}.jpg"
        img.save(f"{OUT}/{name}", quality=92)
        gt[name] = {
            "cert": cert,
            "grade": meta.get("grade"),
            "centering_lr": parse_ratio(meta.get("centering_front_lr")),
            "centering_tb": parse_ratio(meta.get("centering_front_tb")),
            "defects_norm": [[round(x / NOM_W, 3), round(y / NOM_H, 3), t] for x, y, t in fd],
        }
    json.dump(gt, open(f"{OUT}/_gt.json", "w"), indent=2)
    print(f"exported {len(cards)} cards to {OUT}/ (card_01..card_{len(cards):02d}.jpg)")
    print("GT stashed in _gt.json (do not read until predictions are recorded)")


if __name__ == "__main__":
    main()
