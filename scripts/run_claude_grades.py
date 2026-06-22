"""Batch-run the Claude grader over zone montages, concurrently. Writes grades + cost.

Needs ANTHROPIC_API_KEY. Builds montages first via scripts/build_grade_test.py if missing.

Usage:
  python scripts/run_claude_grades.py --n 50                 # 50 cards
  python scripts/run_claude_grades.py --n 2000 --workers 16  # full spread
  python scripts/run_claude_grades.py --no-thinking          # cheaper/faster
"""
from __future__ import annotations
import argparse, json, os, sys, glob
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

def _load_dotenv():
    f = Path(__file__).resolve().parent.parent / ".env"
    if not f.exists():
        return
    for line in f.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

_load_dotenv()
from src.claude_grade import ClaudeGrader, prep_full_card

# Opus 4.8 pricing $/1M
IN_PRICE, OUT_PRICE = 5.0, 25.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--montage-dir", default="runs/grade_test/montage")
    ap.add_argument("--n", type=int, default=50)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--no-thinking", action="store_true")
    ap.add_argument("--variant", default="base")
    ap.add_argument("--out", default="runs/grade_test/claude_grades.json")
    args = ap.parse_args()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("ERROR: set ANTHROPIC_API_KEY first (export ANTHROPIC_API_KEY=sk-ant-...).")

    fronts = sorted(glob.glob(f"{args.montage_dir}/*_front.png"))[:args.n]
    certs = [Path(f).name[:-len("_front.png")] for f in fronts]
    print(f"grading {len(certs)} cards, workers={args.workers}, thinking={not args.no_thinking}")

    grader = ClaudeGrader(thinking=not args.no_thinking, variant=args.variant)

    fulldir = Path(args.montage_dir).parent / "fullcard"
    fulldir.mkdir(parents=True, exist_ok=True)

    def one(cert):
        fp = f"{args.montage_dir}/{cert}_front.png"
        bp = f"{args.montage_dir}/{cert}_back.png"
        ff = prep_full_card(f"data/tag_raw/{cert}/images/FRONT_MAIN.jpg", str(fulldir / f"{cert}_front.png"))
        bf = prep_full_card(f"data/tag_raw/{cert}/images/BACK_MAIN.jpg", str(fulldir / f"{cert}_back.png"))
        try:
            return cert, grader.grade_montages(fp, bp if os.path.exists(bp) else None,
                                               front_full=ff, back_full=bf)
        except Exception as e:
            return cert, {"error": str(e)}

    results, tin, tout, done = {}, 0, 0, 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        for cert, r in (f.result() for f in as_completed([ex.submit(one, c) for c in certs])):
            results[cert] = r; done += 1
            if "_usage" in r:
                tin += r["_usage"]["input"]; tout += r["_usage"]["output"]
            g = r.get("overall_grade", "ERR")
            print(f"[{done}/{len(certs)}] {cert}: {g}", flush=True)

    Path(args.out).write_text(json.dumps(results, indent=2))
    cost = tin / 1e6 * IN_PRICE + tout / 1e6 * OUT_PRICE
    print(f"\nDONE -> {args.out}")
    print(f"tokens: in={tin:,} out={tout:,}  cost=${cost:.2f}  (~${cost/max(done,1):.3f}/card)")
    print(f"extrapolated to 2000 cards: ~${cost/max(done,1)*2000:.0f}")


if __name__ == "__main__":
    main()
