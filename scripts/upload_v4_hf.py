"""Tar + split + upload data/tag_v4_tiles to HF as v4_parts/part_NNN.
Pure Python (consistent paths) — avoids the bash /tmp vs Windows-python mismatch that
made the first upload glob 0 files. Matches bootstrap_exp1.sh which does `cat v4_parts/part_*`.
"""
import os, tarfile, glob, math
from pathlib import Path

REPO = Path("d:/CardChecker")
SRC = REPO / "data/tag_v4_tiles"
WORK = REPO / "data/_v4up"
PART_MB = 480
REPO_ID = "Senyasky1111/cardchecker-v3-staging"

os.environ.setdefault("HF_TOKEN",
    [l.split("=", 1)[1].strip() for l in open(REPO / ".env") if l.startswith("HF_TOKEN")][0])
from huggingface_hub import HfApi, login

WORK.mkdir(parents=True, exist_ok=True)
tar_path = WORK / "v4.tar.gz"

print("[tar] packing", SRC, flush=True)
with tarfile.open(tar_path, "w:gz") as tf:
    tf.add(SRC, arcname="tag_v4_tiles")
sz = tar_path.stat().st_size
print(f"[tar] {sz/1e9:.2f} GB", flush=True)

print("[split] into", PART_MB, "MB parts", flush=True)
for p in glob.glob(str(WORK / "part_*")):
    os.remove(p)
chunk = PART_MB * 1024 * 1024
parts = []
with open(tar_path, "rb") as f:
    i = 0
    while True:
        data = f.read(chunk)
        if not data:
            break
        pp = WORK / f"part_{i:03d}"
        pp.write_bytes(data)
        parts.append(pp); i += 1
print(f"[split] {len(parts)} parts", flush=True)

login(token=os.environ["HF_TOKEN"]); api = HfApi()
for pp in parts:
    api.upload_file(path_or_fileobj=str(pp), path_in_repo=f"v4_parts/{pp.name}",
                    repo_id=REPO_ID, repo_type="dataset", commit_message=f"v4 {pp.name}")
    print("[upload]", pp.name, flush=True)
print(f"[done] uploaded {len(parts)} parts to HF v4_parts/")

# cleanup big local artifacts
os.remove(tar_path)
for pp in parts:
    os.remove(pp)
print("[cleanup] removed local tar+parts")
