"""Train the defect-detection heatmap model on native-res 512px tiles.

Architecture (per v1 spec):
- Backbone: HRNet-W32/W48 (timm) — parallel hi-res streams, the 2025 industrial-
  inspection default for tiny defects. (DINOv2 ViT can't resolve hairlines.)
- Head: per-class FIDT-style heatmap (7 channels) at stride-4 over the tile.
- Loss: penalty-reduced focal loss (CenterNet) on Gaussian targets + effective-number
  class-balancing (beta=0.9999) for the 140:1 imbalance + per-class sigma.
- Targets: each tile has ONE point label (its centering defect) at known (tx,ty);
  we splat a Gaussian on the matching class channel. (Tiles are defect-centered crops.)
- Eval: per-class point-F1 @ tolerance radius via local-max peak extraction.

This is intentionally a per-tile detector first (each tile = one defect-centered crop).
Whole-card inference = slide tiles over the card, stitch heatmaps. (sep. inference script.)

Usage on pod:
  python3 scripts/train_defect_heatmap.py \
    --data /workspace/data/tag_v3_tiles --epochs 40 --out /workspace/runs/defect_hm
"""
from __future__ import annotations
import argparse, json, math, time
from pathlib import Path
from collections import Counter

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import Dataset, DataLoader
from PIL import Image
import torchvision.transforms as T

CLASSES = ["corner_wear","edge_wear","surface_damage","scratch","crease","dent","stain"]
NC = 7

# ---------------------------------------------------------------------------
# Dataset — tile + point → Gaussian heatmap target
# ---------------------------------------------------------------------------

class TileDataset(Dataset):
    def __init__(self, root: Path, split: str, tile=512, stride=4, train=True,
                 sigma_px=(10,14,12,8,14,8,12)):
        self.items = []  # (img_path, cls, tx, ty)
        img_dir = root/"images"/split
        lbl_dir = root/"labels"/split
        for lp in lbl_dir.glob("*.txt"):
            line = lp.read_text().strip().split()
            if len(line) != 3: continue
            cls = int(line[0]); txn = float(line[1]); tyn = float(line[2])
            ip = img_dir/f"{lp.stem}.jpg"
            if ip.exists():
                self.items.append((ip, cls, txn, tyn))
        self.tile = tile
        self.stride = stride
        self.hm = tile // stride  # heatmap spatial size
        self.train = train
        self.sigma = sigma_px
        norm = T.Normalize(mean=[0.485,0.456,0.406], std=[0.229,0.224,0.225])
        if train:
            self.tf = T.Compose([
                T.ColorJitter(0.2,0.2,0.2,0.03),
                T.ToTensor(), norm])
        else:
            self.tf = T.Compose([T.ToTensor(), norm])

    def __len__(self): return len(self.items)

    def _gaussian(self, cls, cx, cy):
        """Render penalty-reduced gaussian on (NC, hm, hm); cx,cy in heatmap coords."""
        hm = np.zeros((NC, self.hm, self.hm), dtype=np.float32)
        sig = self.sigma[cls] / self.stride
        r = int(3*sig + 1)
        x0,x1 = max(0,int(cx-r)), min(self.hm,int(cx+r+1))
        y0,y1 = max(0,int(cy-r)), min(self.hm,int(cy+r+1))
        if x0>=x1 or y0>=y1: return hm
        xs = np.arange(x0,x1)[None,:]; ys = np.arange(y0,y1)[:,None]
        g = np.exp(-((xs-cx)**2 + (ys-cy)**2)/(2*sig*sig))
        hm[cls, y0:y1, x0:x1] = np.maximum(hm[cls, y0:y1, x0:x1], g)
        return hm

    def __getitem__(self, i):
        ip, cls, txn, tyn = self.items[i]
        img = Image.open(ip).convert("RGB")
        # mild random shift augmentation: jitter the crop point in heatmap space
        cx = txn * self.hm
        cy = tyn * self.hm
        x = self.tf(img)
        hm = self._gaussian(cls, cx, cy)
        return x, torch.from_numpy(hm), cls

# ---------------------------------------------------------------------------
# Model — HRNet backbone (timm) + heatmap head
# ---------------------------------------------------------------------------

class HeatmapNet(nn.Module):
    def __init__(self, backbone="hrnet_w32", stride=4):
        super().__init__()
        import timm
        # features_only gives multi-scale; HRNet highest-res is stride 4
        self.backbone = timm.create_model(backbone, features_only=True, pretrained=True)
        ch = self.backbone.feature_info.channels()[0]  # stride-4 channels
        self.head = nn.Sequential(
            nn.Conv2d(ch, 128, 3, padding=1), nn.BatchNorm2d(128), nn.ReLU(inplace=True),
            nn.Conv2d(128, NC, 1),
        )
        # init final bias so initial sigmoid ~ 0.01 (CenterNet trick)
        self.head[-1].bias.data.fill_(-4.6)

    def forward(self, x):
        feats = self.backbone(x)          # list; [0] = stride-4
        h = self.head(feats[0])
        return h                          # logits (NC, H/4, W/4)

# ---------------------------------------------------------------------------
# Loss — penalty-reduced focal (CenterNet) + class weights
# ---------------------------------------------------------------------------

def neg_loss(pred_logits, gt, cls_w):
    """CenterNet penalty-reduced focal on a sigmoid heatmap."""
    pred = torch.sigmoid(pred_logits).clamp(1e-4, 1-1e-4)
    pos = gt.eq(1).float()
    neg = gt.lt(1).float()
    neg_weights = torch.pow(1-gt, 4)
    pos_loss = torch.log(pred)*torch.pow(1-pred,2)*pos
    neg_loss_ = torch.log(1-pred)*torch.pow(pred,2)*neg_weights*neg
    # per-class weighting
    w = cls_w.view(1,NC,1,1)
    pos_loss = (pos_loss*w).sum()
    neg_loss_ = (neg_loss_*w).sum()
    npos = pos.sum()
    if npos == 0: return -neg_loss_
    return -(pos_loss+neg_loss_)/npos

# ---------------------------------------------------------------------------
# Eval — peak extraction + point-F1
# ---------------------------------------------------------------------------

def extract_peaks(hm, thr=0.2, k=3):
    """hm: (NC,H,W) sigmoid. Return list of (cls,y,x,score) via local-max NMS."""
    pts=[]
    pooled = F.max_pool2d(hm.unsqueeze(0), k, stride=1, padding=k//2)[0]
    keep = (hm==pooled) & (hm>thr)
    idx = keep.nonzero(as_tuple=False)
    for c,y,x in idx.tolist():
        pts.append((c,y,x,float(hm[c,y,x])))
    return pts

def eval_pointF1(model, loader, device, tol_hm=6):
    """Per-class point-F1: tile has 1 GT point; check if a peak of that class lands within tol."""
    model.eval()
    tp=Counter(); fp=Counter(); fn=Counter()
    with torch.no_grad():
        for x,hm_gt,cls in loader:
            x=x.to(device)
            with torch.autocast(device_type="cuda",dtype=torch.bfloat16):
                logit=model(x)
            hm=torch.sigmoid(logit).float().cpu()
            for b in range(x.size(0)):
                c=cls[b].item()
                # GT point = argmax of gt channel c
                gch=hm_gt[b,c]
                gy,gx=(gch==gch.max()).nonzero()[0].tolist() if gch.max()>0 else (None,None)
                peaks=extract_peaks(hm[b])
                # did we hit class c within tol?
                hit=False
                for pc,py,px,sc in peaks:
                    if pc==c and gy is not None and abs(py-gy)<=tol_hm and abs(px-gx)<=tol_hm:
                        hit=True
                    elif pc==c:
                        fp[pc]+=1  # predicted c somewhere else (no GT there in this single-defect tile)
                if hit: tp[c]+=1
                else: fn[c]+=1
    res={}
    f1s=[]
    for c in range(NC):
        p=tp[c]/max(tp[c]+fp[c],1); r=tp[c]/max(tp[c]+fn[c],1)
        f1=2*p*r/max(p+r,1e-9)
        res[CLASSES[c]]={"p":round(p,3),"r":round(r,3),"f1":round(f1,3),"n":tp[c]+fn[c]}
        if tp[c]+fn[c]>=20: f1s.append(f1)
    res["macro_f1"]=round(float(np.mean(f1s)),4) if f1s else 0.0
    return res

# ---------------------------------------------------------------------------
# Train
# ---------------------------------------------------------------------------

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--data",type=Path,default=Path("/workspace/data/tag_v3_tiles"))
    ap.add_argument("--backbone",default="hrnet_w32")
    ap.add_argument("--epochs",type=int,default=40)
    ap.add_argument("--batch",type=int,default=48)
    ap.add_argument("--lr",type=float,default=2e-3)
    ap.add_argument("--out",type=Path,default=Path("/workspace/runs/defect_hm"))
    ap.add_argument("--sample",type=int,default=None,help="overfit-sanity on N tiles")
    args=ap.parse_args()
    args.out.mkdir(parents=True,exist_ok=True)
    device="cuda"

    tr=TileDataset(args.data,"train",train=True)
    va=TileDataset(args.data,"val",train=False)
    if args.sample:
        tr.items=tr.items[:args.sample]; va.items=va.items[:max(50,args.sample//4)]
    print(f"train tiles={len(tr)} val tiles={len(va)}")

    # effective-number class weights (beta=0.9999) from train class counts
    cc=Counter(c for _,c,_,_ in tr.items)
    beta=0.9999
    eff=np.array([(1-beta**max(cc[c],1))/(1-beta) for c in range(NC)])
    w=(1/eff); w=w/w.sum()*NC
    cls_w=torch.tensor(w,dtype=torch.float32,device=device)
    print("class counts:",dict(cc))
    print("class weights:",[round(float(x),2) for x in w])

    model=HeatmapNet(args.backbone).to(device)
    dl_tr=DataLoader(tr,batch_size=args.batch,shuffle=True,num_workers=8,pin_memory=True,drop_last=True)
    dl_va=DataLoader(va,batch_size=args.batch,shuffle=False,num_workers=8,pin_memory=True)

    opt=torch.optim.AdamW(model.parameters(),lr=args.lr,weight_decay=1e-4)
    sched=torch.optim.lr_scheduler.OneCycleLR(opt,max_lr=args.lr,
            total_steps=args.epochs*len(dl_tr),pct_start=0.1)

    best=0.0; log=[]
    for ep in range(args.epochs):
        model.train(); t0=time.time(); tot=0; nb=0
        for x,hm,cls in dl_tr:
            x=x.to(device); hm=hm.to(device)
            with torch.autocast(device_type="cuda",dtype=torch.bfloat16):
                logit=model(x); loss=neg_loss(logit,hm,cls_w)
            opt.zero_grad(); loss.backward(); opt.step(); sched.step()
            tot+=loss.item(); nb+=1
        res=eval_pointF1(model,dl_va,device)
        row={"epoch":ep,"loss":round(tot/max(nb,1),4),"macro_f1":res["macro_f1"],"sec":round(time.time()-t0)}
        log.append({**row,"per_class":res})
        print(f"ep{ep:02d} loss={row['loss']:.4f} val_macroF1={res['macro_f1']:.3f} "
              f"corner={res['corner_wear']['f1']:.2f} scratch={res['scratch']['f1']:.2f} "
              f"dent={res['dent']['f1']:.2f} ({row['sec']}s)")
        if res["macro_f1"]>best:
            best=res["macro_f1"]
            torch.save({"model":model.state_dict(),"args":vars(args)},args.out/"best.pt")
        (args.out/"log.json").write_text(json.dumps(log,indent=2,default=str))
    print(f"\nBest val macro-F1: {best:.4f}. Saved {args.out}/best.pt")


if __name__=="__main__":
    main()
