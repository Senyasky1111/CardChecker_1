"""Train the direct grade-regression head (v3.3 P6 — the proof-of-life / safety-net floor).

Frozen DINOv2-ViT-L/14 backbone + small MLP head. Predicts TAG overall grade (1-10)
from a single MAIN card image. This is the cheapest signal that tells us whether the
whole approach produces a sensible grade at all — the headline KPI.

- Labels: TAG 'grade' from each cert's metadata.json (41k cards with grade>0).
- Split: GroupKFold by cert-prefix (matches the dataset's existing split dirs).
- Metrics: macro-MAE (avoid mode-collapse on NM-heavy skew), within-±1.0, Spearman ρ.

Usage on pod:
  python3 scripts/train_grade_head.py \
    --data /workspace/data/tag_v3/detection \
    --raw  /workspace/data/tag_raw_meta   # optional; falls back to embedded grades
    --epochs 30 --out /workspace/runs/grade_head

If tag_raw metadata isn't on the pod, pass --grades-json (a {cert: grade} map we
pre-extract locally and ship — tiny file).
"""
from __future__ import annotations
import argparse, json, math, os, time
from pathlib import Path
from collections import defaultdict

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader
from PIL import Image
import torchvision.transforms as T


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

class GradeDataset(Dataset):
    def __init__(self, items, img_root: Path, split: str, train: bool):
        # items: list of (cert, side, grade)
        self.items = items
        self.img_root = img_root
        self.split = split
        # DINOv2 expects ImageNet normalization; 518 = 37 patches @ patch14 (good for L)
        size = 518
        aug = []
        if train:
            aug = [T.ColorJitter(0.2, 0.2, 0.2, 0.05)]
        self.tf = T.Compose([
            T.Resize((size, size)),
            *aug,
            T.ToTensor(),
            T.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
        ])

    def __len__(self):
        return len(self.items)

    def __getitem__(self, i):
        cert, side, grade = self.items[i]
        p = self.img_root / "images" / self.split / f"{cert}_{side}.jpg"
        img = Image.open(p).convert("RGB")
        return self.tf(img), torch.tensor(grade, dtype=torch.float32)


def load_items(data_root: Path, grades: dict, split: str):
    """Pair each available image with its cert grade (front only for v1 grade head)."""
    items = []
    img_dir = data_root / "images" / split
    if not img_dir.exists():
        return items
    for p in img_dir.glob("*_front.jpg"):
        cert = p.stem.rsplit("_", 1)[0]
        g = grades.get(cert)
        if g and g > 0:
            items.append((cert, "front", float(g)))
    return items


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------

class GradeHead(nn.Module):
    def __init__(self, backbone, feat_dim=1024):
        super().__init__()
        self.backbone = backbone
        for p in self.backbone.parameters():
            p.requires_grad = False
        self.head = nn.Sequential(
            nn.LayerNorm(feat_dim),
            nn.Linear(feat_dim, 256), nn.GELU(), nn.Dropout(0.2),
            nn.Linear(256, 1),
        )

    @torch.no_grad()
    def _feat(self, x):
        # DINOv2 hub model: forward returns CLS embedding via .forward; use norm'd CLS
        return self.backbone(x)

    def forward(self, x):
        f = self._feat(x)
        return self.head(f).squeeze(-1)


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def spearman(a, b):
    a = np.asarray(a); b = np.asarray(b)
    ra = a.argsort().argsort().astype(float)
    rb = b.argsort().argsort().astype(float)
    ra -= ra.mean(); rb -= rb.mean()
    denom = math.sqrt((ra**2).sum() * (rb**2).sum())
    return float((ra*rb).sum()/denom) if denom else 0.0

def macro_mae(pred, true, n_bins=10):
    """MAE averaged per true-grade bin → punishes mode-collapse on NM-heavy skew."""
    pred = np.asarray(pred); true = np.asarray(true)
    bins = np.clip(np.round(true).astype(int), 1, 10)
    maes = []
    for g in range(1, 11):
        m = bins == g
        if m.sum() >= 5:
            maes.append(np.abs(pred[m] - true[m]).mean())
    return float(np.mean(maes)) if maes else float("nan")


# ---------------------------------------------------------------------------
# Train
# ---------------------------------------------------------------------------

def evaluate(model, loader, device):
    model.eval(); P=[]; Tt=[]
    with torch.no_grad():
        for x, y in loader:
            x = x.to(device)
            with torch.autocast(device_type="cuda", dtype=torch.bfloat16):
                p = model(x)
            P += p.float().cpu().tolist(); Tt += y.tolist()
    P = np.clip(P, 1, 10)
    mae = float(np.abs(np.array(P)-np.array(Tt)).mean())
    return {
        "mae": mae,
        "macro_mae": macro_mae(P, Tt),
        "within_1": float((np.abs(np.array(P)-np.array(Tt))<=1.0).mean()),
        "within_0.5": float((np.abs(np.array(P)-np.array(Tt))<=0.5).mean()),
        "spearman": spearman(P, Tt),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, default=Path("/workspace/data/tag_v3/detection"))
    ap.add_argument("--grades-json", type=Path, required=True,
                    help="{cert: grade} map (extracted from TAG metadata)")
    ap.add_argument("--epochs", type=int, default=30)
    ap.add_argument("--batch", type=int, default=64)
    ap.add_argument("--lr", type=float, default=3e-4)
    ap.add_argument("--out", type=Path, default=Path("/workspace/runs/grade_head"))
    ap.add_argument("--backbone", default="dinov2_vitl14")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    device = "cuda"
    grades = json.loads(Path(args.grades_json).read_text())

    train_items = load_items(args.data, grades, "train")
    val_items   = load_items(args.data, grades, "val")
    test_items  = load_items(args.data, grades, "test")
    print(f"items: train={len(train_items)} val={len(val_items)} test={len(test_items)}")
    print(f"grade dist (train): ", end="")
    dist = defaultdict(int)
    for _,_,g in train_items: dist[round(g)] += 1
    print(dict(sorted(dist.items())))

    print(f"Loading backbone {args.backbone} (frozen)...")
    # GitHub API rate-limits the fork-validation call (HTTP 403) on fresh containers.
    # The zipball download itself is fine (codeload), so no-op the validation.
    torch.hub._validate_not_a_forked_repo = lambda *a, **k: None
    try:
        backbone = torch.hub.load("facebookresearch/dinov2", args.backbone,
                                  source="github", trust_repo=True).to(device).eval()
    except Exception as e:
        print(f"hub github load failed ({e}); trying local clone...")
        import subprocess
        clone = Path("/workspace/dinov2_repo")
        if not clone.exists():
            subprocess.run(["git", "clone", "--depth", "1",
                            "https://github.com/facebookresearch/dinov2", str(clone)], check=True)
        backbone = torch.hub.load(str(clone), args.backbone, source="local",
                                  trust_repo=True).to(device).eval()
    model = GradeHead(backbone, feat_dim=1024).to(device)

    dl_tr = DataLoader(GradeDataset(train_items, args.data, "train", True),
                       batch_size=args.batch, shuffle=True, num_workers=8, pin_memory=True, drop_last=True)
    dl_va = DataLoader(GradeDataset(val_items, args.data, "val", False),
                       batch_size=args.batch, shuffle=False, num_workers=8, pin_memory=True)
    dl_te = DataLoader(GradeDataset(test_items, args.data, "test", False),
                       batch_size=args.batch, shuffle=False, num_workers=8, pin_memory=True)

    opt = torch.optim.AdamW(model.head.parameters(), lr=args.lr, weight_decay=0.05)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=args.epochs)
    # Huber on grade; macro metric guards skew at eval time
    loss_fn = nn.HuberLoss(delta=1.0)

    best_val = 1e9
    log = []
    for ep in range(args.epochs):
        model.train(); t0=time.time(); tot=0; nb=0
        for x, y in dl_tr:
            x=x.to(device); y=y.to(device)
            with torch.autocast(device_type="cuda", dtype=torch.bfloat16):
                p = model(x); loss = loss_fn(p, y)
            opt.zero_grad(); loss.backward(); opt.step()
            tot += loss.item(); nb += 1
        sched.step()
        va = evaluate(model, dl_va, device)
        row = {"epoch": ep, "train_loss": tot/max(nb,1), **{f"val_{k}":v for k,v in va.items()}, "sec": round(time.time()-t0)}
        log.append(row)
        print(f"ep{ep:02d} loss={row['train_loss']:.3f} "
              f"val_macroMAE={va['macro_mae']:.3f} val_within1={va['within_1']:.3f} "
              f"val_ρ={va['spearman']:.3f} ({row['sec']}s)")
        if va["macro_mae"] < best_val:
            best_val = va["macro_mae"]
            torch.save({"head": model.head.state_dict(), "args": vars(args)}, args.out/"best.pt")
        (args.out/"log.json").write_text(json.dumps(log, indent=2, default=str))

    # Final test with best head
    ckpt = torch.load(args.out/"best.pt")
    model.head.load_state_dict(ckpt["head"])
    te = evaluate(model, dl_te, device)
    print("\n=== TEST (best-val head) ===")
    for k,v in te.items(): print(f"  {k}: {v:.4f}")
    (args.out/"test_metrics.json").write_text(json.dumps(te, indent=2))
    print(f"\nSaved to {args.out}")


if __name__ == "__main__":
    main()
