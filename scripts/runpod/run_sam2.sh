#!/bin/bash
# Run SAM2 bbox refinement on the v3 dataset.
# Prereq: bootstrap_pod.sh completed successfully.
#
# Usage:
#   bash /workspace/CardChecker/scripts/runpod/run_sam2.sh

set -eu

cd /workspace/CardChecker

# Set HF token (already in env from pod deploy)
test -n "${HF_TOKEN:-}" && huggingface-cli login --token "$HF_TOKEN" --add-to-git-credential || true

# Patch script paths to point at /workspace/data instead of d:\CardChecker\data
# (The script's hard-coded Windows paths won't work on Linux pod)
sed -i 's|D:\\CardChecker\\data|/workspace/data|g; s|D:/CardChecker/data|/workspace/data|g' \
    scripts/sam2_refine_bboxes.py 2>/dev/null || true

# Smoke test on 20 cards first (5-10 min)
echo "=== SMOKE TEST (20 cards, should take ~5 min) ==="
python3 scripts/sam2_refine_bboxes.py \
    --src /workspace/data/tag_v3/detection \
    --output /workspace/data/tag_v3/detection_sam2 \
    --sample 20 \
    --device cuda \
    --clean

echo ""
echo "=== Smoke test OK. Starting full refinement (~3-5 hours) ==="

# Full run
nohup python3 scripts/sam2_refine_bboxes.py \
    --src /workspace/data/tag_v3/detection \
    --output /workspace/data/tag_v3/detection_sam2 \
    --device cuda \
    > /workspace/sam2_full.log 2>&1 &

echo "PID: $!"
echo "Monitor: tail -f /workspace/sam2_full.log"
echo ""
echo "When done:"
echo "  ls /workspace/data/tag_v3/detection_sam2/labels/*/ | head"
echo "  ls /workspace/store_listing/v3_sam2_hitl/ | head"
