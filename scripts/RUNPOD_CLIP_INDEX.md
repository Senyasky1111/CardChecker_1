# Rebuild the CLIP/FAISS recognition index on RunPod

The local machine can't rebuild the index (66k images, only ~8GB free RAM → swap-thrash).
Run it on a cheap RunPod GPU pod (~10 min, ~$0.5). The pod re-downloads images from the
CDN via `image_url`, so you do NOT upload the multi-GB image folder — only `cards.db` + code.

## What the index is
- Output: `models/card_index/{cards.faiss, metadata.pkl, cards_indexed.json}`
- Model: `openai/clip-vit-large-patch14` (768-dim). Used as the L5 visual fallback in `/identify-v2`
  (primary path is OCR+SQL, which already recognizes the new cards without this).

## Steps

1. **Launch a pod**: RTX 4090 or A40, template with PyTorch + CUDA. ~50GB disk.

2. **Get code + DB onto the pod** (from your local machine):
   ```bash
   # copy the repo code (src/, scripts/) and the current DB
   rsync -avz src scripts requirements.txt <pod>:/workspace/CardChecker/
   rsync -avz data/cards.db data/cards.db-wal data/cards.db-shm <pod>:/workspace/CardChecker/data/
   # OR pull cards.db straight from prod (it's the same 59,125-card DB now):
   #   scp root@89.167.31.124:/opt/cardcheck/data/cards.db <pod>:/workspace/CardChecker/data/
   ```

3. **On the pod**:
   ```bash
   cd /workspace/CardChecker
   pip install torch transformers faiss-cpu pillow imagehash requests tqdm
   export PYTHONUTF8=1
   # download all ~66k images from CDN into data/cardmarket/images/{set}/{lang}_{id}.jpg
   python scripts/download_all_images_from_db.py --workers 32
   # build the index (auto-detects CUDA; keep --no-dedup unless you want the hash pass)
   python scripts/build_embedding_index.py --no-dedup
   ```
   Expect: `models/card_index/cards.faiss` (~130-180MB), `metadata.pkl`, `cards_indexed.json`.

4. **Bring the index back** (to local, then deploy to prod):
   ```bash
   rsync -avz <pod>:/workspace/CardChecker/models/card_index/ models/card_index/
   ```

5. **Deploy to prod** (index is image-baked, NOT bind-mounted — must rebuild the image):
   ```bash
   scp models/card_index/cards.faiss models/card_index/metadata.pkl models/card_index/cards_indexed.json \
       root@89.167.31.124:/opt/cardcheck/models/card_index/
   ssh root@89.167.31.124 'cd /opt/cardcheck && docker compose build api && docker compose up -d api'
   ```
   (`Dockerfile` does `COPY models/card_index/ models/card_index/` — rebuild bakes the new index in.)

6. **Verify**: `/identify-v2` on a photo of a new-set card should still resolve, and CLIP fallback
   now covers new cards. Smoke: the api logs should load the index at startup without errors.

## Notes
- `--no-dedup` avoids the perceptual-hash pass (that's the phase that segfaulted locally under
  memory pressure). On a GPU pod with plenty of RAM you can drop it to enable dedup if desired.
- If you'd rather not touch prod's running image, you can bind-mount `./models` in
  `docker-compose.yml` (like `./data`) so future index updates are a file copy + restart, no rebuild.
