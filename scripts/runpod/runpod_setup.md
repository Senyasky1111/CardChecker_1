# RunPod / Vast.ai setup for CardChecker v3.2 training

> **Goal**: prepare cloud GPU pod for DINOv3 SSL pretrain (B1) → detector (C2) → severity (D1/D2) → SAM2 (A4). Total budget ~$170-240.

## Choosing a provider

| Provider | Best for | Caveat |
|---|---|---|
| **RunPod community-cloud** (recommended) | one-click pods, spot ~$1.30-1.66/hr H100 80GB | requires payment method, spot pods can be reclaimed |
| RunPod secure-cloud | reliable, on-demand ~$2.50/hr H100 | 2× the cost of community-cloud |
| Vast.ai | even cheaper spot prices ~$1.20/hr | flakier uptime, manual SSH setup |
| Lambda | reliable, hourly fixed | more expensive |

> **Always use community-cloud spot** for our workloads — the cost projections below assume it. Secure-cloud is on-demand and ~2× more expensive. The earlier draft of this doc had on-demand pricing — corrected per Round-4 review.

**Pick RunPod** unless you have specific reason otherwise. The rest of this doc assumes RunPod.

## Account setup (one-time)

1. Create account: https://www.runpod.io/
2. Add credit (start with $50 — enough for 1 pod-day on RTX 4090, or 5 hours on H100)
3. Create persistent storage volume:
   - Name: `cardchecker-vol`
   - Size: **150 GB** (holds dataset + checkpoints + intermediate weights)
   - Type: Network Volume (re-attachable to different pods)
4. Generate RunPod API key (Settings → API Keys) — save it locally:
   ```bash
   # Add to ~/.runpod/config.toml or as env var
   export RUNPOD_API_KEY="rpa_..."
   ```

## Pod templates per phase

### Phase A4: SAM2 bbox refinement
- **GPU**: RTX 4090 24GB ($0.40/hr spot) — sufficient
- **Image**: `runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04`
- **Volume**: attach `cardchecker-vol`
- **Cmd on boot**:
  ```bash
  cd /workspace && \
  git clone https://github.com/Senyasky1111/CardChecker_1.git && \
  cd CardChecker_1 && \
  pip install -r requirements-cloud.txt && \
  pip install sam2 huggingface_hub && \
  python scripts/sam2_refine_bboxes.py --device cuda
  ```
- **Expected**: 4-6 hours, ~$2-3

### Phase B1: DINOv3 SSL pretrain
- **GPU**: H100 80GB community-cloud spot ($1.30-1.66/hr) — needed for ViT-L + multi-crop SSL
- **Image**: `runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04`
- **Volume**: attach `cardchecker-vol`
- **Env vars** (must set in pod): `HF_TOKEN`, `WANDB_API_KEY`, `RUNPOD_AUTO_SHUTDOWN=1`
- **Cmd**: see `scripts/runpod/run_dinov3_ssl.sh`
- **Expected**: 16-20 hours, **~$25-35** (was $40-50 — corrected per validator)
- **Pre-flight**: model is gated. Visit `https://huggingface.co/facebook/dinov3-vitl16-pretrain-lvd1689m` and click "Agree and access repository" before training

### Phase C2: Detector training (DEIMv2 + DINOv3-LoRA)
- **GPU**: H100 80GB ($2.50/hr) — DEIMv2 with DINOv3-L backbone needs >40GB VRAM
- **Image**: same as above
- **Volume**: attach `cardchecker-vol`
- **Cmd**: see `scripts/runpod/run_detector_train.sh`
- **Expected**: 12-15 hours, ~$30-40 (after RF-DETR bake-off)

### Phase D1/D2: Severity classifier training
- **GPU**: A40 48GB ($0.40/hr) — ConvNeXt-V2-Tiny fits easily
- **Cmd**: see `scripts/runpod/run_severity_train.sh`
- **Expected**: 6 hours × 2 (corners + edges in parallel), ~$5-10

## Data sync workflow

### Upload v3 dataset (one-time, ~50-80 GB)

```bash
# Local prep: zip and split
cd /d/CardChecker
tar -czf tag_v3.tar.gz data/tag_v3/

# Upload to RunPod volume via SSH (after pod is up with volume mounted)
# Get pod SSH credentials from RunPod dashboard
scp -P <port> tag_v3.tar.gz root@<pod-ip>:/workspace/data/

# On pod: extract once, reused across pods
ssh -p <port> root@<pod-ip>
cd /workspace/data && tar -xzf tag_v3.tar.gz && rm tag_v3.tar.gz
```

**Alternative** (faster, no upload): RunPod has S3-compatible object storage. Sync data once via `aws s3 cp --recursive` from local to RunPod bucket.

### Download trained weights back

```bash
# After phase completes, models are saved to /workspace/models/
scp -P <port> -r root@<pod-ip>:/workspace/models/dinov3_card_ssl.pt ./models/
scp -P <port> -r root@<pod-ip>:/workspace/models/defect_detector_v1.pt ./models/
```

## Cost monitoring

Set RunPod billing alerts at $50, $100, $200 thresholds. Spot pods can be reclaimed without warning — ALWAYS save checkpoints every epoch to volume.

## Auto-shutdown — use runpodctl, NOT `shutdown`

**CRITICAL**: `sudo shutdown -h now` halts the OS but RunPod keeps billing the pod in "Exited" state for reserved GPU + volume. Use the platform API instead:

```bash
# Each pod has $RUNPOD_POD_ID in env; runpodctl is pre-installed
runpodctl stop pod "$RUNPOD_POD_ID"
```

Templates in `scripts/runpod/run_*.sh` already use this. Don't replace with `shutdown`.

## Troubleshooting

- **Volume not mounting**: check pod region matches volume region
- **CUDA OOM**: drop batch size by half; for ViT-L use `--gradient_checkpointing`
- **HuggingFace gated model**: `huggingface-cli login` with read token before pulling DINOv3 weights
- **Spot pod reclaim**: training scripts MUST checkpoint each epoch + use `--resume` flag
