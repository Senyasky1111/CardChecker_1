"""
OCR module for Pokemon card text extraction.

Extracts card name and collector number from a card photo using:
1. OpenCV for card boundary detection and perspective correction
2. EasyOCR for text recognition on cropped regions

The card layout has consistent regions:
- Name: top banner (2-10% height, 5-77% width)
- Collector number: bottom strip (87-97% height)
  - Scarlet & Violet era (2023+): bottom-LEFT
  - Pre-SV era: bottom-RIGHT
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
from PIL import Image

# Canonical card size for perspective correction (matches dataset images)
CARD_W = 600
CARD_H = 825

# Crop regions as fractions of card dimensions
# Tuned for 600x825 images from TCGdex
CROP_NAME = {
    "y_start": 0.012,  # ~10px from top
    "y_end": 0.097,    # ~80px from top
    "x_start": 0.050,  # ~30px from left
    "x_end": 0.770,    # ~462px from left (before HP)
}

# Narrow horizontal bands at the bottom for collector number extraction.
# The number "057/191" is always in the last 10-15% of card height.
# Using narrow bands + 4x upscale gives much better OCR accuracy than
# scanning the full bottom strip (which includes "weakness", "resistance" text).
#
# Strategy: try focused right-bottom crops first (less noise from copyright text),
# then fall back to full-width bands.
CROP_NUMBER_BANDS = [
    # --- Full-width bands (modern cards: SV, SwSh, SM, XY, BW, DP, Platinum, HGSS) ---
    {"y_start": 0.93, "y_end": 0.97, "x_start": 0.0, "x_end": 1.0},   # Most SV-era cards
    {"y_start": 0.95, "y_end": 1.00, "x_start": 0.0, "x_end": 1.0},   # Bottom edge
    {"y_start": 0.87, "y_end": 0.93, "x_start": 0.0, "x_end": 1.0},   # Pre-SV bottom area
    # --- Right-side crops (older cards: Base, Neo, e-Card, EX, Gym) ---
    # Number is always in bottom-right corner on these eras
    {"y_start": 0.93, "y_end": 1.00, "x_start": 0.60, "x_end": 1.0},  # Right bottom corner
    {"y_start": 0.88, "y_end": 0.96, "x_start": 0.55, "x_end": 1.0},  # Right, wider & higher (EX/e-Card/Neo)
    {"y_start": 0.90, "y_end": 0.98, "x_start": 0.65, "x_end": 1.0},  # Tight right corner (Gym/Base)
]

# Regex patterns for collector number
# Matches: "057/191", "57 / 191", "057/191 SSP", "SVI EN 057/191"
_NUMBER_RE = re.compile(r"(\d{1,4})\s*/\s*(\d{1,4})")
_SET_CODE_RE = re.compile(r"\b([A-Z]{2,5})\b")

# Known set codes loaded from _set_abbreviations.json (lazy-loaded)
_KNOWN_SET_CODES: set[str] | None = None

# Known set totals loaded from DB (lazy-loaded) — used to validate OCR'd totals
_KNOWN_SET_TOTALS: set[int] | None = None

# Common OCR digit confusions (bidirectional)
_DIGIT_SUBS: dict[str, list[str]] = {
    "0": ["8", "6", "9"],
    "1": ["7", "4"],
    "2": ["7", "Z"],
    "3": ["8", "5"],
    "4": ["1", "9"],
    "5": ["3", "8", "6"],
    "6": ["0", "8", "5"],
    "7": ["1", "2"],
    "8": ["0", "3", "6"],
    "9": ["0", "4"],
}


def _get_known_set_codes() -> set[str]:
    """Load known printed set codes for validation."""
    global _KNOWN_SET_CODES
    if _KNOWN_SET_CODES is None:
        _KNOWN_SET_CODES = set()
        abbr_path = Path("./data/cardmarket/_set_abbreviations.json")
        if abbr_path.exists():
            try:
                with open(abbr_path, "r", encoding="utf-8") as f:
                    abbrs = json.load(f)
                _KNOWN_SET_CODES = {
                    v.upper() for v in abbrs.values() if v
                }
            except Exception:
                pass
    return _KNOWN_SET_CODES


def _get_known_set_totals() -> set[int]:
    """Load known set card totals from DB for OCR validation.

    Returns a set of all distinct set_total values from cards table
    plus card_count_official from sets table.  Used to validate whether
    an OCR'd total actually belongs to a real Pokemon set.
    """
    global _KNOWN_SET_TOTALS
    if _KNOWN_SET_TOTALS is None:
        _KNOWN_SET_TOTALS = set()
        try:
            import sqlite3

            db = Path("./data/cards.db")
            if db.exists():
                conn = sqlite3.connect(str(db))
                rows = conn.execute(
                    "SELECT DISTINCT set_total FROM cards "
                    "WHERE set_total IS NOT NULL AND set_total > 0"
                ).fetchall()
                _KNOWN_SET_TOTALS = {r[0] for r in rows}
                rows = conn.execute(
                    "SELECT DISTINCT card_count_official FROM sets "
                    "WHERE card_count_official > 0"
                ).fetchall()
                _KNOWN_SET_TOTALS.update(r[0] for r in rows)
                conn.close()
        except Exception:
            pass
    return _KNOWN_SET_TOTALS


def _try_digit_corrections(
    parsed: CollectorNumber, known_totals: set[int]
) -> Optional[CollectorNumber]:
    """Try common OCR digit corrections when total doesn't match known sets.

    Only called when parsed.total is NOT in known_totals.

    Three strategies in order of reliability:
    1. Trim trailing digit from total (OCR merged with adjacent text, e.g. 785 → 78)
    2. Trim leading digit from total (e.g. 785 → 85)
    3. Single-digit substitution in total (e.g. 785 → 185 if 7↔1 confusion)

    Trim strategies are prioritised because on holographic/SAR cards OCR
    commonly reads extra characters from neighbouring text (e.g. "078 SAR" → "0785").

    For each corrected total, also attempts to correct the number part
    to ensure it passes validation (number <= total * 2).
    """
    if not known_totals:
        return None

    # Guard: if total already valid, no correction needed
    if parsed.total in known_totals:
        return None

    t_str = str(parsed.total)
    n_str = str(parsed.number)

    def _try_fix_number(new_t: int) -> Optional[CollectorNumber]:
        """Given a corrected total, find a valid number."""
        # Number already valid with new total?
        if 1 <= parsed.number <= new_t * 2:
            return CollectorNumber(
                number=parsed.number,
                total=new_t,
                set_code=parsed.set_code,
                raw=parsed.raw,
            )
        # Try single-digit corrections on number
        for j, d in enumerate(n_str):
            for r in _DIGIT_SUBS.get(d, []):
                try:
                    new_n = int(n_str[:j] + r + n_str[j + 1 :])
                except ValueError:
                    continue
                if 1 <= new_n <= new_t * 2:
                    return CollectorNumber(
                        number=new_n,
                        total=new_t,
                        set_code=parsed.set_code,
                        raw=parsed.raw,
                    )
        # Try trimming number too (same pattern — extra digit from noise)
        if len(n_str) >= 3:
            for trimmed_n in (parsed.number // 10, parsed.number % (10 ** (len(n_str) - 1))):
                if 1 <= trimmed_n <= new_t * 2:
                    return CollectorNumber(
                        number=trimmed_n,
                        total=new_t,
                        set_code=parsed.set_code,
                        raw=parsed.raw,
                    )
        return None

    # Strategy 1: trim trailing digit (OCR merged "078S" → reads "0785")
    if len(t_str) >= 3:
        trimmed = parsed.total // 10
        if trimmed in known_totals and trimmed > 0:
            result = _try_fix_number(trimmed)
            if result:
                return result

    # Strategy 2: trim leading digit
    if len(t_str) >= 3:
        trimmed = parsed.total % (10 ** (len(t_str) - 1))
        if trimmed in known_totals and trimmed > 0:
            result = _try_fix_number(trimmed)
            if result:
                return result

    # Strategy 3: single-digit substitution in total (last resort)
    for i, digit in enumerate(t_str):
        for replacement in _DIGIT_SUBS.get(digit, []):
            try:
                new_t = int(t_str[:i] + replacement + t_str[i + 1 :])
            except ValueError:
                continue
            if new_t in known_totals and new_t > 0:
                result = _try_fix_number(new_t)
                if result:
                    return result

    return None


def detect_language(text: str) -> str:
    """
    Detect card language from OCR text.

    Returns: 'ja', 'zh-tw', or 'en' (default).

    Japanese: contains Hiragana or Katakana characters.
    Chinese: contains CJK ideographs but no Hiragana/Katakana.
    English: primarily Latin characters.
    """
    if not text:
        return "en"

    has_hiragana = bool(re.search(r"[\u3040-\u309F]", text))
    has_katakana = bool(re.search(r"[\u30A0-\u30FF]", text))
    has_cjk = bool(re.search(r"[\u4E00-\u9FFF\u3400-\u4DBF]", text))

    if has_hiragana or has_katakana:
        return "ja"
    if has_cjk:
        return "zh-tw"  # Default to Traditional Chinese for CJK-only text
    return "en"


@dataclass
class CollectorNumber:
    """Parsed collector number from a Pokemon card."""
    number: int                      # e.g., 57
    total: Optional[int] = None      # e.g., 191
    set_code: Optional[str] = None   # e.g., "SSP"
    raw: str = ""                    # Original OCR text


@dataclass
class CardOCRResult:
    """Result of OCR extraction from a card image."""
    name: Optional[str] = None
    collector_number: Optional[CollectorNumber] = None
    name_confidence: float = 0.0
    number_confidence: float = 0.0
    card_detected: bool = False
    detected_language: str = "en"
    processing_time_ms: float = 0.0


class CardOCR:
    """Extract card name and collector number from a Pokemon card image."""

    def __init__(self, languages: list[str] | None = None):
        self._readers: dict[str, object] = {}
        # EasyOCR can't mix ja + ch_tra in one reader, so we use separate readers
        self._reader_configs = {
            "en_ja": ["en", "ja"],
            "en_ch": ["en", "ch_tra"],
            "en_only": ["en"],  # For number extraction — digits & Latin only
        }

    def _get_reader(self, lang_key: str = "en_ja"):
        """Lazy-load EasyOCR reader (downloads models on first use).

        lang_key: "en_ja" for English+Japanese, "en_ch" for English+Chinese
        """
        if lang_key not in self._readers:
            import easyocr
            langs = self._reader_configs.get(lang_key, ["en", "ja"])
            try:
                self._readers[lang_key] = easyocr.Reader(
                    langs,
                    gpu=False,
                    verbose=False,
                )
            except Exception as e:
                print(f"EasyOCR init error for {lang_key}: {e}")
                # Fallback to English-only
                self._readers[lang_key] = easyocr.Reader(
                    ["en"],
                    gpu=False,
                    verbose=False,
                )
        return self._readers[lang_key]

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def extract(self, image: Image.Image) -> CardOCRResult:
        """
        Extract card name and collector number from a card photo.

        Steps:
        1. Detect card boundary in the photo
        2. Perspective-correct to canonical 600x825
        3. Crop name and collector number regions
        4. Run OCR on each region
        5. Parse results
        """
        t0 = time.time()
        result = CardOCRResult()

        try:
            # Step 1-2: Detect and correct card
            corners, detected = self._detect_card_boundary(image)
            result.card_detected = detected

            if detected:
                card_img = self._perspective_correct(image, corners)
            else:
                # Assume the image IS the card — just resize
                card_img = image.resize((CARD_W, CARD_H), Image.LANCZOS)

            # Step 3-5: Extract text from regions
            result.name, result.name_confidence = self._extract_name(card_img)
            result.collector_number, result.number_confidence = self._extract_collector_number(card_img)

            # Step 6: Detect language from OCR'd name
            if result.name:
                result.detected_language = detect_language(result.name)

        except Exception as e:
            # Never crash — return partial results
            print(f"OCR error: {e}")

        result.processing_time_ms = (time.time() - t0) * 1000
        return result

    # ------------------------------------------------------------------
    # Card boundary detection
    # ------------------------------------------------------------------

    def _detect_card_boundary(
        self, image: Image.Image
    ) -> tuple[np.ndarray, bool]:
        """
        Find the card rectangle in the photo using edge detection.

        Returns (4 corner points, was_card_found).
        If no card found, returns image corners (assume full image is card).
        """
        img = np.array(image.convert("RGB"))
        gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
        h, w = gray.shape

        # Blur to reduce noise
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)

        # Edge detection
        edges = cv2.Canny(blurred, 40, 120)

        # Close gaps in card border
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
        edges = cv2.dilate(edges, kernel, iterations=2)

        # Find contours
        contours, _ = cv2.findContours(
            edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )

        img_area = h * w
        best = None
        best_area = 0

        for cnt in contours:
            area = cv2.contourArea(cnt)
            # Card should be at least 15% of image
            if area < img_area * 0.15:
                continue

            peri = cv2.arcLength(cnt, True)
            approx = cv2.approxPolyDP(cnt, 0.02 * peri, True)

            if len(approx) == 4 and area > best_area:
                # Check aspect ratio (card is ~5:7 = 0.714)
                rect = cv2.minAreaRect(cnt)
                rw, rh = rect[1]
                if rw == 0 or rh == 0:
                    continue
                ratio = min(rw, rh) / max(rw, rh)
                if 0.55 < ratio < 0.85:  # Allow some tolerance
                    best = approx.reshape(4, 2).astype(np.float32)
                    best_area = area

        if best is not None:
            return best, True

        # Fallback: whole image
        corners = np.array(
            [[0, 0], [w, 0], [w, h], [0, h]], dtype=np.float32
        )
        return corners, False

    def _perspective_correct(
        self, image: Image.Image, corners: np.ndarray
    ) -> Image.Image:
        """Warp detected card quadrilateral to a 600x825 rectangle."""
        img = np.array(image.convert("RGB"))

        # Order corners: top-left, top-right, bottom-right, bottom-left
        ordered = self._order_corners(corners)

        dst = np.array(
            [[0, 0], [CARD_W, 0], [CARD_W, CARD_H], [0, CARD_H]],
            dtype=np.float32,
        )
        M = cv2.getPerspectiveTransform(ordered, dst)
        warped = cv2.warpPerspective(img, M, (CARD_W, CARD_H))
        return Image.fromarray(warped)

    @staticmethod
    def _order_corners(pts: np.ndarray) -> np.ndarray:
        """Order 4 points as: top-left, top-right, bottom-right, bottom-left."""
        pts = pts.astype(np.float32)
        # Sort by sum (x+y): smallest = top-left, largest = bottom-right
        s = pts.sum(axis=1)
        # Sort by diff (y-x): smallest = top-right, largest = bottom-left
        d = np.diff(pts, axis=1).flatten()

        ordered = np.zeros((4, 2), dtype=np.float32)
        ordered[0] = pts[np.argmin(s)]  # top-left
        ordered[2] = pts[np.argmax(s)]  # bottom-right
        ordered[1] = pts[np.argmin(d)]  # top-right
        ordered[3] = pts[np.argmax(d)]  # bottom-left
        return ordered

    # ------------------------------------------------------------------
    # Region cropping & preprocessing
    # ------------------------------------------------------------------

    def _crop_region(
        self, card_img: Image.Image, region: dict
    ) -> Image.Image:
        """Crop a region from the card image using fractional coordinates."""
        w, h = card_img.size
        left = int(w * region["x_start"])
        top = int(h * region["y_start"])
        right = int(w * region["x_end"])
        bottom = int(h * region["y_end"])
        return card_img.crop((left, top, right, bottom))

    def _preprocess_for_ocr(self, region: Image.Image) -> np.ndarray:
        """
        Preprocess a cropped region for better OCR accuracy.

        1. Convert to grayscale
        2. Upscale 2x (helps OCR with small text)
        3. Adaptive threshold for binarization
        4. If dark background, invert
        """
        img = np.array(region.convert("L"))  # grayscale

        # Upscale 2x
        h, w = img.shape
        img = cv2.resize(img, (w * 2, h * 2), interpolation=cv2.INTER_CUBIC)

        # Check if dark background (full-art cards)
        mean_val = img.mean()
        if mean_val < 128:
            img = 255 - img

        # Adaptive threshold
        img = cv2.adaptiveThreshold(
            img, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY, 31, 10
        )

        return img

    # ------------------------------------------------------------------
    # Name extraction
    # ------------------------------------------------------------------

    def _extract_name(
        self, card_img: Image.Image
    ) -> tuple[Optional[str], float]:
        """Extract the card name from the top banner region."""
        region = self._crop_region(card_img, CROP_NAME)

        # Use color image upscaled 2x (works better than threshold for names)
        region_np = np.array(region.convert("RGB"))
        h, w = region_np.shape[:2]
        region_np = cv2.resize(
            region_np, (w * 2, h * 2), interpolation=cv2.INTER_CUBIC
        )

        reader = self._get_reader()
        results = reader.readtext(region_np, detail=1, paragraph=False)

        if not results:
            # Try with preprocessed (threshold) version
            preprocessed = self._preprocess_for_ocr(region)
            results = reader.readtext(preprocessed, detail=1, paragraph=False)

        if not results:
            return None, 0.0

        # Sort by Y position (topmost first), then by confidence
        candidates = []
        for bbox, text, conf in results:
            if conf < 0.10:
                continue
            y_pos = bbox[0][1] if isinstance(bbox[0], (list, tuple)) else 0
            candidates.append((y_pos, conf, text))
        candidates.sort(key=lambda x: (x[0], -x[1]))

        # Try each candidate — the card name is typically the topmost text
        # that isn't a stage label or subtitle
        # Noise words that are NOT card names (OCR artifacts from HP, stage labels, etc.)
        _NOISE = {"HP", "hp", "Hp", "hP", "EX", "GX", "ex", "gx", "V", "VMAX", "VSTAR"}
        for y_pos, conf, text in candidates:
            cleaned = self._clean_name(text)
            if cleaned and len(cleaned) >= 2 and cleaned.strip() not in _NOISE:
                return cleaned, conf

        return None, 0.0

    @staticmethod
    def _clean_name(raw: str) -> str:
        """Clean OCR'd card name. Supports EN, JP, and Chinese text."""
        name = raw.strip()
        # Remove common OCR artifacts (EN-only substitutions)
        name = name.replace("|", "l").replace("}", "j")
        # Remove control characters and emoji artifacts, but KEEP:
        # - ASCII printable (\x20-\x7E)
        # - CJK Unified Ideographs (U+4E00-U+9FFF)
        # - CJK Extension A (U+3400-U+4DBF)
        # - CJK Compatibility Ideographs (U+F900-U+FAFF)
        # - Hiragana (U+3040-U+309F)
        # - Katakana (U+30A0-U+30FF)
        # - Katakana Phonetic Extensions (U+31F0-U+31FF)
        # - CJK Symbols and Punctuation (U+3000-U+303F)
        # - Halfwidth/Fullwidth Forms (U+FF00-U+FFEF)
        # - Hangul (U+AC00-U+D7AF) — for Korean cards if needed
        name = re.sub(
            r"[^\x20-\x7E'"
            r"\u3000-\u303F"   # CJK symbols
            r"\u3040-\u309F"   # Hiragana
            r"\u30A0-\u30FF"   # Katakana
            r"\u31F0-\u31FF"   # Katakana extensions
            r"\u3400-\u4DBF"   # CJK Extension A
            r"\u4E00-\u9FFF"   # CJK Unified Ideographs
            r"\uF900-\uFAFF"   # CJK Compatibility
            r"\uFF00-\uFFEF"   # Fullwidth forms
            r"]", "", name
        )
        # Remove trailing HP numbers that may bleed from HP region
        name = re.sub(r"\s+\d{2,3}\s*$", "", name)
        # Remove "HP" if it bleeds in
        name = re.sub(r"\s+HP\s*$", "", name, flags=re.IGNORECASE)
        # Remove leading EN labels (only if text starts with Latin characters)
        if name and name[0].isascii():
            name = re.sub(
                r"^(Basic|BASIG|BASIC|Stage\s*[12]|STAGe?\]?|Supporter|Trainer|Item)\s*",
                "", name, flags=re.IGNORECASE
            )
        # Remove leading JP labels
        name = re.sub(r"^(たね|1進化|2進化|基礎)\s*", "", name)
        # Remove trailing version/number artifacts like ".v.40", "tv.42", " V 120"
        name = re.sub(r"[.\s]*t?[vV]\s*[.\d]*\s*$", "", name)
        # Remove evolution text bleed (EN only)
        name = re.sub(r"^(Evolves\s+from\s+\w+)\s*$", "", name, flags=re.IGNORECASE)
        name = re.sub(r"\s*(Put|Evolves|on the)\s+.*$", "", name, flags=re.IGNORECASE)
        # Remove trailing dots, brackets, and random characters
        name = re.sub(r"[\[\].\s]+$", "", name)
        # Normalize whitespace
        name = " ".join(name.split())
        return name.strip()

    # ------------------------------------------------------------------
    # Collector number extraction
    # ------------------------------------------------------------------

    def _preprocess_clahe(
        self, region: Image.Image, scale: int = 4
    ) -> np.ndarray:
        """
        CLAHE + Otsu preprocessing — best for holographic/SAR/full-art cards.

        1. Convert to grayscale
        2. Upscale by *scale*
        3. CLAHE contrast enhancement (cuts through holographic patterns)
        4. Otsu binarization
        5. Invert if mostly dark
        """
        gray = np.array(region.convert("L"))
        h, w = gray.shape
        gray = cv2.resize(
            gray, (w * scale, h * scale), interpolation=cv2.INTER_CUBIC
        )
        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(gray)
        _, binary = cv2.threshold(
            enhanced, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
        )
        if binary.mean() < 128:
            binary = 255 - binary
        return binary

    def _extract_collector_number(
        self, card_img: Image.Image
    ) -> tuple[Optional[CollectorNumber], float]:
        """
        Extract collector number from the bottom of the card.

        Multi-strategy approach for maximum reliability:
        1. Primary: scan bands with EasyOCR (color + threshold + CLAHE modes)
           — returns IMMEDIATELY if the parsed total matches a known set total
           — otherwise saves as best_unvalidated and keeps scanning
        2. Fallback: wide bottom strip with CLAHE + Otsu
        3. Last resort: digit correction on best_unvalidated result

        Uses English-only reader for number extraction (no JP character noise).
        """
        reader = self._get_reader("en_only")
        known_totals = _get_known_set_totals()

        best_unvalidated: Optional[CollectorNumber] = None
        best_unvalidated_conf: float = 0.0

        # Strategy 1: Band-by-band OCR with multiple preprocessing modes
        # Try scales: 4x for clean images, 6x for blurry/phone photos
        for scale in (4, 6):
            for band in CROP_NUMBER_BANDS:
                region = self._crop_region(card_img, band)

                for mode in ("color", "threshold", "clahe"):
                    if mode == "color":
                        region_np = np.array(region.convert("RGB"))
                        h, w = region_np.shape[:2]
                        region_np = cv2.resize(
                            region_np, (w * scale, h * scale),
                            interpolation=cv2.INTER_CUBIC,
                        )
                    elif mode == "threshold":
                        # Grayscale + adaptive threshold
                        region_np = self._preprocess_for_ocr(region)
                        h, w = region_np.shape[:2]
                        th_scale = max(1, scale // 2)
                        region_np = cv2.resize(
                            region_np, (w * th_scale, h * th_scale),
                            interpolation=cv2.INTER_CUBIC,
                        )
                    else:
                        # CLAHE + Otsu — best for holographic/SAR cards
                        region_np = self._preprocess_clahe(region, scale=scale)

                    results = reader.readtext(region_np, detail=1, paragraph=False)
                    all_text = " ".join(text for _, text, _ in results)
                    avg_conf = (
                        sum(conf for _, _, conf in results) / len(results)
                        if results else 0.0
                    )

                    if mode == "threshold" and avg_conf < 0.25:
                        continue

                    parsed = self._parse_collector_number(all_text)
                    if parsed is not None:
                        # Validated: total matches a known set → accept immediately
                        if known_totals and parsed.total in known_totals:
                            return parsed, avg_conf
                        # Unvalidated: save best, keep scanning
                        if best_unvalidated is None or avg_conf > best_unvalidated_conf:
                            best_unvalidated = parsed
                            best_unvalidated_conf = avg_conf

            # Only try 6x scale if 4x found nothing validated
            if scale == 4:
                continue

        # Strategy 2: Wide bottom strip with CLAHE + Otsu
        # Reads the full bottom 15% at high resolution
        try:
            wide_band = {"y_start": 0.87, "y_end": 1.0, "x_start": 0.0, "x_end": 1.0}
            region = self._crop_region(card_img, wide_band)
            binary = self._preprocess_clahe(region, scale=6)

            results = reader.readtext(binary, detail=1, paragraph=False)
            all_text = " ".join(text for _, text, _ in results)
            parsed = self._parse_collector_number(all_text)
            if parsed is not None:
                avg_conf = (
                    sum(conf for _, _, conf in results) / len(results)
                    if results else 0.0
                )
                if known_totals and parsed.total in known_totals:
                    return parsed, avg_conf
                if best_unvalidated is None or avg_conf > best_unvalidated_conf:
                    best_unvalidated = parsed
                    best_unvalidated_conf = avg_conf
        except Exception:
            pass

        # Strategy 3: Digit correction on best unvalidated result
        if best_unvalidated is not None and known_totals:
            corrected = _try_digit_corrections(best_unvalidated, known_totals)
            if corrected is not None:
                return corrected, best_unvalidated_conf * 0.8

        if best_unvalidated is not None:
            return best_unvalidated, best_unvalidated_conf

        return None, 0.0

    @staticmethod
    def _parse_collector_number(raw: str) -> Optional[CollectorNumber]:
        """
        Parse OCR text into a structured collector number.

        Matches patterns like:
          "057/191"  →  number=57, total=191
          "057/191 SSP"  →  number=57, total=191, set_code="SSP"

        Uses the LAST valid N/N match in the text, since the collector number
        is always the rightmost such pattern (copyright text may contain
        false positives like year ranges "96,98,99").
        """
        # Clean common OCR artifacts before parsing
        cleaned = raw
        # Common OCR substitutions near the number pattern:
        # "o" or "O" → "0" when adjacent to digits (e.g. "1o2/109" → "102/109")
        cleaned = re.sub(r"(?<=\d)[oO](?=\d)", "0", cleaned)
        cleaned = re.sub(r"(?<=\d)[oO](?=/)", "0", cleaned)
        cleaned = re.sub(r"(?<=/)[oO](?=\d)", "0", cleaned)
        # "[01/102" → "101/102", "[0/108" → "100/108" — EasyOCR reads "[" for "1" on old cards
        # Special case: "[0/" likely means "100/" (lost both digits)
        cleaned = re.sub(r"\[0/", "100/", cleaned)
        cleaned = re.sub(r"\[(\d)", r"1\1", cleaned)
        # "l" or "I" → "1" when before digits/slash (e.g. "I02/109" → "102/109")
        cleaned = re.sub(r"(?<!\w)[lI](\d+/\d)", r"1\1", cleaned)
        cleaned = re.sub(r"(\d+/\d+\s*)[lI](?!\w)", r"\g<1>1", cleaned)  # trailing l/I

        # Find ALL matches and pick the last valid one
        matches = list(_NUMBER_RE.finditer(cleaned))
        if not matches:
            return None

        # Try matches from last to first, pick first valid one
        number = 0
        total = 0
        m = None
        for candidate in reversed(matches):
            n = int(candidate.group(1))
            t = int(candidate.group(2))
            # Validate: number >= 1, total >= 1, number <= total * 2,
            # total <= 999 (no Pokemon set has 1000+ cards — prevents OCR
            # artifacts like "768/1650" from being accepted)
            if n >= 1 and t >= 1 and n <= t * 2 and t <= 999:
                number = n
                total = t
                m = candidate
                break

        if m is None:
            return None

        # Look for set code (2-5 uppercase letters)
        set_code = None
        known_codes = _get_known_set_codes()
        code_matches = _SET_CODE_RE.findall(cleaned)
        # Filter out common false positives
        skip = {"HP", "EX", "GX", "EN", "JP", "DE", "FR", "IT", "ES", "PT",
                "RGB", "PNG", "THE", "AND", "FOR"}

        # Strategy 1: Check if any OCR word is a known set code
        for code in code_matches:
            if code in known_codes and code not in skip:
                set_code = code
                break

        # Strategy 2: Check if any known code is a PREFIX of an OCR word
        # (handles OCR artifacts like "SSPEH" when real code is "SSP")
        if set_code is None:
            for code in code_matches:
                if code in skip:
                    continue
                for known in known_codes:
                    if code.startswith(known) and known not in skip and len(known) >= 2:
                        set_code = known
                        break
                if set_code:
                    break

        # Strategy 3: Fallback to first non-skip code (original behavior)
        if set_code is None:
            for code in code_matches:
                if code not in skip and len(code) >= 2:
                    set_code = code
                    break

        return CollectorNumber(
            number=number,
            total=total,
            set_code=set_code,
            raw=raw,
        )
