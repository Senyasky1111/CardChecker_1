"""Hypothesis test: how well can a multimodal LLM (Gemini) do defect localization +
centering from a single card photo — and what does it cost per call (pay-per-use MVP)?

Scored against TAG ground truth:
  * centering: MAE of predicted left% / top% vs TAG ratios (the clean, exact GT).
  * defects:   recall vs TAG points (placeholder-filtered) at tolerance; and false
               positives per CLEAN card (grade-10, 0 defects).
  * cost:      input/output tokens per card -> $/card at Gemini Flash/Pro pricing.

Usage:
  ./venv/Scripts/python.exe scripts/llm_defect_centering_eval.py --model gemini-2.5-flash --n-def 12 --n-clean 8
"""
from __future__ import annotations
import argparse, io, json, glob, os, random, re, time
import numpy as np
from PIL import Image

os.environ.setdefault("GEMINI_API_KEY",
    [l.split('"')[1] for l in open("scripts/run_gemini_test.py") if "AIza" in l][0])
from google import genai
from google.genai import types

NOM_W, NOM_H = 4463, 6161
OUT = "runs/defect_full/llm_eval"
# Gemini pricing ($ per 1M tokens), approx mid-2026 public rates
PRICE = {"gemini-2.5-flash": (0.30, 2.50), "gemini-2.5-pro": (1.25, 10.0)}

PROMPT = """You are inspecting a Pokemon trading card photo for professional grading.
Return STRICT JSON only (no prose, no markdown), with this exact shape:
{
  "centering": {"left_pct": <number>, "right_pct": <number>, "top_pct": <number>, "bottom_pct": <number>},
  "defects": [{"x": <0..1>, "y": <0..1>, "type": "<corner_wear|edge_wear|scratch|dent|crease|surface|stain>", "confidence": <0..1>}]
}
centering = width of the border/margin around the inner printed frame, as percentages:
left_pct+right_pct=100, top_pct+bottom_pct=100. A perfectly centered card is 50/50.
defects = every VISIBLE flaw (whitening, scratches, dents, creases, edge/corner wear,
print lines, stains). x,y = location normalized to image width/height, (0,0)=top-left.
Only report defects you can actually see. Do NOT invent defects on a clean card."""


def is_placeholder(x, y, r=25):
    return (abs(x - 50) <= r and abs(y - 50) <= r) or (abs(x) <= r and abs(y) <= r)


def parse_ratio(s):
    """'45.43/54.57' or '48L/52R' or '46T/54B' -> (first, second) floats, or None."""
    if not s or "/" not in str(s):
        return None
    try:
        a, b = str(s).split("/")
        a = float(re.sub(r"[^0-9.]", "", a)); b = float(re.sub(r"[^0-9.]", "", b))
        if 90 <= a + b <= 110:
            return a, b
    except Exception:
        return None
    return None


def front_defects(meta):
    return [(d["x"], d["y"]) for d in (meta.get("surface_defects") or [])
            if d.get("side", "front") == "front" and not is_placeholder(d.get("x", 0), d.get("y", 0))]


def pick_cards(n_def, n_clean):
    paths = glob.glob("data/tag_raw/*/metadata.json")
    random.Random(7).shuffle(paths)
    defected, clean = [], []
    for p in paths:
        if len(defected) >= n_def and len(clean) >= n_clean:
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
        if len(fd) >= 5 and len(defected) < n_def:
            defected.append((cert, meta, fd))
        elif g >= 9.5 and len(fd) == 0 and len(clean) < n_clean:
            clean.append((cert, meta, fd))
    return defected, clean


def ask_gemini(client, model, ip):
    img = Image.open(ip).convert("RGB")
    img.thumbnail((1280, 1280))  # phone-photo scale, keeps cost low
    buf = io.BytesIO(); img.save(buf, format="JPEG", quality=90)
    resp = client.models.generate_content(
        model=model,
        contents=[types.Part.from_bytes(data=buf.getvalue(), mime_type="image/jpeg"), PROMPT],
        config=types.GenerateContentConfig(temperature=0.0, response_mime_type="application/json"),
    )
    um = resp.usage_metadata
    tok = (getattr(um, "prompt_token_count", 0) or 0, getattr(um, "candidates_token_count", 0) or 0)
    try:
        data = json.loads(resp.text)
    except Exception:
        data = {"centering": {}, "defects": [], "_raw": resp.text[:200]}
    return data, tok


def score_centering(pred, meta):
    glr = parse_ratio(meta.get("centering_front_lr"))
    gtb = parse_ratio(meta.get("centering_front_tb"))
    c = pred.get("centering") or {}
    errs = []
    if glr and c.get("left_pct") is not None:
        errs.append(("lr", abs(float(c["left_pct"]) - glr[0])))
    if gtb and c.get("top_pct") is not None:
        errs.append(("tb", abs(float(c["top_pct"]) - gtb[0])))
    return errs


def score_defects(pred, gt_pts, tol_norm=0.05):
    preds = pred.get("defects") or []
    # recall: GT point detected if any predicted defect within tol (normalized)
    hits = 0
    pred_xy = [(float(d.get("x", -9)), float(d.get("y", -9))) for d in preds if "x" in d]
    for (gx, gy) in gt_pts:
        nx, ny = gx / NOM_W, gy / NOM_H
        if any((px - nx) ** 2 + (py - ny) ** 2 <= tol_norm ** 2 for (px, py) in pred_xy):
            hits += 1
    return hits, len(gt_pts), len(pred_xy)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="gemini-2.5-flash")
    ap.add_argument("--n-def", type=int, default=12)
    ap.add_argument("--n-clean", type=int, default=8)
    args = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

    defected, clean = pick_cards(args.n_def, args.n_clean)
    print(f"model={args.model}  defected={len(defected)}  clean={len(clean)}")

    cent_err = {"lr": [], "tb": []}
    def_hits = def_total = def_pred = 0
    clean_fp = []
    tok_in = tok_out = 0
    rows = []

    for tag, group in [("def", defected), ("clean", clean)]:
        for cert, meta, fd in group:
            ip = f"data/tag_raw/{cert}/images/FRONT_MAIN.jpg"
            try:
                pred, (ti, to) = ask_gemini(client, args.model, ip)
            except Exception as e:
                print(f"  ERR {cert}: {str(e)[:120]}"); continue
            tok_in += ti; tok_out += to
            for k, e in score_centering(pred, meta):
                cent_err[k].append(e)
            if tag == "def":
                h, t, np_ = score_defects(pred, fd)
                def_hits += h; def_total += t; def_pred += np_
                rows.append((cert, "def", t, h, np_))
                print(f"  [def] {cert} grade={meta.get('grade')} TAGpts={t} hit={h} pred={np_}", flush=True)
            else:
                npred = len(pred.get("defects") or [])
                clean_fp.append(npred)
                rows.append((cert, "clean", 0, 0, npred))
                print(f"  [clean] {cert} grade={meta.get('grade')} pred_defects(FP)={npred}", flush=True)
            time.sleep(0.5)

    pin, pout = PRICE.get(args.model, (0.3, 2.5))
    cost_total = tok_in / 1e6 * pin + tok_out / 1e6 * pout
    ncards = len(rows)
    result = {
        "model": args.model, "n_cards": ncards,
        "centering_MAE_lr_pct": round(float(np.mean(cent_err["lr"])), 2) if cent_err["lr"] else None,
        "centering_MAE_tb_pct": round(float(np.mean(cent_err["tb"])), 2) if cent_err["tb"] else None,
        "defect_recall": round(def_hits / def_total, 3) if def_total else None,
        "defect_total_gt": def_total, "defect_total_pred": def_pred,
        "clean_FP_per_card": round(float(np.mean(clean_fp)), 2) if clean_fp else None,
        "tokens_in": tok_in, "tokens_out": tok_out,
        "cost_total_usd": round(cost_total, 4),
        "cost_per_card_usd": round(cost_total / max(ncards, 1), 5),
    }
    json.dump(result, open(f"{OUT}/llm_{args.model}.json", "w"), indent=2)
    print("\n=== LLM EVAL RESULT ===")
    for k, v in result.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
