"""Visualize SAM2 refinement vs synthetic bboxes for the smoke-test cards.

Draws side-by-side (synthetic | SAM2-refined) for every card that has both
a source label and a refined label. Saves to /workspace/sam2_check/ and also
uploads to an HF dataset repo so we can eyeball them before the full run.

Usage on pod:
  python3 scripts/runpod/viz_sam2_check.py
"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import os, sys

SRC = Path("/workspace/data/tag_v3/detection")
# SAM2 output dir can be passed as argv[1]; default to detection_sam2
SAM2 = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/workspace/data/tag_v3/detection_sam2")
OUT = Path("/workspace/sam2_check")
OUT.mkdir(parents=True, exist_ok=True)
# Only visualize cards containing center-surface defect classes (2=surface,3=scratch,4=crease,5=dent)
PREFER_CLASSES = {2, 3, 4, 5}

CLASSES = ["corner_wear","edge_wear","surface_damage","scratch","crease","dent","stain"]
COLORS = [(230,40,40),(40,200,40),(60,130,230),(255,170,30),(180,80,200),(60,200,200),(220,200,40)]

try:
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 18)
except Exception:
    font = ImageFont.load_default()

def draw(img, lines, title):
    im = img.copy()
    d = ImageDraw.Draw(im, "RGBA")
    W, H = im.size
    for ln in lines:
        p = ln.split()
        if len(p) != 5:
            continue
        c = int(p[0]); xn, yn, wn, hn = map(float, p[1:])
        x, y, w, h = xn*W, yn*H, wn*W, hn*H
        col = COLORS[c % 7]
        d.rectangle([x-w/2, y-h/2, x+w/2, y+h/2], outline=col+(255,), width=3)
        d.text((max(0,x-w/2), max(0,y-h/2-18)), CLASSES[c % 7], fill=col+(255,), font=font)
    d.rectangle([0,0,W,26], fill=(0,0,0,200))
    d.text((5,4), title, fill=(255,255,255), font=font)
    return im

n = 0
for sam2_lbl in sorted((SAM2/"labels").rglob("*.txt")):
    split = sam2_lbl.parent.name
    stem = sam2_lbl.stem
    src_lbl = SRC/"labels"/split/f"{stem}.txt"
    img_path = SRC/"images"/split/f"{stem}.jpg"
    if not img_path.exists() or not src_lbl.exists():
        continue
    sam2_lines = [l for l in sam2_lbl.read_text().splitlines() if l.strip()]
    if not sam2_lines:
        continue
    # Only keep cards that contain a center-surface defect class
    classes_here = {int(l.split()[0]) for l in sam2_lines if l.split()}
    if not (classes_here & PREFER_CLASSES):
        continue
    src_lines = [l for l in src_lbl.read_text().splitlines() if l.strip()]
    img = Image.open(img_path).convert("RGB")
    W, H = img.size
    left = draw(img, src_lines, f"{stem} SYNTHETIC ({len(src_lines)} box)")
    right = draw(img, sam2_lines, f"{stem} SAM2 ({len(sam2_lines)} box)")
    combo = Image.new("RGB", (W*2+6, H), (50,50,50))
    combo.paste(left, (0,0)); combo.paste(right, (W+6,0))
    # downscale for quick viewing
    scale = 900/combo.width
    combo = combo.resize((900, int(combo.height*scale)))
    combo.save(OUT/f"{stem}.jpg", quality=85)
    n += 1

print(f"Wrote {n} comparison images to {OUT}")

# Upload to HF for review
try:
    from huggingface_hub import HfApi, login
    tok = os.environ.get("HF_TOKEN")
    if tok:
        login(token=tok)
        api = HfApi()
        api.create_repo("Senyasky1111/cardchecker-sam2-check", repo_type="dataset", private=True, exist_ok=True)
        api.upload_folder(folder_path=str(OUT), repo_id="Senyasky1111/cardchecker-sam2-check", repo_type="dataset")
        print("Uploaded to HF: Senyasky1111/cardchecker-sam2-check")
    else:
        print("HF_TOKEN not set — skipping upload")
except Exception as e:
    print(f"HF upload failed: {e}")
