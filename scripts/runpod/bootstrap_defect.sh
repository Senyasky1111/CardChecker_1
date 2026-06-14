#!/bin/bash
# Defect-training pod bootstrap: pull tile parts from HF, reassemble, extract,
# clone repo, install deps, run 50-tile overfit sanity, then (if OK) full train.
set -eu

cd /workspace
echo "=== [1/6] deps ==="
pip install -q huggingface_hub hf_xet hf_transfer timm 2>&1 | tail -1

echo "=== [2/6] download 10 tile parts from HF ==="
export HF_HUB_ENABLE_HF_TRANSFER=1
python3 - <<'PY'
from huggingface_hub import hf_hub_download
import os
os.makedirs('/workspace/tile_parts', exist_ok=True)
for c in 'abcdefghij':
    name=f'part_a{c}'
    p=hf_hub_download(repo_id='Senyasky1111/cardchecker-v3-staging',
        filename=f'tile_parts/{name}', repo_type='dataset', local_dir='/workspace')
    print('got', name, flush=True)
PY

echo "=== [3/6] reassemble + extract ==="
cat /workspace/tile_parts/part_* > /workspace/_tiles.tar.gz
mkdir -p /workspace/data
tar --no-same-owner -xzf /workspace/_tiles.tar.gz -C /workspace/data
rm -rf /workspace/tile_parts /workspace/_tiles.tar.gz
echo "tiles:"; for s in train val test; do echo -n "  $s: "; ls /workspace/data/tag_v3_tiles/images/$s 2>/dev/null | wc -l; done

echo "=== [4/6] clone repo ==="
if [ -d /workspace/CardChecker ]; then cd /workspace/CardChecker && git pull; else git clone https://github.com/Senyasky1111/CardChecker_1.git /workspace/CardChecker; fi

echo "=== [5/6] fix torch for cuDNN (sam2 left torch 2.12; need 2.4.1+cu124) ==="
python3 -c "import torch;print('torch',torch.__version__,'cuda',torch.cuda.is_available())" || true
pip install -q torch==2.4.1 torchvision==0.19.1 --index-url https://download.pytorch.org/whl/cu124 2>&1 | tail -1
python3 -c "import torch;x=torch.zeros(2,2).cuda();print('GPU OK',x.device)"

echo "=== [6/6] 50-tile OVERFIT SANITY (should reach high macro-F1 fast) ==="
cd /workspace/CardChecker
python3 scripts/train_defect_heatmap.py --data /workspace/data/tag_v3_tiles \
  --sample 50 --epochs 15 --batch 16 --out /workspace/runs/sanity 2>&1 | tee /workspace/sanity.log | tail -25
echo "=== SANITY DONE ==="

# Upload sanity results to HF
python3 - <<'PY'
import os
from huggingface_hub import HfApi, login
login(token=os.environ['HF_TOKEN'])
api=HfApi()
for f in ['/workspace/sanity.log','/workspace/runs/sanity/log.json']:
    if os.path.exists(f):
        api.upload_file(path_or_fileobj=f, path_in_repo=f'results/{os.path.basename(f)}',
            repo_id='Senyasky1111/cardchecker-v3-staging', repo_type='dataset', commit_message='sanity result')
        print('uploaded', f, flush=True)
PY
echo "=== SANITY RESULTS ON HF ==="

# Gate full training on sanity passing (overfit should reach high macro-F1)
SANITY_F1=$(python3 -c "import json; d=json.load(open('/workspace/runs/sanity/log.json')); print(max(r['macro_f1'] for r in d))" 2>/dev/null || echo 0)
echo "=== sanity best macro_f1 = $SANITY_F1 ==="

if python3 -c "import sys; sys.exit(0 if float('$SANITY_F1')>0.5 else 1)"; then
  echo "=== SANITY PASSED -> FULL TRAINING ==="
  python3 scripts/train_defect_heatmap.py --data /workspace/data/tag_v3_tiles \
    --epochs 40 --batch 48 --out /workspace/runs/defect_full 2>&1 | tee /workspace/full.log | tail -40
  python3 - <<'PY'
import os
from huggingface_hub import HfApi, login
login(token=os.environ['HF_TOKEN']); api=HfApi()
for f in ['/workspace/full.log','/workspace/runs/defect_full/log.json','/workspace/runs/defect_full/best.pt']:
    if os.path.exists(f):
        api.upload_file(path_or_fileobj=f, path_in_repo=f'results/{os.path.basename(f)}',
            repo_id='Senyasky1111/cardchecker-v3-staging', repo_type='dataset', commit_message='full train result')
        print('uploaded', f, flush=True)
PY
  echo "=== FULL TRAIN RESULTS ON HF ==="
else
  echo "=== SANITY FAILED (macro_f1<=0.5) — NOT running full train ==="
fi

# Self-stop to avoid idle cost (pod has RUNPOD_POD_ID in env)
echo "=== stopping pod to stop billing ==="
sleep 10
runpodctl stop pod "${RUNPOD_POD_ID:-}" 2>/dev/null || true
