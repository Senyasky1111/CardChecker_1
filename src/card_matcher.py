"""
OCR-first card matching pipeline (multi-language).

Flow:
    Photo → OCR (name + number + language) → SQL lookup → optional CLIP verify → result + price

Supports English, Japanese, and Traditional Chinese cards.
Language detection from OCR text narrows SQL queries for faster, more accurate matching.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image
from rapidfuzz import fuzz

from src.card_detector import get_detector
from src.db import get_connection
from src.ocr import CardOCR, CardOCRResult, CollectorNumber


@dataclass
class MatchResult:
    success: bool = False
    method: str = ""  # "ocr_exact", "ocr_name", "ocr_clip", "clip_only", "ocr_number"
    card: dict = field(default_factory=dict)
    candidates: list[dict] = field(default_factory=list)
    ocr_name: Optional[str] = None
    ocr_number: Optional[str] = None
    detected_language: str = "en"
    confidence: float = 0.0
    processing_time_ms: float = 0.0


# Common SELECT fragment for all card queries
_SELECT_SQL = """
    SELECT c.*, s.name AS set_name, s.abbreviation, s.card_count_official,
           p.trend AS price_trend, p.low AS price_low, p.avg AS price_avg,
           p.foil_trend AS price_foil_trend,
           p.cm_name,
           COALESCE(p.cm_expansion_id, s.cm_expansion_id) AS cm_expansion_id
    FROM cards c
    JOIN sets s ON c.set_id = s.set_id AND s.language = c.language
    LEFT JOIN prices p ON c.cm_id_product = p.cm_id_product
"""


def _row_to_dict(row: sqlite3.Row) -> dict:
    """Convert sqlite3.Row to a plain dict."""
    return dict(row)


def _normalize_name(name: str) -> str:
    """Quick name normalization for matching. Preserves CJK characters."""
    name = re.sub(r"\s*\[.*?\]", "", name)
    name = re.sub(r"\s*\(.*?\)", "", name)
    # Remove punctuation but keep CJK, Latin, digits
    name = re.sub(
        r"[^\w\u3000-\u303F\u3040-\u309F\u30A0-\u30FF\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF\uFF00-\uFFEF]",
        "", name
    )
    return name.lower().strip()


def _lang_priority(card: dict) -> int:
    """Language tiebreaker: prefer JP > EN > TW when scores are equal."""
    lang = card.get("language", "")
    return {"ja": 0, "en": 1, "zh-tw": 2}.get(lang, 9)


class CardMatcher:
    """SQL-based card matching with OCR input (multi-language)."""

    def __init__(self, db_path: str | Path = "data/cards.db", recognizer=None):
        self._db_path = str(db_path)
        self._conn: Optional[sqlite3.Connection] = None
        self._ocr: Optional[CardOCR] = None
        self._detector = None  # Will be created via get_detector()
        self._recognizer = recognizer  # Optional CardRecognizer for CLIP verification

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = get_connection(self._db_path)
        return self._conn

    @property
    def ocr(self) -> CardOCR:
        if self._ocr is None:
            self._ocr = CardOCR()
        return self._ocr

    @property
    def detector(self):
        if self._detector is None:
            self._detector = get_detector("auto")
        return self._detector

    @property
    def card_count(self) -> int:
        return self.conn.execute("SELECT count(*) FROM cards").fetchone()[0]

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def match(self, image: Image.Image) -> MatchResult:
        """
        Identify a card from a photo.

        1. Detect card boundary and perspective-correct
        2. OCR extracts name + collector number + detected language
        3. SQL lookup narrows candidates (filtered by language)
        4. If ambiguous, fuzzy name ranking picks best match
        """
        import time
        t0 = time.time()

        result = MatchResult()

        # Step 0: Detect card and get perspective-corrected image
        detection = self.detector.detect(image)
        card_image = detection.warped if detection.warped else image

        # Step 1: OCR — try warped image first, fall back to original if
        # the warp lost the collector number (common on already-cropped
        # database thumbnails where YOLO corners clip the edges).
        ocr_result = self.ocr.extract(card_image)

        if (
            detection.card_found
            and detection.warped is not None
            and ocr_result.number_confidence < 0.5
        ):
            ocr_original = self.ocr.extract(image)
            if ocr_original.number_confidence > ocr_result.number_confidence:
                ocr_result = ocr_original
                # Keep warped image for CLIP (perspective-corrected is still
                # better for visual matching), but use OCR from original.

        if ocr_result.name:
            result.ocr_name = ocr_result.name
        if ocr_result.collector_number:
            cn = ocr_result.collector_number
            result.ocr_number = f"{cn.number}/{cn.total}" if cn.total else str(cn.number)
        result.detected_language = ocr_result.detected_language

        # Debug logging for troubleshooting misidentifications
        _cn = ocr_result.collector_number
        _name_safe = (ocr_result.name or "").encode("ascii", errors="replace").decode()
        _raw_safe = (_cn.raw[:80] if _cn and _cn.raw else "").encode("ascii", errors="replace").decode()
        print(f"[match] OCR name={_name_safe!r}, "
              f"number={_cn.number if _cn else None}/{_cn.total if _cn else None}, "
              f"set_code={_cn.set_code if _cn else None}, "
              f"num_conf={ocr_result.number_confidence:.2f}, "
              f"lang={ocr_result.detected_language}, "
              f"raw={_raw_safe!r}")

        # Step 2: SQL lookup (language-aware)
        candidates = self._sql_lookup(ocr_result)
        used_clip_fallback = False

        if not candidates:
            # Fallback: CLIP visual search when OCR found nothing.
            # Use the warped (perspective-corrected) image when available —
            # the original photo includes background/sleeve/glare which
            # confuses CLIP embeddings.
            clip_result = self._clip_fallback(card_image)
            if clip_result:
                clip_result = self._refine_clip_with_ocr_number(
                    clip_result, ocr_result
                )
                candidates = clip_result
                used_clip_fallback = True
            else:
                result.processing_time_ms = (time.time() - t0) * 1000
                return result

        # Store all candidates
        result.candidates = candidates

        # Step 3: Pick best
        if used_clip_fallback:
            # CLIP fallback — results already ranked by visual similarity
            result.success = True
            result.method = "clip_only"
            result.card = candidates[0]
            result.confidence = 0.75
        elif len(candidates) == 1:
            # Single candidate — verify with name if we have one.
            # OCR might have read garbage (e.g. Japanese card → Tesseract
            # returns Latin noise) and the SQL match could be wrong.
            name_ok = True
            if ocr_result.name and self._recognizer:
                cand_name = candidates[0].get("name_normalized", "")
                name_score = fuzz.ratio(
                    _normalize_name(ocr_result.name), cand_name
                )
                if name_score < 55:
                    # Name doesn't match — OCR is likely garbage.
                    # Ask CLIP to verify or find the real card.
                    clip_results = self._clip_fallback(card_image)
                    if clip_results:
                        clip_results = self._refine_clip_with_ocr_number(
                            clip_results, ocr_result
                        )
                        print(f"[match] Single-candidate safety net: "
                              f"name score {name_score} < 55, "
                              f"CLIP → {clip_results[0].get('name', '')}")
                        result.success = True
                        result.method = "clip_only"
                        result.card = clip_results[0]
                        result.candidates = clip_results
                        result.confidence = 0.75
                        name_ok = False

            if name_ok:
                result.success = True
                result.method = "ocr_exact"
                result.card = candidates[0]
                result.confidence = 0.95
        elif ocr_result.name:
            # Rank by name similarity
            ranked = self._rank_by_name(candidates, ocr_result.name)
            ocr_norm = _normalize_name(ocr_result.name)
            top_score = fuzz.ratio(ocr_norm, ranked[0].get("name_normalized", ""))

            # Check if multiple candidates have very similar name scores
            # (e.g. same Pokemon from different sets/languages)
            tied = [ranked[0]]
            for c in ranked[1:]:
                s = fuzz.ratio(ocr_norm, c.get("name_normalized", ""))
                if top_score - s <= 5:  # within 5 points = essentially tied
                    tied.append(c)
                else:
                    break

            if len(tied) > 1 and self._recognizer:
                # Multiple candidates with same name — CLIP picks the right printing
                reranked_tied = self._clip_rerank(card_image, tied)
                # Put CLIP-reranked tied candidates first, then the rest
                rest = [c for c in ranked if c not in tied]
                ranked = reranked_tied + rest
                result.method = "ocr_name"
            else:
                result.method = "ocr_name"

            # Safety net: when name match is poor, OCR likely misread the
            # card text entirely (e.g. holographic reflections → garbage).
            # Trust CLIP visual search directly — don't compare against the
            # garbage OCR name since neither SQL nor CLIP results will match it.
            if top_score < 55 and self._recognizer:
                clip_results = self._clip_fallback(card_image)
                if clip_results:
                    clip_results = self._refine_clip_with_ocr_number(
                        clip_results, ocr_result
                    )
                    print(f"[match] CLIP safety net: OCR name score "
                          f"{top_score} < 55, using CLIP visual match "
                          f"({clip_results[0].get('name', '')})")
                    ranked = clip_results
                    result.method = "clip_only"

            result.success = True
            result.card = ranked[0]
            result.candidates = ranked
            result.confidence = min(0.99, 0.7 + top_score / 500)
        else:
            # Multiple candidates, no name — use CLIP visual verification
            # to pick the right card when same number exists across languages
            reranked = self._clip_rerank(card_image, candidates)
            result.success = True
            result.method = "ocr_number"
            result.card = reranked[0]
            result.candidates = reranked

            # Confidence depends on how trustworthy the number-only match is.
            # When OCR name is None (can't read card text), this is risky —
            # the number might be garbage from holographic/SR cards.
            # Low confidence forces frontend to fall back to Gemini Vision AI.
            cn = ocr_result.collector_number
            num_conf = ocr_result.number_confidence
            n_sets = len(set(c.get("set_id", "") for c in candidates))

            if num_conf < 0.5:
                # Very low OCR confidence on number — likely garbage
                result.confidence = 0.35
            elif n_sets > 1:
                # Multiple sets matched — ambiguous
                result.confidence = 0.45
            elif len(candidates) == 1:
                # Single match — moderately trustworthy
                result.confidence = 0.7 if self._recognizer else 0.6
            else:
                # Multiple candidates in same set — use CLIP
                result.confidence = 0.55 if self._recognizer else 0.45

        result.processing_time_ms = (time.time() - t0) * 1000
        return result

    # ------------------------------------------------------------------
    # SQL lookup strategies
    # ------------------------------------------------------------------

    def _sql_lookup(self, ocr: CardOCRResult) -> list[dict]:
        """Find cards based on OCR results, trying most specific query first."""
        cn = ocr.collector_number
        lang = ocr.detected_language

        # Strategy 1: number + set code (most specific)
        if cn and cn.set_code:
            rows = self._query_number_and_code(cn.number, cn.set_code, lang)
            if rows:
                return rows

        # Strategy 2: number + total + language (very specific for JP/TW cards)
        # Only trust language detection if OCR actually read a meaningful name
        _has_real_name = ocr.name and len(ocr.name) > 2
        if cn and cn.total:
            if _has_real_name and lang:
                rows = self._query_number_total_lang(cn.number, cn.total, lang)
                if rows:
                    return rows
            # Fallback: try without language filter (crucial when OCR can't read JP/TW names)
            rows = self._query_number_and_total(cn.number, cn.total)
            if rows:
                return rows

        # Strategy 3: number + name filter (language-aware)
        if cn:
            rows = self._query_number_only(cn.number, lang)
            if rows and ocr.name:
                filtered = self._filter_by_name(rows, ocr.name, threshold=60)
                if filtered:
                    return filtered
            if rows:
                return rows[:20]
            # Fallback: try all languages
            rows = self._query_number_only(cn.number)
            if rows and ocr.name:
                filtered = self._filter_by_name(rows, ocr.name, threshold=60)
                if filtered:
                    return filtered
            if rows:
                return rows[:20]

        # Strategy 4: name only (language-aware)
        if ocr.name:
            rows = self._query_by_name(ocr.name, lang=lang)
            if rows:
                return rows
            # Fallback: try all languages
            return self._query_by_name(ocr.name)

        return []

    def _query_number_and_code(self, number: int, set_code: str, lang: str | None = None) -> list[dict]:
        """Most specific: number + printed set code (e.g. 57 + SSP).
        Results sorted by language priority (JP > EN > TW)."""
        sql = _SELECT_SQL + " WHERE c.collector_number = ? AND UPPER(s.abbreviation) = UPPER(?)"
        params: list = [number, set_code]
        if lang:
            sql += " AND c.language = ?"
            params.append(lang)
        rows = self.conn.execute(sql, params).fetchall()
        result = [_row_to_dict(r) for r in rows]
        result.sort(key=_lang_priority)
        return result

    def _query_number_total_lang(self, number: int, total: int, lang: str) -> list[dict]:
        """Number + total + language — the best strategy for JP/TW cards."""
        rows = self.conn.execute(
            _SELECT_SQL + """
            WHERE c.collector_number = ?
              AND c.set_total = ?
              AND c.language = ?""",
            (number, total, lang),
        ).fetchall()
        return [_row_to_dict(r) for r in rows]

    def _query_number_and_total(self, number: int, total: int) -> list[dict]:
        """Number + total cards in set (e.g. 57/191). Searches all languages.
        Results sorted by language priority (JP > EN > TW)."""
        rows = self.conn.execute(
            _SELECT_SQL + """
            WHERE c.collector_number = ?
              AND (c.set_total = ? OR s.card_count_official = ?)""",
            (number, total, total),
        ).fetchall()
        result = [_row_to_dict(r) for r in rows]
        result.sort(key=_lang_priority)
        return result

    def _query_number_only(self, number: int, lang: str | None = None) -> list[dict]:
        """Just the collector number — broader results."""
        sql = _SELECT_SQL + " WHERE c.collector_number = ?"
        params: list = [number]
        if lang:
            sql += " AND c.language = ?"
            params.append(lang)
        sql += " ORDER BY p.trend DESC NULLS LAST LIMIT 50"
        rows = self.conn.execute(sql, params).fetchall()
        return [_row_to_dict(r) for r in rows]

    def _query_by_name(self, name: str, limit: int = 20, lang: str | None = None) -> list[dict]:
        """Fuzzy name search, optionally filtered by language."""
        normalized = _normalize_name(name)
        if not normalized:
            return []

        lang_clause = " AND c.language = ?" if lang else ""
        base_params: list = [normalized]
        if lang:
            base_params.append(lang)

        # Try exact match first
        rows = self.conn.execute(
            _SELECT_SQL + f"""
            WHERE c.name_normalized = ?{lang_clause}
            ORDER BY p.trend DESC NULLS LAST
            LIMIT ?""",
            base_params + [limit],
        ).fetchall()

        if rows:
            return [_row_to_dict(r) for r in rows]

        # LIKE fallback for partial matches
        like_params: list = [f"%{normalized}%"]
        if lang:
            like_params.append(lang)
        rows = self.conn.execute(
            _SELECT_SQL + f"""
            WHERE c.name_normalized LIKE ?{lang_clause}
            ORDER BY p.trend DESC NULLS LAST
            LIMIT ?""",
            like_params + [limit],
        ).fetchall()
        return [_row_to_dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Ranking helpers
    # ------------------------------------------------------------------

    def _filter_by_name(
        self, candidates: list[dict], ocr_name: str, threshold: float = 60
    ) -> list[dict]:
        """Filter candidates by fuzzy name match. Prefer JP over TW on ties."""
        normalized = _normalize_name(ocr_name)
        scored = []
        for c in candidates:
            score = fuzz.ratio(normalized, c.get("name_normalized", ""))
            if score >= threshold:
                scored.append((score, _lang_priority(c), c))
        scored.sort(key=lambda x: (-x[0], x[1]))
        return [c for _, _, c in scored]

    def _rank_by_name(self, candidates: list[dict], ocr_name: str) -> list[dict]:
        """Rank candidates by name similarity (best first).
        Secondary sort: prefer JP over TW when name scores are equal."""
        normalized = _normalize_name(ocr_name)
        scored = []
        for c in candidates:
            score = fuzz.ratio(normalized, c.get("name_normalized", ""))
            lang_pri = _lang_priority(c)
            scored.append((score, lang_pri, c))
        scored.sort(key=lambda x: (-x[0], x[1]))
        return [c for _, _, c in scored]

    # ------------------------------------------------------------------
    # CLIP fallback & visual verification
    # ------------------------------------------------------------------

    def _clip_fallback(self, query_image: Image.Image, k: int = 5) -> list[dict]:
        """
        Pure CLIP visual search when OCR fails completely.

        Uses FAISS index to find visually similar cards, then fetches
        their full data from SQL for consistent response format.
        """
        if not self._recognizer:
            return []

        try:
            import faiss as _faiss

            emb = self._recognizer._embed_image(query_image)
            query = emb.astype(np.float32).reshape(1, -1)
            _faiss.normalize_L2(query)

            scores, indices = self._recognizer.index.search(query, k * 3)

            seen_tcgdex: set[str] = set()
            results: list[dict] = []

            for score, idx in zip(scores[0], indices[0]):
                if idx < 0:
                    continue
                idx = int(idx)

                # Get tcgdex_id from FAISS metadata
                card_meta = self._recognizer.cards_by_idx.get(idx, {})
                tcgdex_id = card_meta.get("_tcgdex_id", "")
                if not tcgdex_id:
                    continue
                if tcgdex_id in seen_tcgdex:
                    continue
                seen_tcgdex.add(tcgdex_id)

                # Fetch full card data from SQL
                row = self.conn.execute(
                    _SELECT_SQL + " WHERE c.tcgdex_id = ? LIMIT 1",
                    (tcgdex_id,),
                ).fetchone()
                if row:
                    results.append(_row_to_dict(row))

                if len(results) >= k:
                    break

            return results

        except Exception as e:
            print(f"CLIP fallback failed: {e}")
            return []

    def _refine_clip_with_ocr_number(
        self, clip_results: list[dict], ocr: CardOCRResult
    ) -> list[dict]:
        """Combine CLIP visual match with OCR collector number.

        When CLIP finds the right Pokemon but wrong printing (e.g. Ivysaur
        from Mega Evolution instead of Ivysaur from M1L), use the OCR
        number+total to find the exact card.

        Strategy: take the CLIP top match name, search DB for that name +
        OCR number/total.  If found, replace CLIP results.
        """
        cn = ocr.collector_number
        if not cn or not clip_results:
            return clip_results

        clip_name = clip_results[0].get("name_normalized", "")
        if not clip_name:
            return clip_results

        # Search for cards matching CLIP name + OCR number + total.
        # Try both name_normalized and eng_name since CLIP might return
        # an English card name but the target card is JP/TW.
        total_clause = (
            "AND (c.set_total = ? OR s.card_count_official = ?)"
            if cn.total else ""
        )
        base_params_total = [cn.total, cn.total] if cn.total else []

        for name_col in ("c.name_normalized", "LOWER(c.eng_name)"):
            sql = (
                _SELECT_SQL
                + f" WHERE {name_col} = ? AND c.collector_number = ? "
                + total_clause
                + " ORDER BY p.trend DESC NULLS LAST LIMIT 5"
            )
            params: list = [clip_name, cn.number] + base_params_total
            rows = self.conn.execute(sql, params).fetchall()
            if rows:
                refined = [_row_to_dict(r) for r in rows]
                # Prefer JP over TW when visually identical
                refined.sort(key=_lang_priority)
                c = refined[0]
                print(f"[match] CLIP+OCR cross-match: {c.get('name', '')} "
                      f"#{c.get('collector_number', '')}/{c.get('set_total', '')} "
                      f"[{c.get('abbreviation', '')}] ({c.get('language', '')})")
                return refined

        return clip_results

    def _clip_rerank(self, query_image: Image.Image, candidates: list[dict]) -> list[dict]:
        """
        Rerank candidates using CLIP visual similarity.

        Used when multiple candidates match (same name across sets, same number
        across languages, etc.). Compares the uploaded photo against each
        candidate's stored image using CLIP embeddings.

        Falls back to original order if CLIP is not available or images can't be loaded.
        """
        if not self._recognizer or len(candidates) <= 1:
            return candidates

        try:
            # Get CLIP embedding of the uploaded photo
            query_emb = self._recognizer._embed_image(query_image)

            scored = []
            for c in candidates:
                # Try to load the candidate's local image
                local_path = c.get("image_local", "")
                if not local_path:
                    scored.append((0.0, c))
                    continue

                img_path = Path(local_path)
                if not img_path.is_absolute():
                    # Try common base directories
                    for base in [Path("."), Path("data/cardmarket")]:
                        candidate_path = base / local_path
                        if candidate_path.exists():
                            img_path = candidate_path
                            break
                    else:
                        img_path = Path(".") / local_path

                if not img_path.exists():
                    scored.append((0.0, c))
                    continue

                try:
                    cand_image = Image.open(img_path).convert("RGB")
                    cand_emb = self._recognizer._embed_image(cand_image)
                    # Cosine similarity (embeddings are L2-normalized)
                    similarity = float(np.dot(query_emb, cand_emb))
                    scored.append((similarity, c))
                except Exception:
                    scored.append((0.0, c))

            # Sort by CLIP similarity (highest first), prefer JP over TW on ties
            scored.sort(key=lambda x: (-x[0], _lang_priority(x[1])))

            # Only rerank if we actually got meaningful scores
            if scored[0][0] > 0.0:
                return [c for _, c in scored]

        except Exception as e:
            print(f"CLIP rerank failed: {e}")

        return candidates

    # ------------------------------------------------------------------
    # Direct lookup
    # ------------------------------------------------------------------

    def get_card_by_id(self, cm_id_product: int) -> Optional[dict]:
        """Lookup a card by CardMarket product ID."""
        row = self.conn.execute(
            _SELECT_SQL + " WHERE c.cm_id_product = ? LIMIT 1",
            (cm_id_product,),
        ).fetchone()
        return _row_to_dict(row) if row else None
