"""
Card recognition: CLIP embedding + FAISS nearest-neighbour search + OCR.

Supports three identification modes:
    identify()            - Single CLIP embedding search (fast)
    identify_multi_crop() - Multi-crop voting (more robust)
    identify_hybrid()     - CLIP + OCR hybrid (most accurate)

Usage:
    recognizer = CardRecognizer.load("./models/card_index")
    results = recognizer.identify_hybrid(image, k=5)
"""

from __future__ import annotations

import pickle
from pathlib import Path
from typing import Any, Union

import faiss
import numpy as np
import torch
from PIL import Image
from transformers import CLIPModel, CLIPProcessor

from src.cardmarket_url import card_url


class CardRecognizer:
    """Identify Pokemon cards from photos using a pre-built FAISS index."""

    def __init__(
        self,
        index: faiss.Index,
        metadata: dict,
        model: CLIPModel,
        processor: CLIPProcessor,
        device: str = "cpu",
    ) -> None:
        self.index = index
        self.metadata = metadata
        self.model = model
        self.processor = processor
        self.device = device

        self.card_ids: list = metadata["card_ids"]

        # cards_by_idx: FAISS position → card data (for search)
        # cards_by_id:  product ID → card data  (for /card/{id} endpoint)
        self.cards_by_idx: dict[int, dict] = metadata.get("cards_by_idx", {})
        self.cards_by_id: dict[Any, dict] = metadata.get("cards_by_id", {})

        # Backward compatibility with older metadata format
        if not self.cards_by_idx and "cards" in metadata:
            old_cards = metadata["cards"]
            # Old format: {product_id: card_data}
            if old_cards:
                first_key = next(iter(old_cards))
                if isinstance(first_key, int) and first_key < len(self.card_ids):
                    # Keyed by FAISS index
                    self.cards_by_idx = old_cards
                else:
                    # Keyed by product ID
                    self.cards_by_id = old_cards
                    self.cards_by_idx = {
                        i: old_cards.get(cid, {})
                        for i, cid in enumerate(self.card_ids)
                    }

        # Lazy-initialized OCR and text index (loaded on first hybrid call)
        self._ocr = None
        self._text_index = None

    def _build_number_lookup(self) -> None:
        """Build collector_number → [faiss_indices] mapping from metadata.

        Parses collector number from _tcgdex_id (e.g. 'sv08-228' → 228)
        since _printed_number may be None in older metadata.
        """
        from collections import defaultdict
        self._number_to_indices: dict[int, list[int]] = defaultdict(list)
        self._number_lang_to_indices: dict[tuple, list[int]] = defaultdict(list)

        for idx, card in self.cards_by_idx.items():
            # Try _printed_number first, fall back to parsing tcgdex_id
            num = card.get("_printed_number")
            if num is None:
                tcgdex_id = card.get("_tcgdex_id", "")
                if "-" not in tcgdex_id:
                    continue
                num_part = tcgdex_id.rsplit("-", 1)[1]
                try:
                    num = int(num_part)
                except ValueError:
                    continue

            lang = card.get("_image_lang", "en")
            self._number_to_indices[num].append(idx)
            self._number_lang_to_indices[(num, lang)].append(idx)

        print(f"[recognizer] Number lookup: {len(self._number_to_indices)} "
              f"unique numbers, avg {np.mean([len(v) for v in self._number_to_indices.values()]):.0f} cards/number")

    def search_filtered(
        self,
        query_embedding: np.ndarray,
        collector_number: int | None = None,
        language: str | None = None,
        k: int = 5,
    ) -> list[tuple[float, int]]:
        """CLIP search with optional collector-number pre-filtering.

        When a collector number is available, narrows search from 55K to
        ~24-57 candidates using direct embedding comparison instead of
        full FAISS search.

        Returns list of (similarity_score, faiss_index) tuples.
        """
        query = query_embedding.astype(np.float32).reshape(1, -1)
        faiss.normalize_L2(query)

        if collector_number is not None:
            if not hasattr(self, '_number_to_indices'):
                self._build_number_lookup()

            # Get candidate FAISS indices for this number
            if language:
                candidates = self._number_lang_to_indices.get(
                    (collector_number, language), []
                )
                # Broaden if language filter too narrow
                if len(candidates) < 3:
                    candidates = self._number_to_indices.get(collector_number, [])
            else:
                candidates = self._number_to_indices.get(collector_number, [])

            if candidates and len(candidates) < 500:
                # Small candidate set: direct similarity computation (faster than FAISS)
                candidate_embeddings = np.array(
                    [self.index.reconstruct(int(i)) for i in candidates],
                    dtype=np.float32,
                )
                scores = (candidate_embeddings @ query.T).flatten()
                top_k = min(k, len(scores))
                top_indices = np.argsort(scores)[::-1][:top_k]
                return [(float(scores[i]), candidates[i]) for i in top_indices]

        # Fallback: full FAISS search
        scores, indices = self.index.search(query, k * 3)
        return [(float(s), int(i)) for s, i in zip(scores[0], indices[0]) if i >= 0]

    @property
    def ocr(self):
        """Lazy-load OCR engine on first use."""
        if self._ocr is None:
            from src.ocr import CardOCR
            self._ocr = CardOCR()
        return self._ocr

    @property
    def text_index(self):
        """Lazy-load text index on first use."""
        if self._text_index is None:
            from src.text_index import CardTextIndex
            set_abbrevs = CardTextIndex.load_set_abbreviations()
            self._text_index = CardTextIndex(
                cards_by_idx=self.cards_by_idx,
                card_ids=self.card_ids,
                set_abbreviations=set_abbrevs,
            )
        return self._text_index

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def load(cls, index_dir: str, device: str | None = None) -> CardRecognizer:
        """Instantiate from a saved index directory."""
        index_path = Path(index_dir)

        if device is None:
            device = "cuda" if torch.cuda.is_available() else "cpu"

        index = faiss.read_index(str(index_path / "cards.faiss"))

        with open(index_path / "metadata.pkl", "rb") as f:
            metadata = pickle.load(f)

        model_name = metadata.get("model_name", "openai/clip-vit-base-patch32")
        model = CLIPModel.from_pretrained(model_name).to(device)
        # Index was built with the slow (pre-v4.50) image processor.
        # The new fast processor gives slightly different pixel values,
        # causing CLIP embeddings to drift and search accuracy to drop.
        processor = CLIPProcessor.from_pretrained(model_name, use_fast=False)
        model.eval()

        return cls(index, metadata, model, processor, device)

    # ------------------------------------------------------------------
    # Embedding
    # ------------------------------------------------------------------

    def _preprocess_query(self, image: Image.Image) -> Image.Image:
        """Preprocess a query photo to better match clean database renders.

        1. CLAHE contrast enhancement (reduces holographic glare)
        2. Gray-world white balance
        3. Pad to square with white padding (preserves card aspect ratio)
        """
        import cv2

        img_np = np.array(image)

        # 1. CLAHE on L channel (LAB color space)
        lab = cv2.cvtColor(img_np, cv2.COLOR_RGB2LAB)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        lab[:, :, 0] = clahe.apply(lab[:, :, 0])
        img_np = cv2.cvtColor(lab, cv2.COLOR_LAB2RGB)

        # 2. Gray-world white balance
        avg = img_np.mean(axis=(0, 1))
        avg_all = avg.mean()
        scale = np.where(avg > 0, avg_all / avg, 1.0)
        img_np = np.clip(img_np.astype(np.float32) * scale, 0, 255).astype(np.uint8)

        # 3. Pad to square (preserves 600x825 aspect ratio instead of squashing)
        h, w = img_np.shape[:2]
        max_dim = max(h, w)
        padded = np.full((max_dim, max_dim, 3), 255, dtype=np.uint8)
        y_off = (max_dim - h) // 2
        x_off = (max_dim - w) // 2
        padded[y_off:y_off + h, x_off:x_off + w] = img_np

        return Image.fromarray(padded)

    def _embed_image(self, image: Image.Image, preprocess: bool = False) -> np.ndarray:
        if preprocess:
            image = self._preprocess_query(image)
        with torch.no_grad():
            inputs = self.processor(images=image, return_tensors="pt")
            pixel_values = inputs["pixel_values"].to(self.device)
            features = self.model.get_image_features(pixel_values=pixel_values)
            if not hasattr(features, "shape"):
                features = features.pooler_output
            features = features / features.norm(dim=-1, keepdim=True)
        return features.cpu().numpy().flatten()

    # ------------------------------------------------------------------
    # Identification
    # ------------------------------------------------------------------

    def identify(
        self,
        image: Union[Image.Image, np.ndarray, str, Path],
        k: int = 5,
        locale: str = "en",
    ) -> list[dict]:
        """
        Identify a card from an image.

        Parameters
        ----------
        image : PIL Image, ndarray, or path
        k : how many candidates to return
        locale : CardMarket locale for URL generation (en, it, de, fr, ...)

        Returns
        -------
        List of dicts with card info, confidence scores, and CardMarket URLs.
        """
        image = self._to_pil(image)
        embedding = self._embed_image(image)
        results = self._search(embedding, k, locale=locale)
        for r in results:
            r.pop("_faiss_idx", None)
        return results

    def identify_multi_crop(
        self,
        image: Union[Image.Image, np.ndarray, str, Path],
        k: int = 5,
        locale: str = "en",
    ) -> list[dict]:
        """
        Identify with multi-crop voting (original + 90% + 80% centre crops).

        More robust to photos that include background around the card.
        """
        image = self._to_pil(image)
        w, h = image.size

        crops = [
            image,
            image.crop(
                (int(w * 0.05), int(h * 0.05), int(w * 0.95), int(h * 0.95))
            ),
            image.crop(
                (int(w * 0.10), int(h * 0.10), int(w * 0.90), int(h * 0.90))
            ),
        ]

        # Collect candidates from every crop
        aggregated: dict[Any, dict] = {}
        for crop in crops:
            embedding = self._embed_image(crop)
            for hit in self._search(embedding, k, locale=locale):
                cid = hit["id_product"]
                if cid not in aggregated:
                    aggregated[cid] = hit.copy()
                    aggregated[cid]["_votes"] = 1
                    aggregated[cid]["_max_conf"] = hit["confidence"]
                else:
                    aggregated[cid]["_votes"] += 1
                    aggregated[cid]["_max_conf"] = max(
                        aggregated[cid]["_max_conf"], hit["confidence"]
                    )

        # Rank by votes then confidence
        ranked = sorted(
            aggregated.values(),
            key=lambda x: (x["_votes"], x["_max_conf"]),
            reverse=True,
        )

        for r in ranked:
            r["confidence"] = min(r["_max_conf"] * (1 + r["_votes"] * 0.05), 1.0)
            del r["_votes"], r["_max_conf"]

        return ranked[:k]

    def identify_hybrid(
        self,
        image: Union[Image.Image, np.ndarray, str, Path],
        k: int = 5,
        locale: str = "en",
        clip_weight: float = 0.4,
        ocr_weight: float = 0.6,
        clip_k: int = 50,
    ) -> tuple[list[dict], dict]:
        """
        Hybrid identification: CLIP visual matching + OCR text matching.

        Pipeline:
        1. CLIP embedding → FAISS top-50 candidates
        2. OCR → card name + collector number
        3. Text index lookup → OCR-matched candidates
        4. Merge & re-rank using combined scoring

        Returns:
            (results, ocr_info) where ocr_info has debug data.
            Falls back to multi-crop if OCR module is unavailable.
        """
        from src.ocr import CardOCRResult
        from src.text_index import normalize_name

        image = self._to_pil(image)
        ocr_info = {"name": None, "number": None, "confidence": 0.0}

        # --- Step 1: CLIP visual matching ---
        # dedup=False: keep all FAISS matches so OCR can pick the right
        # variant when multiple cards share the same id_product
        embedding = self._embed_image(image)
        clip_candidates = self._search(
            embedding, k=clip_k, locale=locale, dedup=False
        )

        # --- Step 2: OCR extraction ---
        try:
            ocr_result = self.ocr.extract(image)
            if ocr_result.name:
                ocr_info["name"] = ocr_result.name
            if ocr_result.collector_number:
                cn = ocr_result.collector_number
                ocr_info["number"] = f"{cn.number}/{cn.total}" if cn.total else str(cn.number)
                if cn.set_code:
                    ocr_info["number"] += f" {cn.set_code}"
            ocr_info["confidence"] = max(
                ocr_result.name_confidence,
                ocr_result.number_confidence,
            )
        except Exception as e:
            print(f"OCR failed, falling back to CLIP-only: {e}")
            ocr_result = CardOCRResult()

        # --- Step 3: Text index lookup ---
        text_faiss_indices: list[int] = []
        if ocr_result.name or ocr_result.collector_number:
            try:
                text_faiss_indices = self.text_index.lookup_combined(
                    name=ocr_result.name,
                    number=ocr_result.collector_number,
                )
            except Exception as e:
                print(f"Text index lookup failed: {e}")

        # Convert text matches to candidate dicts
        text_candidates = self._faiss_indices_to_results(
            text_faiss_indices, locale
        )

        # --- Step 4: Merge and re-rank ---
        merged = self._merge_and_rank(
            clip_candidates=clip_candidates,
            text_candidates=text_candidates,
            ocr_result=ocr_result,
            clip_weight=clip_weight,
            ocr_weight=ocr_weight,
        )

        return merged[:k], ocr_info

    def _faiss_indices_to_results(
        self, indices: list[int], locale: str
    ) -> list[dict]:
        """Convert a list of FAISS indices to result dicts."""
        results = []
        seen: set = set()
        for idx in indices:
            if idx < 0 or idx >= len(self.card_ids):
                continue
            cid = self.card_ids[idx]
            if cid in seen:
                continue
            seen.add(cid)

            card = self.cards_by_idx.get(idx, {})
            if not card:
                card = self.cards_by_id.get(cid, {})

            cm_url = card_url(card, locale=locale)
            results.append({
                "id_product": cid,
                "name": card.get("name", str(cid)),
                "expansion": card.get("expansion_name", card.get("expansion", "")),
                "confidence": 0.0,  # will be set by merge
                "price_trend": card.get("price_trend", 0),
                "price_low": card.get("price_low", 0),
                "cardmarket_url": cm_url,
            })
        return results

    def _merge_and_rank(
        self,
        clip_candidates: list[dict],
        text_candidates: list[dict],
        ocr_result,
        clip_weight: float,
        ocr_weight: float,
    ) -> list[dict]:
        """Combine CLIP and OCR scores into final ranking."""
        from src.text_index import normalize_name
        from rapidfuzz import fuzz

        # Score all candidates (CLIP + text) without dedup
        all_entries: list[dict] = []

        # Add CLIP candidates (also compute OCR score for each)
        for c in clip_candidates:
            entry = c.copy()
            entry["_clip_score"] = c["confidence"]
            entry["_ocr_score"] = self._compute_ocr_score(c, ocr_result)
            all_entries.append(entry)

        # Score and add text candidates
        clip_faiss_idxs = {c.get("_faiss_idx") for c in clip_candidates}
        for tc in text_candidates:
            if tc.get("_faiss_idx") in clip_faiss_idxs:
                continue  # already scored above
            entry = tc.copy()
            entry["_clip_score"] = 0.0
            entry["_ocr_score"] = self._compute_ocr_score(tc, ocr_result)
            all_entries.append(entry)

        # Compute final scores for all entries
        for c in all_entries:
            clip_s = c["_clip_score"]
            ocr_s = c["_ocr_score"]

            if ocr_s >= 0.8:
                # Very strong OCR match — definitive identification
                c["confidence"] = min(0.99, max(clip_s, 0.5) + ocr_s * 0.4)
            else:
                c["confidence"] = clip_weight * clip_s + ocr_weight * ocr_s

        # Dedup by product_id, keeping the entry with highest confidence
        best_by_pid: dict[Any, dict] = {}
        for entry in all_entries:
            pid = entry["id_product"]
            if pid not in best_by_pid or entry["confidence"] > best_by_pid[pid]["confidence"]:
                best_by_pid[pid] = entry

        # Sort by confidence
        ranked = sorted(
            best_by_pid.values(),
            key=lambda x: x["confidence"],
            reverse=True,
        )

        # Clean internal fields
        for r in ranked:
            r.pop("_clip_score", None)
            r.pop("_ocr_score", None)
            r.pop("_faiss_idx", None)

        return ranked

    def _compute_ocr_score(self, candidate: dict, ocr_result) -> float:
        """Compute how well a candidate matches the OCR result (0.0-1.0).

        Uses _faiss_idx from the candidate to look up per-entry metadata
        (cards_by_idx), which has the correct _printed_number for that
        specific card image — even when multiple tcgdex_ids share the
        same CardMarket id_product.
        """
        from src.text_index import normalize_name
        from rapidfuzz import fuzz

        # Use FAISS-index-specific card data (has correct printed number)
        faiss_idx = candidate.get("_faiss_idx")
        if faiss_idx is not None:
            card = self.cards_by_idx.get(faiss_idx, {})
        else:
            # Fallback to product-id lookup
            product_id = candidate.get("id_product")
            card = self.cards_by_id.get(product_id, {})
            if not card:
                for idx, cid in enumerate(self.card_ids):
                    if cid == product_id:
                        card = self.cards_by_idx.get(idx, {})
                        break

        score = 0.0

        # --- Collector number matching ---
        # Prefer enriched fields, fallback to parsing _tcgdex_id
        card_num = card.get("_printed_number")
        card_code = card.get("_printed_set_code", "")
        card_total = card.get("_printed_total", 0)

        if card_num is None:
            # Fallback: parse from _tcgdex_id
            tcgdex_id = card.get("_tcgdex_id", "")
            if tcgdex_id and "-" in tcgdex_id:
                parts = tcgdex_id.rsplit("-", 1)
                try:
                    card_num = int(parts[1])
                except ValueError:
                    card_num = None
                if not card_code:
                    card_code = self.text_index.get_set_code(parts[0]) or ""

        if ocr_result.collector_number and card_num is not None:
            ocr_num = ocr_result.collector_number.number
            if card_num == ocr_num:
                score += 0.5  # Number match is very strong

                # Set code match makes it definitive
                if (ocr_result.collector_number.set_code and card_code and
                        card_code.upper() == ocr_result.collector_number.set_code.upper()):
                    score += 0.3  # Definitive match

                # Total match adds confidence
                if (ocr_result.collector_number.total and card_total and
                        ocr_result.collector_number.total == card_total):
                    score += 0.1  # Total confirms the set

        # --- Name matching ---
        if ocr_result.name and card.get("name"):
            card_norm = normalize_name(card["name"])
            ocr_norm = normalize_name(ocr_result.name)
            if card_norm and ocr_norm:
                sim = fuzz.ratio(card_norm, ocr_norm) / 100.0
                if sim >= 0.9:
                    score += 0.2 * sim
                elif sim >= 0.7:
                    score += 0.1 * sim

        return min(score, 1.0)

    def get_card(self, id_product: Any) -> dict | None:
        """Lookup card details by product ID."""
        return self.cards_by_id.get(id_product)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _to_pil(image: Union[Image.Image, np.ndarray, str, Path]) -> Image.Image:
        if isinstance(image, (str, Path)):
            return Image.open(image).convert("RGB")
        if isinstance(image, np.ndarray):
            return Image.fromarray(image).convert("RGB")
        return image.convert("RGB")

    def _search(
        self, embedding: np.ndarray, k: int, locale: str = "en",
        *, dedup: bool = True,
    ) -> list[dict]:
        query = embedding.astype(np.float32).reshape(1, -1)
        faiss.normalize_L2(query)

        n_fetch = min(k * 5, 200) if dedup else min(k, 500)
        scores, indices = self.index.search(query, n_fetch)

        results: list[dict] = []
        seen: set = set()

        for score, idx in zip(scores[0], indices[0]):
            if idx < 0:
                continue

            card_id = self.card_ids[idx]

            if dedup:
                # Dedup by product ID (multiple language images map to same card)
                if card_id in seen:
                    continue
                seen.add(card_id)

            # Get card data from index-based or id-based lookup
            card = self.cards_by_idx.get(idx, {})
            if not card:
                card = self.cards_by_id.get(card_id, {})

            # Generate CardMarket URL
            cm_url = card_url(card, locale=locale)

            results.append(
                {
                    "id_product": card_id,
                    "name": card.get("name", str(card_id)),
                    "expansion": card.get("expansion_name", card.get("expansion", "")),
                    "confidence": float(score),
                    "price_trend": card.get("price_trend", 0),
                    "price_low": card.get("price_low", 0),
                    "cardmarket_url": cm_url,
                    "_faiss_idx": int(idx),
                }
            )
            if len(results) >= k:
                break

        return results
