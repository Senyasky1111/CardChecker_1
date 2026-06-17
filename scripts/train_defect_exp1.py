"""EXP-1 defect trainer — single class-agnostic "defectness" heatmap, NEGATIVE-AWARE.

Fixes the v3 model's fatal flaws (see stress-test + EXP-0):
  * single channel (no 7-class flood multiplier); type is a later downstream step.
  * trains on v4 tiles: de-centered positives + TRUSTWORTHY clean negatives (empty label).
  * eval is negative-aware at the TILE level: it finally MEASURES false positives
    (recall on positive tiles + FP on negative/background tiles + precision + F1),
    so the metric can see the flood the v3 metric was blind to.

Data: data/tag_v4_tiles (from build_exp1_tiles.py). Positive label = "tx ty"; negative = empty.

Usage:
  python scripts/train_defect_exp1.py --data data/tag_v4_tiles --sample 60 --overfit --epochs 30   # sanity
  python scripts/train_defect_exp1.py --data /workspace/data/tag_v4_tiles --epochs 25 --batch 48    # full
"""
from __future__ import annotations
import argparse, json, os, time
from pathlib import Path
from collections import Counter
import numpy as np
import torch, torch.nn as nn, torch.nn.functional as F
from torch.utils.data import Dataset, DataLoader
from PIL import Image
import torchvision.transforms as T

SIGMA_PX = 10.0  # gaussian sigma in tile px for the single defect channel


class TileDataset(Dataset):
    def __init__(self, root: Path, split: str, tile=512, stride=4, train=True):
        self.items = []  # (img_path, tx_or_None, ty_or_None)
        img_dir = root / "images" / split
        lbl_dir = root / "labels" / split
        for lp in lbl_dir.glob("*.txt"):
            ip = img_dir / f"{lp.stem}.jpg"
            if not ip.exists():
                continue
            txt = lp.read_text().strip().split()
            if len(txt) == 2:
                self.items.append((ip, float(txt[0]), float(txt[1])))  # positive
            else:
                self.items.append((ip, None, None))                    # negative
        self.tile = tile; self.stride = stride; self.hm = tile // stride; self.train = train
        norm = T.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225])
        self.tf = (T.Compose([T.ColorJitter(0.2, 0.2, 0.2, 0.03), T.ToTensor(), norm])
                   if train else T.Compose([T.ToTensor(), norm]))

    def __len__(self): return len(self.items)

    def _gauss(self, cx, cy):
        hm = np.zeros((1, self.hm, self.hm), np.float32)
        sig = SIGMA_PX / self.stride; r = int(3 * sig + 1)
        x0, x1 = max(0, int(cx - r)), min(self.hm, int(cx + r + 1))
        y0, y1 = max(0, int(cy - r)), min(self.hm, int(cy + r + 1))
        if x0 >= x1 or y0 >= y1: return hm
        xs = np.arange(x0, x1)[None, :]; ys = np.arange(y0, y1)[:, None]
        hm[0, y0:y1, x0:x1] = np.exp(-((xs - cx) ** 2 + (ys - cy) ** 2) / (2 * sig * sig))
        return hm

    def __getitem__(self, i):
        ip, tx, ty = self.items[i]
        x = self.tf(Image.open(ip).convert("RGB"))
        if tx is None:
            hm = np.zeros((1, self.hm, self.hm), np.float32); ispos = 0
        else:
            hm = self._gauss(tx * self.hm, ty * self.hm); ispos = 1
        return x, torch.from_numpy(hm), ispos


class HeatmapNet(nn.Module):
    def __init__(self, backbone="hrnet_w32", pretrained=True):
        super().__init__()
        import timm
        self.backbone = timm.create_model(backbone, features_only=True, pretrained=pretrained)
        self.feat_idx = 1  # stride-4
        ch = self.backbone.feature_info.channels()[self.feat_idx]
        self.head = nn.Sequential(
            nn.Conv2d(ch, 128, 3, padding=1), nn.BatchNorm2d(128), nn.ReLU(inplace=True),
            nn.Conv2d(128, 1, 1))
        self.head[-1].bias.data.fill_(-4.6)

    def forward(self, x):
        return self.head(self.backbone(x)[self.feat_idx])


def neg_loss(logits, gt):
    """CenterNet penalty-reduced focal (single channel), float32 + logsigmoid."""
    logits = logits.float()
    log_p = F.logsigmoid(logits); log_1mp = F.logsigmoid(-logits)
    pred = torch.sigmoid(logits).clamp(1e-6, 1 - 1e-6)
    pos = gt.ge(0.95).float(); neg = 1 - pos
    nw = torch.pow(1 - gt, 4)
    pl = (log_p * torch.pow(1 - pred, 2) * pos).sum()
    nl = (log_1mp * torch.pow(pred, 2) * nw * neg).sum()
    npos = pos.sum()
    return -nl if npos == 0 else -(pl + nl) / npos


def peaks(hm, thr=0.3, k=3):
    pooled = F.max_pool2d(hm[None, None], k, 1, k // 2)[0, 0]
    keep = (hm == pooled) & (hm > thr)
    return keep.nonzero(as_tuple=False).tolist()


@torch.no_grad()
def evaluate(model, loader, device, thr=0.3, tol=6):
    model.eval(); tp = fp = fn = neg_fp = n_neg = 0
    for x, hm_gt, ispos in loader:
        x = x.to(device)
        with torch.autocast("cuda", dtype=torch.bfloat16):
            logit = model(x)
        hm = torch.sigmoid(logit).float().cpu()
        for b in range(x.size(0)):
            pk = peaks(hm[b, 0], thr)
            if ispos[b].item() == 1:
                g = hm_gt[b, 0]
                gy, gx = (g == g.max()).nonzero()[0].tolist()
                hit = any(abs(py - gy) <= tol and abs(px - gx) <= tol for py, px in pk)
                if hit: tp += 1
                else: fn += 1
                fp += max(0, len(pk) - (1 if hit else 0))
            else:
                n_neg += 1; neg_fp += len(pk)
    prec = tp / max(tp + fp, 1); rec = tp / max(tp + fn, 1)
    f1 = 2 * prec * rec / max(prec + rec, 1e-9)
    return {"precision": round(prec, 3), "recall": round(rec, 3), "f1": round(f1, 3),
            "fp_per_neg_tile": round(neg_fp / max(n_neg, 1), 3), "n_neg": n_neg, "tp": tp, "fn": fn}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, default=Path("data/tag_v4_tiles"))
    ap.add_argument("--backbone", default="hrnet_w32")
    ap.add_argument("--epochs", type=int, default=25)
    ap.add_argument("--batch", type=int, default=48)
    ap.add_argument("--lr", type=float, default=2e-3)
    ap.add_argument("--out", type=Path, default=Path("runs/defect_exp1"))
    ap.add_argument("--sample", type=int, default=None)
    ap.add_argument("--overfit", action="store_true")
    ap.add_argument("--pretrained", type=int, default=1)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    device = "cuda" if torch.cuda.is_available() else "cpu"

    tr = TileDataset(args.data, "train", train=True)
    va = TileDataset(args.data, "val", train=False)
    if args.sample:
        import random as _r
        _r.Random(0).shuffle(tr.items)  # mix pos+neg into the sample (glob order is pos-then-neg)
        tr.items = tr.items[:args.sample]
        if args.overfit:
            va = TileDataset(args.data, "train", train=False); va.items = list(tr.items)
        else:
            va.items = va.items[:max(80, args.sample)]
    npos = sum(1 for _, tx, _ in tr.items if tx is not None)
    print(f"train={len(tr)} (pos={npos}, neg={len(tr)-npos})  val={len(va)}  device={device}")

    model = HeatmapNet(args.backbone, pretrained=bool(args.pretrained)).to(device)
    dl_tr = DataLoader(tr, batch_size=args.batch, shuffle=True, num_workers=min(8, os.cpu_count() or 4),
                       pin_memory=True, drop_last=True)
    dl_va = DataLoader(va, batch_size=args.batch, shuffle=False, num_workers=min(8, os.cpu_count() or 4))
    opt = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=args.lr, total_steps=args.epochs * len(dl_tr), pct_start=0.1)

    best = -1; log = []
    for ep in range(args.epochs):
        model.train(); t0 = time.time(); tot = nb = 0
        for x, hm, ispos in dl_tr:
            x = x.to(device); hm = hm.to(device)
            with torch.autocast("cuda", dtype=torch.bfloat16, enabled=(device == "cuda")):
                loss = neg_loss(model(x), hm)
            opt.zero_grad(); loss.backward(); opt.step(); sched.step()
            tot += loss.item(); nb += 1
        res = evaluate(model, dl_va, device)
        row = {"epoch": ep, "loss": round(tot / max(nb, 1), 4), **res, "sec": round(time.time() - t0)}
        log.append(row)
        print(f"ep{ep:02d} loss={row['loss']:.3f} P={res['precision']} R={res['recall']} "
              f"F1={res['f1']} FP/neg={res['fp_per_neg_tile']} ({row['sec']}s)", flush=True)
        score = res["f1"]
        if score > best:
            best = score; torch.save({"model": model.state_dict(), "args": vars(args)}, args.out / "best.pt")
        (args.out / "log.json").write_text(json.dumps(log, indent=2, default=str))
    print(f"\nBest val F1: {best:.4f}. Saved {args.out}/best.pt")


if __name__ == "__main__":
    main()
