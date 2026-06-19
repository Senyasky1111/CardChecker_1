"""Binary zone whitening/wear classifier — clean, well-posed (unlike the failed heatmap).

Input: zone crops (data/zone_tiles/{train,val,test}/{0,1}). 0=clean (gem-mint zones), 1=wear
(TAG corner/edge-wear zones). Small timm backbone, weighted CE for imbalance. Reports
precision/recall/F1 for the WEAR class (precision-first: don't cry wolf).

Usage:
  python scripts/train_zone_classifier.py --data data/zone_tiles --epochs 12 --backbone mobilenetv3_small_100
"""
from __future__ import annotations
import argparse, json, os, time
from pathlib import Path
import numpy as np
import torch, torch.nn as nn
from torch.utils.data import DataLoader, WeightedRandomSampler
from torchvision import datasets, transforms as T


def build_loaders(data, size, batch):
    norm = T.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])
    tf_tr = T.Compose([T.RandomResizedCrop(size, scale=(0.8, 1.0)), T.RandomHorizontalFlip(),
                       T.RandomVerticalFlip(), T.RandomRotation(8),
                       T.ColorJitter(0.15, 0.15, 0.1), T.ToTensor(), norm])
    tf_ev = T.Compose([T.Resize(size), T.CenterCrop(size), T.ToTensor(), norm])
    tr = datasets.ImageFolder(Path(data) / "train", tf_tr)
    va = datasets.ImageFolder(Path(data) / "val", tf_ev)
    # class-balanced sampling (worn is the minority)
    labels = np.array([y for _, y in tr.samples])
    cw = 1.0 / np.maximum(np.bincount(labels), 1)
    sw = cw[labels]
    sampler = WeightedRandomSampler(torch.as_tensor(sw, dtype=torch.double), len(sw))
    dl_tr = DataLoader(tr, batch_size=batch, sampler=sampler, num_workers=min(8, os.cpu_count() or 4), pin_memory=True)
    dl_va = DataLoader(va, batch_size=batch, shuffle=False, num_workers=min(8, os.cpu_count() or 4))
    return tr, dl_tr, dl_va, labels


@torch.no_grad()
def evaluate(model, loader, device):
    model.eval(); tp = fp = fn = tn = 0
    for x, y in loader:
        x = x.to(device)
        with torch.autocast(device_type="cuda", dtype=torch.bfloat16, enabled=(device == "cuda")):
            pred = model(x).float().argmax(1).cpu()
        for p, t in zip(pred.tolist(), y.tolist()):
            tp += (p == 1 and t == 1); fp += (p == 1 and t == 0)
            fn += (p == 0 and t == 1); tn += (p == 0 and t == 0)
    prec = tp / max(tp + fp, 1); rec = tp / max(tp + fn, 1)
    f1 = 2 * prec * rec / max(prec + rec, 1e-9)
    acc = (tp + tn) / max(tp + fp + fn + tn, 1)
    return {"precision": round(prec, 3), "recall": round(rec, 3), "f1": round(f1, 3),
            "acc": round(acc, 3), "tp": tp, "fp": fp, "fn": fn, "tn": tn}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/zone_tiles")
    ap.add_argument("--backbone", default="mobilenetv3_small_100")
    ap.add_argument("--size", type=int, default=224)
    ap.add_argument("--epochs", type=int, default=12)
    ap.add_argument("--batch", type=int, default=64)
    ap.add_argument("--lr", type=float, default=3e-4)
    ap.add_argument("--out", type=Path, default=Path("runs/zone_clf"))
    ap.add_argument("--pretrained", type=int, default=1)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    import timm

    tr, dl_tr, dl_va, labels = build_loaders(args.data, args.size, args.batch)
    print(f"train={len(tr)} (clean={int((labels==0).sum())}, wear={int((labels==1).sum())}) device={device}")
    model = timm.create_model(args.backbone, pretrained=bool(args.pretrained), num_classes=2).to(device)
    # class-weighted loss as well (precision matters)
    cw = torch.tensor([1.0, float((labels == 0).sum()) / max((labels == 1).sum(), 1)], device=device).clamp(0.3, 3)
    crit = nn.CrossEntropyLoss(weight=cw)
    opt = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=args.lr, total_steps=args.epochs * len(dl_tr), pct_start=0.1)

    best = -1; log = []
    for ep in range(args.epochs):
        model.train(); t0 = time.time(); tot = nb = 0
        for x, y in dl_tr:
            x, y = x.to(device), y.to(device)
            with torch.autocast(device_type="cuda", dtype=torch.bfloat16, enabled=(device == "cuda")):
                loss = crit(model(x), y)
            opt.zero_grad(); loss.backward(); opt.step(); sched.step()
            tot += loss.item(); nb += 1
        res = evaluate(model, dl_va, device)
        row = {"epoch": ep, "loss": round(tot / max(nb, 1), 4), **res, "sec": round(time.time() - t0)}
        log.append(row)
        print(f"ep{ep:02d} loss={row['loss']:.3f} P={res['precision']} R={res['recall']} F1={res['f1']} acc={res['acc']} ({row['sec']}s)", flush=True)
        if res["f1"] > best:
            best = res["f1"]; torch.save({"model": model.state_dict(), "args": vars(args)}, args.out / "best.pt")
        (args.out / "log.json").write_text(json.dumps(log, indent=2))
    print(f"\nBest val F1: {best:.4f}. Saved {args.out}/best.pt")


if __name__ == "__main__":
    main()
