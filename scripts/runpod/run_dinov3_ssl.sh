#!/bin/bash
# Phase B1 entry: continual DINOv3-ViT-L SSL pretrain on CardChecker scans.
# Target: H100 80GB, ~16h, ~$40-50.
#
# Inputs:
#   /workspace/data/tag_v3/detection/images/{train,val,test}/*.jpg  (~67k images, MAIN+SFX)
# Outputs:
#   /workspace/models/dinov3_card_ssl.pt   (adapted backbone weights)
#   /workspace/runs/dinov3_ssl/             (training logs, intermediate checkpoints)

set -euo pipefail

cd /workspace/CardChecker_1

# Sanity checks
test -d /workspace/data/tag_v3/detection/images || {
    echo "ERROR: dataset not mounted at /workspace/data/tag_v3/"
    exit 1
}
test -f .env || cp .env.example .env

# Install training deps (idempotent)
pip install --quiet \
    'torch>=2.4' \
    'transformers>=4.45' \
    'timm>=1.0.9' \
    'huggingface_hub' \
    'datasets' \
    'wandb' \
    'peft>=0.13'   # LoRA support

# CRITICAL: DINOv3 weights are GATED on HuggingFace.
# Steps:
#   1. Visit https://huggingface.co/facebook/dinov3-vitl16-pretrain-lvd1689m
#   2. Click "Agree and access repository" with your Meta-linked account
#   3. Set HF_TOKEN env var in RunPod pod (Settings → Environment Variables)
test -n "${HF_TOKEN:-}" || { echo "ERROR: HF_TOKEN env var not set"; exit 1; }
huggingface-cli login --token "$HF_TOKEN" --add-to-git-credential

# Verify model is reachable (correct full id, NOT facebook/dinov3-vitl16 which 404s)
python -c "from transformers import AutoModel; AutoModel.from_pretrained('facebook/dinov3-vitl16-pretrain-lvd1689m')" \
    || { echo "ERROR: cannot pull DINOv3 — check HF_TOKEN + gated-access agreement"; exit 1; }

# 50-step sanity probe BEFORE committing 16h of H100 time
python scripts/train_dinov3_ssl.py \
    --backbone facebook/dinov3-vitl16-pretrain-lvd1689m \
    --data /workspace/data/tag_v3/detection/images \
    --output /workspace/runs/dinov3_ssl_probe \
    --image-size 224 \
    --batch-size 96 \
    --grad-accum 6 \
    --gradient-checkpointing \
    --max-steps 50 \
    --amp bf16 \
    --num-workers 8

echo "Sanity probe OK. Starting full SSL pretrain."

# Full SSL pretrain — corrected params per Meta DINOv3 continual-pretrain guidance:
#   - batch 96 (not 256: multi-crop expands tokens ~10×, OOMs on H100 at 256 × ViT-L)
#   - grad-accum 6 → effective batch 576 (similar to original SSL plan)
#   - schedule CONSTANT (not cosine — Meta paper recommends constant for continual)
#   - gradient checkpointing enabled to fit ViT-L
python scripts/train_dinov3_ssl.py \
    --backbone facebook/dinov3-vitl16-pretrain-lvd1689m \
    --data /workspace/data/tag_v3/detection/images \
    --output /workspace/runs/dinov3_ssl \
    --image-size 224 \
    --batch-size 96 \
    --grad-accum 6 \
    --gradient-checkpointing \
    --epochs 20 \
    --lr 1e-5 \
    --weight-decay 0.05 \
    --warmup-epochs 2 \
    --schedule constant \
    --amp bf16 \
    --num-workers 8 \
    --resume-if-exists \
    --save-every-epoch \
    --wandb-project cardchecker-v3 \
    --wandb-name dinov3_ssl_continual

# Persist final weights to models/ for downstream tasks
cp /workspace/runs/dinov3_ssl/final.pt /workspace/models/dinov3_card_ssl.pt

# Auto-stop pod via RunPod API (NOT `sudo shutdown` — that halts OS but RunPod
# keeps billing the pod in "Exited" state for reserved GPU + volume)
if [ "${RUNPOD_AUTO_SHUTDOWN:-0}" = "1" ] && [ -n "${RUNPOD_POD_ID:-}" ]; then
    echo "Stopping pod $RUNPOD_POD_ID via runpodctl in 60s"
    sleep 60
    runpodctl stop pod "$RUNPOD_POD_ID"
fi
