#!/bin/bash
# Plain (no encryption) download + extract + bootstrap.
# Replaces the broken encrypted-version of this script.
#
# Usage on pod:
#   curl -sL https://raw.githubusercontent.com/Senyasky1111/CardChecker_1/main/scripts/runpod/download_extract_bootstrap.sh | bash

set -eu

echo "=== [1/6] Installing huggingface_hub + hf_xet ==="
pip install -q huggingface_hub hf_xet hf_transfer

echo "=== [2/6] Downloading 35 GB tar.gz from HF (cloud-to-cloud, fast) ==="
cd /workspace
rm -f /workspace/_v3_archive.tar.gz /workspace/_v3_archive.tar.gz.enc
HF_HUB_ENABLE_HF_TRANSFER=1 python3 - <<'PY'
import os
from huggingface_hub import hf_hub_download
path = hf_hub_download(
    repo_id='Senyasky1111/cardchecker-v3-staging',
    filename='_v3_archive.tar.gz',
    repo_type='dataset',
    local_dir='/workspace',
)
print(f'Downloaded to: {path}')
PY

ls -lh /workspace/_v3_archive.tar.gz

echo "=== [3/6] Extracting (3-5 min)... ==="
mkdir -p /workspace/data
# --no-same-owner: ignore tarball's original UID/GID (Windows source) to avoid
# 'Cannot change ownership' warnings + tar failing-exit-status under set -e.
tar --no-same-owner -xzf /workspace/_v3_archive.tar.gz -C /workspace/data
du -sh /workspace/data/tag_v3
rm -f /workspace/_v3_archive.tar.gz

echo "=== [4/6] Cloning CardChecker... ==="
if [ -d /workspace/CardChecker ]; then
    cd /workspace/CardChecker && git pull
else
    git clone https://github.com/Senyasky1111/CardChecker_1.git /workspace/CardChecker
fi

echo "=== [5/6] Running bootstrap (backbone test + SAM2 install)... ==="
bash /workspace/CardChecker/scripts/runpod/bootstrap_pod.sh

echo "=== [6/6] === READY === ==="
