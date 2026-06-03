#!/bin/bash
# CardChecker pod bootstrap: extract dataset, install SAM2, test backbones.
# Run from /workspace via web terminal after `runpodctl receive` brought the tar.gz.
#
# Usage:
#   bash /workspace/CardChecker/scripts/runpod/bootstrap_pod.sh

set -eu

cd /workspace
echo "=== [1/5] Sanity ==="
nvidia-smi --query-gpu=name,memory.total --format=csv
df -h /workspace
test -f /workspace/_v3_archive.tar.gz && echo "Archive found." || { echo "ERROR: archive missing"; exit 1; }

echo ""
echo "=== [2/5] Extracting v3 dataset (~25-30 GB → 34 GB) ==="
mkdir -p /workspace/data
time tar -xzf /workspace/_v3_archive.tar.gz -C /workspace/data
ls /workspace/data/tag_v3/
du -sh /workspace/data/tag_v3
echo "Extracted. Keeping archive for safety (delete with 'rm /workspace/_v3_archive.tar.gz' to reclaim 25 GB later)."

echo ""
echo "=== [3/5] Clone CardChecker code ==="
git clone https://github.com/Senyasky1111/CardChecker_1.git /workspace/CardChecker || (cd /workspace/CardChecker && git pull)

echo ""
echo "=== [4/5] Test DINOv3 backbone access (3-step fallback) ==="
python3 <<'PY'
import sys, traceback
def try_load(label, loader):
    try:
        m = loader()
        n = sum(p.numel() for p in m.parameters())/1e6
        print(f"  ✅ {label}: {n:.0f}M params loaded")
        return True
    except Exception as e:
        print(f"  ❌ {label}: {type(e).__name__}: {str(e)[:200]}")
        return False

print("Trying DINOv3 via torch.hub (Meta CDN, no HF gate)...")
import torch
ok = try_load("DINOv3 ViT-L/16",
              lambda: torch.hub.load('facebookresearch/dinov3', 'dinov3_vitl16', source='github'))
if not ok:
    print("\nTrying DINOv2 via torch.hub (known to work without HF)...")
    ok = try_load("DINOv2 ViT-L/14",
                  lambda: torch.hub.load('facebookresearch/dinov2', 'dinov2_vitl14', source='github'))
if not ok:
    print("\nTrying EVA-02-L from HF (fully open)...")
    from transformers import AutoModel
    ok = try_load("EVA-02-L",
                  lambda: AutoModel.from_pretrained("BAAI/EVA-CLIP-bigE-14"))
print("\n" + ("SUCCESS — proceed with chosen backbone" if ok else "ALL FAILED — need university HF account"))
PY

echo ""
echo "=== [5/5] Install SAM2 ==="
pip install --quiet sam2 hf_xet 2>&1 | tail -3
python3 -c "from sam2.sam2_image_predictor import SAM2ImagePredictor; print('sam2 import OK')"

echo ""
echo "=== READY ==="
echo "Next: bash /workspace/CardChecker/scripts/runpod/run_sam2.sh"
