"""Golden regression of the NEW weakest-link grading logic on the 95-card set + cap-threshold sweep.

DESIGN (cost-aware):
  PHASE 1 (paid, ~$5, ONCE): for each usable card in runs/grade_test_100, build card_box montages
          + centering offsets from the TAG data, call grade_montages + detect_zones CONCURRENTLY,
          and CACHE the raw holistic + detector dicts -> runs/grade_regression_95_cache.json.
          Re-runs are FREE (cache hit) unless --refresh.
  PHASE 2 (free, offline): score the CURRENT aggregation (weakest-link + whitening cap, no TAG
          calibration) vs ground-truth grade, then SWEEP 2-3 whitening-cap threshold variants by
          re-aggregating the cached outputs (no extra API calls). Reports MAE / +/-1 / +/-2 overall
          and by band, plus gem over-cap rate (the known holo-front over-flag failure).

Run:  ./venv/Scripts/python.exe scripts/grade_regression_95.py            # cache-aware
      ./venv/Scripts/python.exe scripts/grade_regression_95.py --refresh  # force paid re-run
      ./venv/Scripts/python.exe scripts/grade_regression_95.py --score    # offline scoring only
"""
import os, sys, json, re, tempfile
from pathlib import Path
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

for ln in Path('.env').read_text().splitlines():
    if ln.strip() and not ln.startswith('#') and '=' in ln:
        k, v = ln.split('=', 1); os.environ.setdefault(k.strip(), v.strip())
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import ImageFile
ImageFile.LOAD_TRUNCATED_IMAGES = True
from src.claude_grade import ClaudeGrader
from src import pregrade_service as svc
from src import pregrade_distribution as pd

CACHE = "runs/grade_regression_95_cache.json"
GT = "runs/grade_test_100/_gt_DO_NOT_READ_until_scoring.json"


def cent_off_axis(s):
    if not s:
        return None
    nums = [float(x) for x in re.findall(r'[0-9.]+', str(s))]
    nums = [v for v in nums if 0.0 <= v <= 100.0]
    return max(abs(v - 50.0) for v in nums) if nums else None


def worst_off(lr, tb):
    offs = [o for o in (cent_off_axis(lr), cent_off_axis(tb)) if o is not None]
    return max(offs) if offs else None


# ---------------------------------------------------------------- PHASE 1: paid pass
def usable_cards():
    gt = json.load(open(GT))
    out = []
    for cert, v in gt.items():
        fr = f'data/tag_raw/{cert}/images/FRONT_MAIN.jpg'
        bk = f'data/tag_raw/{cert}/images/BACK_MAIN.jpg'
        mp = f'data/tag_raw/{cert}/metadata.json'
        if not (os.path.exists(fr) and os.path.exists(bk) and os.path.exists(mp)):
            continue
        m = json.load(open(mp, encoding='utf-8'))
        if not (m.get('centering_front_lr') and m.get('centering_back_lr')):
            continue
        out.append((cert, v, m))
    return out


def run_one(grader, cert, v, m):
    fb = open(f'data/tag_raw/{cert}/images/FRONT_MAIN.jpg', 'rb').read()
    bb = open(f'data/tag_raw/{cert}/images/BACK_MAIN.jpg', 'rb').read()
    foff = worst_off(m.get('centering_front_lr'), m.get('centering_front_tb'))
    boff = worst_off(m.get('centering_back_lr'), m.get('centering_back_tb'))
    with tempfile.TemporaryDirectory(prefix="reg_") as tmp:
        a = svc.build_assets(fb, bb, tmp, cert)
        with ThreadPoolExecutor(max_workers=2) as ex:
            fh = ex.submit(grader.grade_montages, a["front_montage"], a["back_montage"],
                           a["front_full"], a["back_full"])
            fd = ex.submit(grader.detect_zones, a["front_montage"], a["back_montage"],
                           a["front_full"], a["back_full"])
            holistic, det = fh.result(), fd.result()
    return cert, {"tag": float(v["grade"]), "band": v["band"], "foff": foff, "boff": boff,
                  "holistic": holistic, "detections": det}


def build_cache(refresh=False):
    cache = {}
    if os.path.exists(CACHE) and not refresh:
        cache = json.load(open(CACHE))
    cards = usable_cards()
    todo = [(c, v, m) for c, v, m in cards if c not in cache]
    print(f"PHASE 1: {len(cards)} usable cards, {len(cache)} cached, {len(todo)} to grade (paid)")
    if todo:
        grader = ClaudeGrader()
        done = 0
        with ThreadPoolExecutor(max_workers=5) as ex:
            futs = [ex.submit(run_one, grader, c, v, m) for c, v, m in todo]
            for f in futs:
                try:
                    cert, rec = f.result()
                    cache[cert] = rec
                    done += 1
                    if done % 10 == 0:
                        print(f"  graded {done}/{len(todo)}")
                        json.dump(cache, open(CACHE, "w"), indent=1)   # checkpoint
                except Exception as e:
                    print(f"  card failed: {type(e).__name__}: {e}")
        json.dump(cache, open(CACHE, "w"), indent=1)
    print(f"  cache now has {len(cache)} cards -> {CACHE}\n")
    return cache


# ---------------------------------------------------------------- PHASE 2: offline aggregation + sweep
# Cap variants: (n_mod, n_heavy) -> cap grade or None. n_mod = MODERATE+ count, n_heavy = HEAVY count.
def cap_current(n_mod, n_heavy):
    if n_heavy >= 2 or n_mod >= 4: return 5.0
    if n_heavy >= 1: return 6.0
    if n_mod >= 2: return 7.0
    if n_mod >= 1: return 9.0
    return None

def cap_lenient(n_mod, n_heavy):           # defends holo-front over-flag: needs MORE wear to cap
    if n_heavy >= 2 or n_mod >= 5: return 5.0
    if n_heavy >= 1: return 6.0
    if n_mod >= 3: return 7.0
    if n_mod >= 2: return 9.0              # a single MODERATE no longer caps
    return None

def cap_heavy_only(n_mod, n_heavy):        # only HEAVY caps; MODERATE never (max holo defense)
    if n_heavy >= 2: return 5.0
    if n_heavy >= 1: return 6.0
    return None

def cap_heavy_plus4(n_mod, n_heavy):       # heavy-driven + only ALL-AROUND moderate (>=4) caps
    if n_heavy >= 2: return 5.0
    if n_heavy >= 1: return 6.0
    if n_mod >= 4: return 7.0              # 4+ moderate zones = real whitening, still cap
    return None

def cap_heavy_plus3(n_mod, n_heavy):       # heavy-driven + a softer net for 3+ moderate
    if n_heavy >= 2: return 5.0
    if n_heavy >= 1: return 6.0
    if n_mod >= 4: return 7.0
    if n_mod >= 3: return 8.0
    return None

CAPS = {"current": cap_current, "lenient": cap_lenient, "heavy_only": cap_heavy_only,
        "heavy_plus4": cap_heavy_plus4, "heavy_plus3": cap_heavy_plus3}


def aggregate(rec, cap_fn):
    """Re-implement assemble's grade math with a swappable cap. Returns most_likely grade."""
    hol, det = rec["holistic"], rec["detections"]
    back = hol.get("back")
    fc = pd.centering_grade_from_offset(rec["foff"])
    bc = pd.centering_grade_from_offset(rec["boff"]) if back else None

    def side_grade(side, cent_g):
        s = hol.get(side)
        if not s:
            return None
        cent = cent_g if cent_g is not None else s.get("centering")
        return pd.weakest_link([cent, s.get("corners"), s.get("edges"), s.get("surface")])

    def worn(side):
        z = (det or {}).get(side) or {}
        n_mod = sum(1 for x in z.values() if x in ("MODERATE", "HEAVY"))
        n_heavy = sum(1 for x in z.values() if x == "HEAVY")
        return n_mod, n_heavy

    fg = side_grade("front", fc)
    nm_f, nh_f = worn("front")
    cap_f = cap_fn(nm_f, nh_f)
    if fg is not None and cap_f is not None:
        fg = min(fg, cap_f)

    if back:
        bg = side_grade("back", bc)
        nm_b, nh_b = worn("back")
        cap_b = cap_fn(nm_b, nh_b)
        if bg is not None and cap_b is not None:
            bg = min(bg, cap_b)
        leniency = 0.0 if nm_b else svc.BACK_LENIENCY
        bl = min(bg + leniency, 10.0) if bg is not None else None
        overall_raw = pd.weakest_link([fg, bl])
    else:
        overall_raw = fg if fg is not None else hol.get("overall_grade")
    return pd.build_overall(raw_overall=overall_raw)["most_likely"]


def score(cache):
    print("PHASE 2: scoring (offline, free)\n")
    bands = ["gem", "nm", "ex", "low"]
    print(f"{'VARIANT':<12}{'MAE':<7}{'+/-1':<7}{'+/-2':<7}  by-band MAE (gem/nm/ex/low)   gem_overcap")
    results = {}
    for name, cap_fn in CAPS.items():
        errs, band_err, preds = [], defaultdict(list), {}
        gem_overcap = 0
        for cert, rec in cache.items():
            ml = aggregate(rec, cap_fn)
            e = abs(ml - rec["tag"])
            errs.append(e); band_err[rec["band"]].append(e); preds[cert] = ml
            if rec["band"] == "gem" and ml < rec["tag"] - 1:   # gem dragged >1 below truth
                gem_overcap += 1
        n = len(errs)
        mae = sum(errs) / n
        w1 = 100 * sum(1 for e in errs if e <= 1) / n
        w2 = 100 * sum(1 for e in errs if e <= 2) / n
        bm = "/".join(f"{(sum(band_err[b])/len(band_err[b])):.2f}" if band_err[b] else "-" for b in bands)
        print(f"{name:<12}{mae:<7.2f}{w1:<7.0f}{w2:<7.0f}  {bm:<28}  {gem_overcap}")
        results[name] = {"mae": mae, "w1": w1, "w2": w2,
                         "band_mae": {b: (sum(band_err[b])/len(band_err[b]) if band_err[b] else None) for b in bands},
                         "gem_overcap": gem_overcap, "preds": preds}

    # per-card detail under the current variant (where do errors live?)
    print(f"\nPer-card (current variant), sorted by |error|:")
    print(f"{'CERT':<10}{'TAG':<5}{'PRED':<6}{'BAND':<6}{'ERR'}")
    cur = results["current"]["preds"]
    rows = sorted(((c, cache[c]["tag"], cur[c], cache[c]["band"], abs(cur[c]-cache[c]["tag"]))
                   for c in cache), key=lambda r: -r[4])
    for c, tag, pred, band, err in rows[:18]:
        print(f"{c:<10}{tag:<5g}{pred:<6g}{band:<6}{err:.1f}")

    json.dump(results, open("runs/grade_regression_95_scored.json", "w"), indent=2, default=str)
    print(f"\nsaved -> runs/grade_regression_95_scored.json")
    return results


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--score" in args:
        score(json.load(open(CACHE)))
    else:
        cache = build_cache(refresh="--refresh" in args)
        score(cache)
