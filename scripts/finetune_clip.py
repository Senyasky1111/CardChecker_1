"""
Fine-tune CLIP ViT-L/14 image encoder for Pokemon card matching.

Training data:
  - Synthetic pairs from generate_training_pairs.py (data/training_pairs/pairs.jsonl)
  - eBay real photos from scrape_ebay_photos.py (data/training_pairs/ebay/ebay_pairs.jsonl)

Loss: NT-Xent (Normalized Temperature-scaled Cross-Entropy)
Only fine-tunes the vision encoder (text encoder frozen).

After training, rebuild the FAISS index with:
    python scripts/build_embedding_index.py --model models/clip_finetuned

Output: models/clip_finetuned/ (ViT-L/14 weights + processor)

Usage:
    python scripts/finetune_clip.py --epochs 5 --batch-size 32 --lr 1e-5
    python scripts/finetune_clip.py --epochs 3 --batch-size 16  # low VRAM
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from PIL import Image
from torch.utils.data import Dataset, DataLoader
from tqdm import tqdm
from transformers import CLIPModel, CLIPProcessor

MODEL_NAME = "openai/clip-vit-large-patch14"
OUTPUT_DIR = Path("models/clip_finetuned")


class CardPairDataset(Dataset):
    """Dataset of (augmented/real photo, clean database image) pairs."""

    def __init__(self, pairs_files: list[Path], processor: CLIPProcessor, max_pairs: int = 0):
        self.pairs = []
        for jsonl_path in pairs_files:
            if not jsonl_path.exists():
                continue
            with open(jsonl_path, encoding="utf-8") as f:
                for line in f:
                    try:
                        pair = json.loads(line.strip())
                        # Verify both files exist
                        query_path = pair.get("augmented_path") or pair.get("ebay_path")
                        clean_path = pair.get("clean_path", "")
                        if query_path and Path(query_path).exists() and clean_path and Path(clean_path).exists():
                            self.pairs.append(pair)
                    except (json.JSONDecodeError, KeyError):
                        continue

        random.shuffle(self.pairs)
        if max_pairs > 0:
            self.pairs = self.pairs[:max_pairs]

        self.processor = processor
        print(f"Loaded {len(self.pairs)} valid training pairs")

    def __len__(self):
        return len(self.pairs)

    def __getitem__(self, idx):
        pair = self.pairs[idx]
        query_path = pair.get("augmented_path") or pair.get("ebay_path")
        clean_path = pair["clean_path"]

        query_img = Image.open(query_path).convert("RGB")
        clean_img = Image.open(clean_path).convert("RGB")

        query_inputs = self.processor(images=query_img, return_tensors="pt")
        clean_inputs = self.processor(images=clean_img, return_tensors="pt")

        return {
            "query_pixels": query_inputs["pixel_values"].squeeze(0),
            "clean_pixels": clean_inputs["pixel_values"].squeeze(0),
        }


class NTXentLoss(nn.Module):
    """Normalized Temperature-scaled Cross-Entropy Loss (InfoNCE)."""

    def __init__(self, temperature: float = 0.07):
        super().__init__()
        self.temperature = temperature

    def forward(self, query_emb: torch.Tensor, clean_emb: torch.Tensor) -> torch.Tensor:
        query_emb = F.normalize(query_emb, dim=-1)
        clean_emb = F.normalize(clean_emb, dim=-1)

        # Similarity matrix [batch, batch]
        logits = query_emb @ clean_emb.T / self.temperature
        labels = torch.arange(logits.shape[0], device=logits.device)

        # Symmetric loss
        loss = (F.cross_entropy(logits, labels) + F.cross_entropy(logits.T, labels)) / 2
        return loss


def train(args):
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Device: {device}")

    # Load model
    print(f"Loading {MODEL_NAME}...")
    model = CLIPModel.from_pretrained(MODEL_NAME).to(device)
    processor = CLIPProcessor.from_pretrained(MODEL_NAME)

    # Freeze everything except vision encoder
    for param in model.text_model.parameters():
        param.requires_grad = False
    for param in model.text_projection.parameters():
        param.requires_grad = False
    # Also freeze visual_projection to keep embedding space compatible
    for param in model.visual_projection.parameters():
        param.requires_grad = False

    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    total = sum(p.numel() for p in model.parameters())
    print(f"Trainable parameters: {trainable:,} / {total:,} ({trainable/total*100:.1f}%)")

    # Collect training pairs
    pairs_files = [
        Path("data/training_pairs/pairs.jsonl"),
        Path("data/training_pairs/ebay/ebay_pairs.jsonl"),
    ]

    dataset = CardPairDataset(pairs_files, processor, max_pairs=args.max_pairs)
    if len(dataset) == 0:
        print("No training pairs found. Run generate_training_pairs.py and/or scrape_ebay_photos.py first.")
        return

    # Split: 95% train, 5% validation
    val_size = max(1, len(dataset) // 20)
    train_size = len(dataset) - val_size
    train_dataset, val_dataset = torch.utils.data.random_split(dataset, [train_size, val_size])

    train_loader = DataLoader(train_dataset, batch_size=args.batch_size, shuffle=True, num_workers=2)
    val_loader = DataLoader(val_dataset, batch_size=args.batch_size, shuffle=False, num_workers=2)

    # Optimizer
    optimizer = torch.optim.AdamW(
        [p for p in model.vision_model.parameters() if p.requires_grad],
        lr=args.lr,
        weight_decay=0.01,
    )
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=args.epochs)
    criterion = NTXentLoss(temperature=0.07)

    # Training loop
    best_val_loss = float("inf")
    for epoch in range(args.epochs):
        # Train
        model.train()
        total_loss = 0
        for batch in tqdm(train_loader, desc=f"Epoch {epoch + 1}/{args.epochs} [train]"):
            query_pixels = batch["query_pixels"].to(device)
            clean_pixels = batch["clean_pixels"].to(device)

            query_emb = model.get_image_features(pixel_values=query_pixels)
            clean_emb = model.get_image_features(pixel_values=clean_pixels)

            loss = criterion(query_emb, clean_emb)

            optimizer.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()

            total_loss += loss.item()

        avg_train_loss = total_loss / len(train_loader)

        # Validate
        model.eval()
        val_loss = 0
        with torch.no_grad():
            for batch in val_loader:
                query_pixels = batch["query_pixels"].to(device)
                clean_pixels = batch["clean_pixels"].to(device)
                query_emb = model.get_image_features(pixel_values=query_pixels)
                clean_emb = model.get_image_features(pixel_values=clean_pixels)
                val_loss += criterion(query_emb, clean_emb).item()

        avg_val_loss = val_loss / max(len(val_loader), 1)
        scheduler.step()

        print(f"Epoch {epoch + 1}: train_loss={avg_train_loss:.4f}, "
              f"val_loss={avg_val_loss:.4f}, lr={scheduler.get_last_lr()[0]:.2e}")

        # Save best model
        if avg_val_loss < best_val_loss:
            best_val_loss = avg_val_loss
            OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            model.save_pretrained(str(OUTPUT_DIR))
            processor.save_pretrained(str(OUTPUT_DIR))
            print(f"  Saved best model (val_loss={avg_val_loss:.4f})")

    print(f"\nTraining complete. Best val_loss={best_val_loss:.4f}")
    print(f"Model saved to {OUTPUT_DIR}")
    print(f"\nNext steps:")
    print(f"  1. Rebuild index: python scripts/build_embedding_index.py --model {OUTPUT_DIR}")
    print(f"  2. Test: python scripts/test_e2e_pipeline.py")


def main():
    parser = argparse.ArgumentParser(description="Fine-tune CLIP for Pokemon card matching")
    parser.add_argument("--epochs", type=int, default=5)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--lr", type=float, default=1e-5)
    parser.add_argument("--max-pairs", type=int, default=0, help="Limit pairs (0 = all)")
    args = parser.parse_args()
    train(args)


if __name__ == "__main__":
    main()
