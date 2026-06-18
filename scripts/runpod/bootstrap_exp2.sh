#!/bin/bash
# EXP-1 pod bootstrap: pull v4 tile parts from HF, reassemble, extract, clone repo,
# install deps, run negative-aware OVERFIT SANITY, then (if OK) full single-channel train.
set -eu
cd /workspace
echo "=== [1/6] deps ==="
pip install -q huggingface_hub hf_xet timm 2>&1 | tail -1

echo "=== [2/6] download v4 tile parts from HF ==="
python3 - <<'PY'
from huggingface_hub import hf_hub_download
import os, glob
os.makedirs('/workspace/tile_parts', exist_ok=True)
i = 0
while True:
    name = f'v5_parts/part_{i:03d}'
    try:
        hf_hub_download(repo_id='Senyasky1111/cardchecker-v3-staging', filename=name,
                        repo_type='dataset', local_dir='/workspace')
        print('got', name, flush=True); i += 1
    except Exception:
        break
print('downloaded', i, 'parts')
PY

echo "=== [3/6] reassemble + extract ==="
cat /workspace/v5_parts/part_* > /workspace/_v5.tar.gz
mkdir -p /workspace/data
tar --no-same-owner -xzf /workspace/_v5.tar.gz -C /workspace/data
rm -rf /workspace/v5_parts /workspace/_v5.tar.gz
echo "tiles:"; for s in train val test; do echo -n "  $s: "; ls /workspace/data/tag_v5_tiles/images/$s 2>/dev/null | wc -l; done

echo "=== [4/6] clone repo ==="
if [ -d /workspace/CardChecker ]; then cd /workspace/CardChecker && git pull; else git clone https://github.com/Senyasky1111/CardChecker_1.git /workspace/CardChecker; fi

echo "=== [5/6] torch cu124 (cuDNN) ==="
pip install -q torch==2.4.1 torchvision==0.19.1 --index-url https://download.pytorch.org/whl/cu124 2>&1 | tail -1
python3 -c "import torch;x=torch.zeros(2,2).cuda();print('GPU OK',x.device)"

echo "=== [6/6] negative-aware OVERFIT SANITY (recall up, FP/neg low) ==="
cd /workspace/CardChecker
python3 scripts/train_defect_exp2.py --data /workspace/data/tag_v5_tiles \
  --sample 80 --overfit --epochs 30 --batch 16 --out /workspace/runs/exp2_sanity 2>&1 | tee /workspace/sanity.log | tail -34
echo "=== SANITY DONE ==="

python3 - <<'PY'
import os
from huggingface_hub import HfApi, login
login(token=os.environ['HF_TOKEN']); api=HfApi()
for f in ['/workspace/sanity.log','/workspace/runs/exp2_sanity/log.json']:
    if os.path.exists(f):
        api.upload_file(path_or_fileobj=f, path_in_repo=f'results/exp2_{os.path.basename(f)}',
            repo_id='Senyasky1111/cardchecker-v3-staging', repo_type='dataset', commit_message='exp1 sanity')
PY

# gate: overfit should reach decent F1 (recall up) with low FP/neg
SF1=$(python3 -c "import json;d=json.load(open('/workspace/runs/exp2_sanity/log.json'));print(max(r['f1'] for r in d))" 2>/dev/null || echo 0)
echo "=== sanity best F1 = $SF1 ==="
if python3 -c "import sys;sys.exit(0 if float('$SF1')>0.5 else 1)"; then
  echo "=== SANITY PASSED -> FULL EXP-1 TRAIN ==="
  python3 scripts/train_defect_exp2.py --data /workspace/data/tag_v5_tiles \
    --epochs 25 --batch 48 --out /workspace/runs/exp2_full 2>&1 | tee /workspace/full.log | tail -40
  python3 - <<'PY'
import os
from huggingface_hub import HfApi, login
login(token=os.environ['HF_TOKEN']); api=HfApi()
for f in ['/workspace/full.log','/workspace/runs/exp2_full/log.json','/workspace/runs/exp2_full/best.pt']:
    if os.path.exists(f):
        api.upload_file(path_or_fileobj=f, path_in_repo=f'results/exp2_{os.path.basename(f)}',
            repo_id='Senyasky1111/cardchecker-v3-staging', repo_type='dataset', commit_message='exp1 full')
PY
  echo "=== EXP-1 FULL RESULTS ON HF ==="
else
  echo "=== SANITY FAILED (F1<=0.5) — NOT running full train ==="
fi

echo "=== stopping pod ==="; sleep 10
runpodctl stop pod "${RUNPOD_POD_ID:-}" 2>/dev/null || true
