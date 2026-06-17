#!/bin/bash
# Wait for the v4 tile build to finish, then tar + split + upload to HF as v4_parts/part_NNN.
# Run as a tracked background task so completion notifies the agent.
set -u
cd /d/CardChecker
HF=$(grep HF_TOKEN .env | cut -d= -f2 | tr -d '\r')

echo "[wait] waiting for v4 tile count to stabilize (build done)..."
prev=-1; stable=0
while true; do
  sleep 90
  cur=$(ls data/tag_v4_tiles/images/*/ 2>/dev/null | grep -c jpg)
  neg=$(find data/tag_v4_tiles/labels -name "*_n*.txt" 2>/dev/null | wc -l)
  if [ "$cur" -eq "$prev" ]; then stable=$((stable+1)); else stable=0; fi
  echo "[wait] tiles=$cur negatives=$neg stable=$stable"
  prev=$cur
  # done when count unchanged for ~7.5 min AND negatives pass ran
  if [ "$stable" -ge 5 ] && [ "$neg" -ge 1000 ]; then break; fi
  # safety: count flat for 20 min even w/o negatives -> stop waiting (build likely died)
  if [ "$stable" -ge 13 ]; then echo "[wait] count flat 20min"; break; fi
done
NEG=$(find data/tag_v4_tiles/labels -name "*_n*.txt" 2>/dev/null | wc -l)
TILES=$(ls data/tag_v4_tiles/images/*/ 2>/dev/null | grep -c jpg)
echo "[wait] done waiting. tiles=$TILES negatives=$NEG"
if [ "$NEG" -lt 1000 ]; then
  echo "[ABORT] too few negatives ($NEG) — build likely incomplete/crashed. Not uploading."
  exit 1
fi

echo "[tar] packing tag_v4_tiles ..."
tar czf /tmp/v4.tar.gz -C data tag_v4_tiles
SZ=$(du -h /tmp/v4.tar.gz | cut -f1); echo "[tar] $SZ"

echo "[split] into 480MB parts ..."
rm -rf /tmp/v4_parts && mkdir -p /tmp/v4_parts
split -b 480m -d -a 3 /tmp/v4.tar.gz /tmp/v4_parts/part_
ls /tmp/v4_parts

echo "[upload] to HF v4_parts/ ..."
HF_TOKEN="$HF" ./venv/Scripts/python.exe - <<'PY'
import os, glob
from huggingface_hub import HfApi, login
login(token=os.environ['HF_TOKEN']); api=HfApi()
parts=sorted(glob.glob('/tmp/v4_parts/part_*'))
for p in parts:
    api.upload_file(path_or_fileobj=p, path_in_repo=f"v4_parts/{os.path.basename(p)}",
        repo_id='Senyasky1111/cardchecker-v3-staging', repo_type='dataset',
        commit_message=f'v4 tiles {os.path.basename(p)}')
    print('uploaded', os.path.basename(p), flush=True)
print('ALL', len(parts), 'PARTS UPLOADED')
PY
rm -f /tmp/v4.tar.gz
echo "[done] v4 uploaded to HF — ready for pod deploy"
