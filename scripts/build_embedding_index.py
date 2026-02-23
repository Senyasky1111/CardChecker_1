from __future__ import annotations

"""
Build a FAISS index of CLIP embeddings from downloaded card images.

Reads:
  data/cardmarket/cards_with_prices.json
  data/cardmarket/images/{set_id}/{lang}_{tcgdex_id}.jpg   (new structure)
  data/cardmarket/images/*.jpg                             (old flat structure, fallback)

Writes: models/card_index/cards.faiss + metadata.pkl + cards_indexed.json

Usage:
    python scripts/build_embedding_index.py
    python scripts/build_embedding_index.py --batch-size 64   # if you have lots of VRAM
"""

import argparse
import json
import pickle
import re
from pathlib import Path

import faiss
import numpy as np
import torch
from PIL import Image
from tqdm import tqdm
from transformers import CLIPModel, CLIPProcessor

# Paths
DATA_DIR = Path("./data/cardmarket")
IMAGES_DIR = DATA_DIR / "images"
INDEX_DIR = Path("./models/card_index")
INDEX_DIR.mkdir(parents=True, exist_ok=True)

MODEL_NAME = "openai/clip-vit-base-patch32"  # 512-dim embeddings


class CLIPEmbedder:
    """Generate normalised image embeddings via CLIP."""

    def __init__(self, model_name: str = MODEL_NAME):
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"Device: {self.device}")

        print(f"Loading {model_name}...")
        self.model = CLIPModel.from_pretrained(model_name).to(self.device)
        self.processor = CLIPProcessor.from_pretrained(model_name)
        self.model.eval()

        # Probe embedding dimension
        with torch.no_grad():
            dummy = self.processor(
                images=Image.new("RGB", (224, 224)),
                return_tensors="pt",
            )
            pixel_values = dummy["pixel_values"].to(self.device)
            features = self.model.get_image_features(pixel_values=pixel_values)
            if hasattr(features, "shape"):
                self.embedding_dim = features.shape[-1]
            else:
                # Newer transformers may return a dataclass
                self.embedding_dim = features.pooler_output.shape[-1]

        print(f"Embedding dim: {self.embedding_dim}")

    def embed_batch(self, images: list[Image.Image]) -> np.ndarray:
        with torch.no_grad():
            inputs = self.processor(
                images=images,
                return_tensors="pt",
                padding=True,
            )
            pixel_values = inputs["pixel_values"].to(self.device)
            features = self.model.get_image_features(pixel_values=pixel_values)
            if not hasattr(features, "shape"):
                features = features.pooler_output
            features = features / features.norm(dim=-1, keepdim=True)
        return features.cpu().numpy()

    def embed_images(
        self, image_paths: list[Path], batch_size: int = 32
    ) -> np.ndarray:
        all_embeddings: list[np.ndarray] = []
        for i in tqdm(range(0, len(image_paths), batch_size), desc="Embedding"):
            batch_paths = image_paths[i : i + batch_size]
            images: list[Image.Image] = []
            for p in batch_paths:
                try:
                    images.append(Image.open(p).convert("RGB"))
                except Exception as exc:
                    print(f"  Skipping {p}: {exc}")
                    images.append(Image.new("RGB", (224, 224), (128, 128, 128)))
            all_embeddings.append(self.embed_batch(images))
        return np.vstack(all_embeddings)


def load_cards_with_images() -> tuple[list[dict], list[Path]]:
    """Return (cards, image_paths) for all images on disk.

    Handles the new set-based directory structure:
      images/{set_id}/{lang}_{tcgdex_id}.jpg

    Each image variant (different language) becomes a separate entry in the
    FAISS index, all pointing to the same underlying card (for pricing).
    This way a Japanese card photo will match against the Japanese image.
    """
    # Load CardMarket data if available (for price info)
    cm_cards: dict[int, dict] = {}
    cm_file = DATA_DIR / "cards_with_prices.json"
    if cm_file.exists():
        with open(cm_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        cm_cards = {c["id_product"]: c for c in data.get("cards", [])}

    # Load EN match map (tcgdex_id → cm_id_product)
    match_map: dict[str, int] = {}
    match_file = DATA_DIR / "_tcgdex_match_map.json"
    if match_file.exists():
        with open(match_file, "r", encoding="utf-8") as f:
            match_map = json.load(f)

    cards_ok: list[dict] = []
    paths: list[Path] = []

    # Pattern: {lang}_{tcgdex_id}.{jpg,png}
    filename_re = re.compile(r"^([a-z]{2}(?:-[a-z]{2})?)_(.+)\.(jpg|png)$")

    # Scan new structure: images/{set_id}/{lang}_{id}.jpg
    for set_dir in sorted(IMAGES_DIR.iterdir()):
        if not set_dir.is_dir():
            continue
        set_id = set_dir.name

        for img in sorted(list(set_dir.glob("*.jpg")) + list(set_dir.glob("*.png"))):
            if img.stat().st_size == 0:
                continue

            m = filename_re.match(img.name)
            if not m:
                continue

            lang = m.group(1)
            tcgdex_id = m.group(2).replace("_", "-")

            # Try to find CardMarket price data via match map
            cm_id = match_map.get(tcgdex_id)
            if cm_id and cm_id in cm_cards:
                card = dict(cm_cards[cm_id])  # copy to avoid mutating
            else:
                card = {
                    "id_product": f"tcg_{tcgdex_id}",
                    "name": tcgdex_id.rsplit("-", 1)[-1] if "-" in tcgdex_id else tcgdex_id,
                    "expansion_id": 0,
                    "expansion_name": set_id,
                    "price_trend": 0,
                    "price_low": 0,
                }

            # Add image-specific metadata
            card["_image_lang"] = lang
            card["_image_set"] = set_id
            card["_tcgdex_id"] = tcgdex_id

            cards_ok.append(card)
            paths.append(img)

    # Fallback: also scan flat images (old structure)
    for img in sorted(IMAGES_DIR.glob("*.jpg")):
        if img.stat().st_size == 0:
            continue

        stem = img.stem
        if stem.startswith("tcg_"):
            tcgdex_id = stem[4:].replace("_", "-")
            cm_id = match_map.get(tcgdex_id)
            if cm_id and cm_id in cm_cards:
                card = dict(cm_cards[cm_id])
            else:
                card = {
                    "id_product": stem,
                    "name": stem.replace("tcg_", "").replace("_", " "),
                    "expansion_name": "",
                    "price_trend": 0,
                    "price_low": 0,
                }
        else:
            try:
                pid = int(stem)
            except ValueError:
                continue
            if pid in cm_cards:
                card = dict(cm_cards[pid])
            else:
                card = {
                    "id_product": pid,
                    "name": f"Card #{pid}",
                    "expansion_name": "",
                    "price_trend": 0,
                    "price_low": 0,
                }

        card["_image_lang"] = "en"
        card["_image_set"] = "flat"
        cards_ok.append(card)
        paths.append(img)

    total_cm = sum(1 for c in cards_ok if isinstance(c.get("id_product"), int))
    print(f"Images found: {len(cards_ok)} (with CM prices: {total_cm})")

    # Show per-language breakdown
    lang_counts: dict[str, int] = {}
    for c in cards_ok:
        lang = c.get("_image_lang", "?")
        lang_counts[lang] = lang_counts.get(lang, 0) + 1
    for lang, cnt in sorted(lang_counts.items()):
        print(f"  [{lang}] {cnt} images")

    return cards_ok, paths


def deduplicate_cards(
    cards: list[dict], image_paths: list[Path]
) -> tuple[list[dict], list[Path]]:
    """Remove duplicate embeddings using perceptual image hashing.

    The match_map creates many-to-one mappings (e.g. 21 different Pikachu
    cards from different sets all mapped to one id_product).  These are
    NOT duplicates — they have different art.  Grouping by id_product would
    incorrectly remove them.

    True duplicates are images that look identical (same art, different
    metadata).  We detect these with a fast perceptual hash (average hash,
    8x8 = 64-bit) and group by (image_hash, language).

    Within each group we keep the entry with the best metadata:
      1. Integer id_product (CM-matched) preferred over string (tcg_...)
      2. Among ties, prefer newer set_id (lexicographic descending)

    Returns the filtered (cards, image_paths) pair.
    """
    import hashlib
    from collections import defaultdict, Counter

    print("Computing image hashes for deduplication...")
    hashes: list[str] = []
    for p in tqdm(image_paths, desc="Hashing"):
        try:
            img = Image.open(p).convert("L").resize((8, 8), Image.LANCZOS)
            pixels = list(img.getdata())
            avg = sum(pixels) / len(pixels)
            bits = "".join("1" if px >= avg else "0" for px in pixels)
            hashes.append(bits)
        except Exception:
            hashes.append(f"err_{p}")

    groups: dict[tuple, list[int]] = defaultdict(list)
    for i, card in enumerate(cards):
        lang = card.get("_image_lang", "en")
        groups[(hashes[i], lang)].append(i)

    keep_indices: list[int] = []
    duplicates_removed = 0

    for key, indices in groups.items():
        if len(indices) == 1:
            keep_indices.append(indices[0])
            continue

        # Pick best: prefer int id_product (CM-matched), then latest set_id
        def sort_key(idx: int) -> tuple:
            c = cards[idx]
            is_int = isinstance(c.get("id_product"), int)
            set_id = c.get("_image_set", "")
            return (is_int, set_id)

        indices.sort(key=sort_key, reverse=True)
        keep_indices.append(indices[0])
        duplicates_removed += len(indices) - 1

    keep_indices.sort()  # Maintain original order

    deduped_cards = [cards[i] for i in keep_indices]
    deduped_paths = [image_paths[i] for i in keep_indices]

    print(f"Deduplication: {len(cards)} -> {len(deduped_cards)} "
          f"(removed {duplicates_removed} duplicates)")

    # Show stats about what was removed
    if duplicates_removed > 0:
        # Find which id_products had the most duplicates
        pid_dups: Counter = Counter()
        for key, indices in groups.items():
            if len(indices) > 1:
                pid = cards[indices[0]].get("id_product", "?")
                pid_dups[pid] += len(indices) - 1
        worst = pid_dups.most_common(5)
        if worst:
            print("  Top duplicated cards (by identical image hash):")
            for pid, cnt in worst:
                name = next(
                    (c.get("name", "?") for c in cards if c.get("id_product") == pid),
                    "?",
                )
                print(f"    {name} (id={pid}): {cnt} duplicate images removed")

    return deduped_cards, deduped_paths


def build_faiss_index(embeddings: np.ndarray) -> faiss.Index:
    embeddings = embeddings.astype(np.float32)
    faiss.normalize_L2(embeddings)

    dim = embeddings.shape[1]
    n = embeddings.shape[0]
    print(f"Building index: {n} vectors, dim={dim}")

    if n < 100_000:
        index = faiss.IndexFlatIP(dim)
    else:
        n_clusters = min(int(np.sqrt(n)), 256)
        quantizer = faiss.IndexFlatIP(dim)
        index = faiss.IndexIVFFlat(
            quantizer, dim, n_clusters, faiss.METRIC_INNER_PRODUCT
        )
        print(f"Training IVF with {n_clusters} clusters...")
        index.train(embeddings)

    index.add(embeddings)
    print(f"Index contains {index.ntotal} vectors")
    return index


def save_index(
    index: faiss.Index,
    cards: list[dict],
    embedding_dim: int,
) -> None:
    faiss.write_index(index, str(INDEX_DIR / "cards.faiss"))

    # card_ids: list where FAISS position → product identifier
    # cards_by_idx: FAISS position → card data (for search results)
    # cards_by_id: product_id → card data (for /card/{id} API endpoint)
    card_ids = [c["id_product"] for c in cards]
    cards_by_id: dict = {}
    for c in cards:
        pid = c["id_product"]
        if pid not in cards_by_id:
            cards_by_id[pid] = c

    metadata = {
        "embedding_dim": embedding_dim,
        "total_cards": len(cards),
        "model_name": MODEL_NAME,
        "card_ids": card_ids,
        "cards_by_idx": {i: c for i, c in enumerate(cards)},
        "cards_by_id": cards_by_id,
    }
    with open(INDEX_DIR / "metadata.pkl", "wb") as f:
        pickle.dump(metadata, f)

    with open(INDEX_DIR / "cards_indexed.json", "w", encoding="utf-8") as f:
        json.dump(
            {
                "total": len(cards),
                "model": MODEL_NAME,
                "embedding_dim": embedding_dim,
                "cards": cards,
            },
            f,
            indent=2,
            ensure_ascii=False,
        )
    print(f"Index saved to {INDEX_DIR}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build CLIP+FAISS card index")
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--no-dedup", action="store_true",
                        help="Skip deduplication (keep all image variants)")
    args = parser.parse_args()

    print("=" * 60)
    print("Building Card Embedding Index")
    print("=" * 60)

    cards, image_paths = load_cards_with_images()
    if not cards:
        print("No cards with images found. Run the scraper first.")
        return

    if not args.no_dedup:
        cards, image_paths = deduplicate_cards(cards, image_paths)

    embedder = CLIPEmbedder()
    embeddings = embedder.embed_images(image_paths, batch_size=args.batch_size)

    index = build_faiss_index(embeddings)
    save_index(index, cards, embedder.embedding_dim)

    print(f"\nDone — indexed {len(cards)} cards.")


if __name__ == "__main__":
    main()
