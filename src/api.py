"""
FastAPI server for card recognition.

Endpoints:
    GET  /health     - service health & index stats
    POST /identify   - upload a card photo, get top matches with prices + CM links
    GET  /card/{id}  - card details by CardMarket product ID

Usage:
    python src/api.py
    uvicorn src.api:app --reload
"""

from __future__ import annotations

import io
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

import uvicorn
from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from PIL import Image
from pydantic import BaseModel

from src.card_detector import get_detector, visualize_detection
from src.card_matcher import CardMatcher, MatchResult
from src.cardmarket_url import card_url
from src.ocr import CardOCR
from src.recognizer import CardRecognizer
from src.gemini_identify import GeminiIdentifier, GeminiIdentifyResult
from src.gemini_grade import GeminiGrader, GeminiGradeResult

INDEX_PATH = Path("./models/card_index")
DB_PATH = Path("./data/cards.db")
_recognizer: Optional[CardRecognizer] = None
_matcher: Optional[CardMatcher] = None
_detector = None  # CardDetector or YOLOCardDetector via get_detector()
_gemini_identifier: Optional[GeminiIdentifier] = None
_gemini_grader: Optional[GeminiGrader] = None


# ------------------------------------------------------------------
# Lifespan (replaces deprecated @app.on_event)
# ------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _recognizer, _matcher, _detector, _gemini_identifier, _gemini_grader

    # Initialize card detector (auto: tries YOLO, falls back to OpenCV)
    _detector = get_detector("auto")
    print(f"Card detector ready ({type(_detector).__name__}).")

    # Initialize Gemini modules (optional — requires GEMINI_API_KEY env var)
    gemini_key = os.environ.get("GEMINI_API_KEY", "")
    if gemini_key:
        try:
            _gemini_identifier = GeminiIdentifier(api_key=gemini_key)
            _gemini_grader = GeminiGrader(api_key=gemini_key)
            print(f"Gemini modules ready (model: {_gemini_identifier.model}).")
        except Exception as e:
            print(f"Gemini init failed: {e}")
    else:
        print("GEMINI_API_KEY not set, Gemini endpoints disabled.")

    # Load CLIP recognizer (legacy)
    if INDEX_PATH.exists() and (INDEX_PATH / "cards.faiss").exists():
        print("Loading CLIP recognizer...")
        _recognizer = CardRecognizer.load(str(INDEX_PATH))
        print(f"CLIP recognizer ready - {len(_recognizer.card_ids)} cards indexed.")
    else:
        print("CLIP index not found, CLIP recognition disabled.")

    # Load SQL-based matcher (new) — pass recognizer for CLIP verification
    if DB_PATH.exists():
        _matcher = CardMatcher(str(DB_PATH), recognizer=_recognizer)
        print(f"SQL matcher ready - {_matcher.card_count} cards in database.")
    else:
        print("Card database not found, SQL matcher disabled.")

    yield
    _recognizer = None
    _matcher = None
    _detector = None
    _gemini_identifier = None
    _gemini_grader = None


app = FastAPI(
    title="CardChecker API",
    description="Pokemon card recognition and pricing",
    version="0.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ------------------------------------------------------------------
# Response models
# ------------------------------------------------------------------

class CardMatch(BaseModel):
    id_product: Any
    name: str
    expansion: str
    confidence: float
    price_trend: float
    price_low: float
    cardmarket_url: str


class OCRInfo(BaseModel):
    """OCR debug information returned when use_ocr=True."""
    name: Optional[str] = None
    collector_number: Optional[str] = None
    confidence: float = 0.0


class IdentifyResponse(BaseModel):
    success: bool
    processing_time_ms: float
    method: str = "clip"  # "clip", "multi_crop", or "hybrid"
    top_match: Optional[CardMatch] = None
    alternatives: list[CardMatch] = []
    ocr: Optional[OCRInfo] = None


class CardDetailResponse(BaseModel):
    id_product: Any
    name: str
    expansion_name: str
    expansion_id: int
    price_trend: float
    price_low: float
    price_avg: float
    price_foil_trend: float
    cardmarket_url: str
    cardmarket_urls: dict[str, str]


class DetectNumberResponse(BaseModel):
    """Response from /detect-number endpoint."""
    success: bool
    number: Optional[str] = None  # e.g. "45/120"
    card_number: Optional[int] = None  # e.g. 45
    total: Optional[int] = None  # e.g. 120
    set_code: Optional[str] = None  # e.g. "SSP"
    raw_ocr: Optional[str] = None  # raw OCR text from the band
    confidence: float = 0.0
    processing_time_ms: float = 0.0
    debug: Optional[dict] = None  # per-band debug info


class SQLCardMatch(BaseModel):
    """Card match from the SQL-based matcher."""
    tcgdex_id: str = ""
    name: str = ""
    eng_name: str = ""
    language: str = "en"
    set_name: str = ""
    set_id: str = ""
    abbreviation: str = ""
    collector_number: Optional[int] = None
    set_total: Optional[int] = None
    rarity: str = ""
    cm_id_product: Optional[int] = None
    price_trend: Optional[float] = None
    price_low: Optional[float] = None
    price_avg: Optional[float] = None
    price_foil_trend: Optional[float] = None
    image_url: str = ""
    cardmarket_url: str = ""
    # New enriched fields
    tcgplayer_id: Optional[int] = None
    tcgplayer_url: str = ""
    pricecharting_url: str = ""
    price_usd: Optional[float] = None
    price_ebay_usd: Optional[float] = None
    graded_psa10: Optional[float] = None
    graded_psa9: Optional[float] = None
    graded_cgc10: Optional[float] = None
    has_graded: bool = False


class IdentifyV2Response(BaseModel):
    success: bool
    processing_time_ms: float
    method: str = ""  # "ocr_exact", "ocr_name", "ocr_number"
    ocr_name: Optional[str] = None
    ocr_number: Optional[str] = None
    detected_language: str = "en"
    confidence: float = 0.0
    top_match: Optional[SQLCardMatch] = None
    alternatives: list[SQLCardMatch] = []


class HealthResponse(BaseModel):
    status: str
    cards_indexed: int
    cards_in_db: int = 0
    cards_by_language: dict[str, int] = {}
    model: str


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------

def _get_recognizer() -> CardRecognizer:
    if _recognizer is None:
        raise HTTPException(status_code=503, detail="CLIP recognizer not loaded")
    return _recognizer


def _get_matcher() -> CardMatcher:
    if _matcher is None:
        raise HTTPException(status_code=503, detail="Card database not loaded")
    return _matcher


@app.get("/health", response_model=HealthResponse)
async def health():
    cards_indexed = len(_recognizer.card_ids) if _recognizer else 0
    model = _recognizer.metadata.get("model_name", "unknown") if _recognizer else "none"
    cards_in_db = _matcher.card_count if _matcher else 0
    cards_by_lang = {}
    if _matcher:
        rows = _matcher.conn.execute(
            "SELECT language, count(*) as cnt FROM cards GROUP BY language"
        ).fetchall()
        cards_by_lang = {row["language"]: row["cnt"] for row in rows}
    return HealthResponse(
        status="healthy",
        cards_indexed=cards_indexed,
        cards_in_db=cards_in_db,
        cards_by_language=cards_by_lang,
        model=model,
    )


@app.post("/identify", response_model=IdentifyResponse)
async def identify_card(
    file: UploadFile = File(...),
    k: int = Query(default=5, ge=1, le=20),
    use_ocr: bool = Query(default=True, description="Use hybrid CLIP+OCR recognition (more accurate)"),
    multi_crop: bool = Query(default=False, description="Use multi-crop voting (fallback if OCR unavailable)"),
    locale: str = Query(default="en", description="CardMarket locale (en, it, de, fr, es, ...)"),
):
    """Upload a card image (JPEG / PNG) and get recognition results with CardMarket links.

    Recognition methods (in order of accuracy):
    - **use_ocr=True** (default): Hybrid CLIP + OCR — reads card name & number for precise matching
    - **multi_crop=True**: Multi-crop voting — more robust to background noise
    - Both false: Single CLIP embedding — fastest but least accurate
    """
    rec = _get_recognizer()

    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image")

    t0 = time.time()

    contents = await file.read()
    image = Image.open(io.BytesIO(contents)).convert("RGB")

    ocr_response = None
    method = "clip"

    if use_ocr:
        try:
            results, ocr_info = rec.identify_hybrid(image, k=k, locale=locale)
            method = "hybrid"
            ocr_response = OCRInfo(
                name=ocr_info.get("name"),
                collector_number=ocr_info.get("number"),
                confidence=ocr_info.get("confidence", 0.0),
            )
        except Exception as e:
            print(f"Hybrid recognition failed, falling back to multi-crop: {e}")
            results = rec.identify_multi_crop(image, k=k, locale=locale)
            method = "multi_crop"
    elif multi_crop:
        results = rec.identify_multi_crop(image, k=k, locale=locale)
        method = "multi_crop"
    else:
        results = rec.identify(image, k=k, locale=locale)
        method = "clip"

    elapsed_ms = (time.time() - t0) * 1000

    if not results:
        return IdentifyResponse(
            success=False,
            processing_time_ms=elapsed_ms,
            method=method,
        )

    return IdentifyResponse(
        success=True,
        processing_time_ms=elapsed_ms,
        method=method,
        top_match=CardMatch(**results[0]),
        alternatives=[CardMatch(**r) for r in results[1:]],
        ocr=ocr_response,
    )


@app.post("/detect-number", response_model=DetectNumberResponse)
async def detect_number(
    file: UploadFile = File(...),
    debug: bool = Query(default=False, description="Include per-band OCR debug info"),
):
    """Upload a card image and get ONLY the collector number (e.g. '45/120').

    This is a focused endpoint for testing and improving number detection.
    No CLIP/FAISS involved — pure OCR on the card image.
    """
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image")

    t0 = time.time()

    contents = await file.read()
    image = Image.open(io.BytesIO(contents)).convert("RGB")

    ocr = CardOCR()

    # Detect card boundary & perspective-correct
    corners, detected = ocr._detect_card_boundary(image)
    if detected:
        card_img = ocr._perspective_correct(image, corners)
    else:
        card_img = image.resize((600, 825), Image.LANCZOS)

    # Run collector number extraction
    collector_number, confidence = ocr._extract_collector_number(card_img)

    elapsed_ms = (time.time() - t0) * 1000

    debug_info = None
    if debug:
        # Re-run extraction with per-band details
        from src.ocr import CROP_NUMBER_BANDS
        reader = ocr._get_reader()
        import cv2
        import numpy as np
        bands_debug = []
        for i, band in enumerate(CROP_NUMBER_BANDS):
            region = ocr._crop_region(card_img, band)
            region_np = np.array(region.convert("RGB"))
            h, w = region_np.shape[:2]
            region_np = cv2.resize(region_np, (w * 4, h * 4), interpolation=cv2.INTER_CUBIC)
            results = reader.readtext(region_np, detail=1, paragraph=False)
            texts = [(text, round(conf, 3)) for _, text, conf in results]
            all_text = " ".join(t for t, _ in texts)
            bands_debug.append({
                "band": i,
                "region": band,
                "texts": texts,
                "joined": all_text,
            })
        debug_info = {"card_detected": detected, "bands": bands_debug}

    if collector_number is None:
        return DetectNumberResponse(
            success=False,
            processing_time_ms=elapsed_ms,
            confidence=confidence,
            debug=debug_info,
        )

    number_str = f"{collector_number.number}/{collector_number.total}"

    return DetectNumberResponse(
        success=True,
        number=number_str,
        card_number=collector_number.number,
        total=collector_number.total,
        set_code=collector_number.set_code,
        raw_ocr=collector_number.raw,
        confidence=confidence,
        processing_time_ms=elapsed_ms,
        debug=debug_info,
    )


def _build_tcgplayer_url(tcgplayer_id: int | None) -> str:
    """Build TCGPlayer product URL."""
    if not tcgplayer_id:
        return ""
    return f"https://www.tcgplayer.com/product/{tcgplayer_id}"


def _build_pricecharting_url(card: dict) -> str:
    """Build PriceCharting URL by formula."""
    import re
    name = (card.get("eng_name") or card.get("name", "")).strip()
    if not name:
        return ""

    lang = card.get("language", "en")
    set_id = card.get("set_id", "")
    number = card.get("collector_number")

    # Slugify name
    slug = re.sub(r"[^a-zA-Z0-9\s-]", "", name.lower())
    slug = re.sub(r"\s+", "-", slug.strip())

    # Add number if available
    if number:
        slug = f"{slug}-{number}"

    # Game prefix depends on language
    if lang == "ja":
        game = "pokemon-japanese"
    elif lang == "zh-tw":
        game = "pokemon-chinese"
    else:
        game = "pokemon"

    # Set slug
    set_slug = re.sub(r"[^a-zA-Z0-9\s-]", "", set_id.lower())
    set_slug = re.sub(r"\s+", "-", set_slug.strip())

    return f"https://www.pricecharting.com/game/{game}-{set_slug}/{slug}" if set_slug else ""


def _get_enriched_prices(tcgdex_id: str) -> dict:
    """Fetch enriched price data for a card from prices_external."""
    if not _matcher:
        return {}

    conn = _matcher.conn
    result = {}

    # TCGPlayer USD price (latest)
    row = conn.execute("""
        SELECT price_avg FROM prices_external
        WHERE tcgdex_id = ? AND marketplace = 'tcgplayer' AND condition = 'NEAR_MINT'
        ORDER BY snapshot_date DESC LIMIT 1
    """, (tcgdex_id,)).fetchone()
    if row and row["price_avg"]:
        result["price_usd"] = row["price_avg"]

    # eBay USD price (latest NM)
    row = conn.execute("""
        SELECT price_avg FROM prices_external
        WHERE tcgdex_id = ? AND marketplace = 'ebay' AND condition IN ('NEAR_MINT', 'AGGREGATED')
        ORDER BY snapshot_date DESC LIMIT 1
    """, (tcgdex_id,)).fetchone()
    if row and row["price_avg"]:
        result["price_ebay_usd"] = row["price_avg"]

    # Graded prices
    for grade_key, condition in [("graded_psa10", "PSA_10"), ("graded_psa9", "PSA_9"), ("graded_cgc10", "CGC_10")]:
        row = conn.execute("""
            SELECT price_avg FROM prices_external
            WHERE tcgdex_id = ? AND condition = ?
            ORDER BY snapshot_date DESC LIMIT 1
        """, (tcgdex_id, condition)).fetchone()
        if row and row["price_avg"]:
            result[grade_key] = row["price_avg"]

    return result


def _match_to_card(card: dict, locale: str = "en") -> SQLCardMatch:
    """Convert a CardMatcher result dict to an API response model."""
    cm_id = card.get("cm_id_product")

    # Build CardMarket URL using existing cardmarket_url module
    cm_card = {
        "id_product": cm_id,
        "name": card.get("cm_name") or card.get("name", ""),
        "eng_name": card.get("eng_name", ""),
        "language": card.get("language", "en"),
        "cm_expansion_id": card.get("cm_expansion_id"),
        "set_id": card.get("set_id", ""),
        "collector_number": card.get("collector_number"),
    }
    cm_url = card_url(cm_card, locale=locale) if (cm_id or card.get("name")) else ""

    # TCGPlayer ID
    tcgplayer_id = card.get("tcgplayer_id")
    tcgplayer_url = _build_tcgplayer_url(tcgplayer_id)

    # PriceCharting URL
    pc_url = _build_pricecharting_url(card)

    # Enriched prices from prices_external
    tcgdex_id = card.get("tcgdex_id", "")
    enriched = _get_enriched_prices(tcgdex_id) if tcgdex_id else {}

    return SQLCardMatch(
        tcgdex_id=tcgdex_id,
        name=card.get("name", ""),
        eng_name=card.get("eng_name", ""),
        language=card.get("language", "en"),
        set_name=card.get("set_name", ""),
        set_id=card.get("set_id", ""),
        abbreviation=card.get("abbreviation", ""),
        collector_number=card.get("collector_number"),
        set_total=card.get("set_total"),
        rarity=card.get("rarity", ""),
        cm_id_product=cm_id,
        price_trend=card.get("price_trend"),
        price_low=card.get("price_low"),
        price_avg=card.get("price_avg"),
        price_foil_trend=card.get("price_foil_trend"),
        image_url=card.get("image_url", ""),
        cardmarket_url=cm_url,
        tcgplayer_id=tcgplayer_id,
        tcgplayer_url=tcgplayer_url,
        pricecharting_url=pc_url,
        price_usd=enriched.get("price_usd"),
        price_ebay_usd=enriched.get("price_ebay_usd"),
        graded_psa10=enriched.get("graded_psa10"),
        graded_psa9=enriched.get("graded_psa9"),
        graded_cgc10=enriched.get("graded_cgc10"),
        has_graded=card.get("has_graded", 0) == 1,
    )


class DetectCardResponse(BaseModel):
    """Response from /detect-card endpoint."""
    card_found: bool
    method: str  # "contour", "hough", "fallback"
    confidence: float
    corners: list[list[float]]  # 4 corner points [[x,y], ...]
    processing_time_ms: float
    annotated_url: str = ""  # URL to annotated image
    warped_url: str = ""  # URL to warped card image


@app.post("/detect-card")
async def detect_card_endpoint(
    file: UploadFile = File(...),
    visualize: bool = Query(default=True, description="Return annotated image"),
    backend: str = Query(default="auto", description="Detector backend: auto, yolo, opencv"),
):
    """Detect a card in an image and return corners + warped card.

    Returns detection result with optional visualization.
    If visualize=True, also saves annotated + warped images to /static/.
    Use backend parameter to force a specific detector for comparison.
    """
    global _detector

    # Use specific backend if requested, otherwise use the default detector
    if backend == "auto":
        if _detector is None:
            _detector = get_detector("auto")
        detector = _detector
    else:
        try:
            detector = get_detector(backend)
        except (FileNotFoundError, ImportError) as e:
            raise HTTPException(status_code=400, detail=f"Backend '{backend}' unavailable: {e}")

    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image")

    t0 = time.time()

    contents = await file.read()
    image = Image.open(io.BytesIO(contents)).convert("RGB")

    result = detector.detect(image)
    elapsed_ms = (time.time() - t0) * 1000

    response_data = {
        "card_found": result.card_found,
        "method": result.method,
        "confidence": round(float(result.confidence), 4),
        "corners": [[float(x), float(y)] for x, y in result.corners],
        "processing_time_ms": round(elapsed_ms, 1),
        "backend": type(detector).__name__,
    }

    if visualize:
        import hashlib
        file_hash = hashlib.md5(contents[:1024]).hexdigest()[:8]

        # Save annotated (use module-level function)
        annotated = visualize_detection(image, result)
        ann_name = f"detect_{file_hash}_annotated.jpg"
        annotated.save(f"static/{ann_name}")
        response_data["annotated_url"] = f"/static/{ann_name}"

        # Save warped
        if result.warped:
            warp_name = f"detect_{file_hash}_warped.jpg"
            result.warped.save(f"static/{warp_name}")
            response_data["warped_url"] = f"/static/{warp_name}"

    return response_data


@app.post("/identify-v2", response_model=IdentifyV2Response)
async def identify_card_v2(
    file: UploadFile = File(...),
    locale: str = Query(default="en", description="CardMarket locale"),
):
    """Upload a card image and identify it using OCR + SQL lookup.

    This is the new, fast matching pipeline:
    - OCR reads card name + collector number from the photo
    - SQL finds matching cards in the database (<1ms)
    - No CLIP/FAISS needed — much faster and more accurate for modern cards
    """
    matcher = _get_matcher()

    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image")

    contents = await file.read()
    image = Image.open(io.BytesIO(contents)).convert("RGB")

    result = matcher.match(image)

    if not result.success:
        return IdentifyV2Response(
            success=False,
            processing_time_ms=result.processing_time_ms,
            ocr_name=result.ocr_name,
            ocr_number=result.ocr_number,
            detected_language=result.detected_language,
        )

    top = _match_to_card(result.card, locale)
    alts = [_match_to_card(c, locale) for c in result.candidates[1:5]]

    return IdentifyV2Response(
        success=True,
        processing_time_ms=result.processing_time_ms,
        method=result.method,
        ocr_name=result.ocr_name,
        ocr_number=result.ocr_number,
        detected_language=result.detected_language,
        confidence=result.confidence,
        top_match=top,
        alternatives=alts,
    )


@app.get("/card/{id_product}", response_model=CardDetailResponse)
async def get_card(
    id_product: int,
    locale: str = Query(default="en", description="CardMarket locale"),
):
    """Lookup card details by CardMarket product ID, including CM links."""
    rec = _get_recognizer()
    card = rec.get_card(id_product)
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")

    # Generate URLs for multiple locales
    urls = {
        loc: card_url(card, locale=loc)
        for loc in ["en", "it", "de", "fr", "es"]
    }

    return CardDetailResponse(
        id_product=card.get("id_product", id_product),
        name=card.get("name", ""),
        expansion_name=card.get("expansion_name", ""),
        expansion_id=card.get("expansion_id", 0),
        price_trend=card.get("price_trend", 0),
        price_low=card.get("price_low", 0),
        price_avg=card.get("price_avg", 0),
        price_foil_trend=card.get("price_foil_trend", 0),
        cardmarket_url=card_url(card, locale=locale),
        cardmarket_urls=urls,
    )


# ------------------------------------------------------------------
# Price detail endpoint
# ------------------------------------------------------------------

class PriceDetail(BaseModel):
    """Full multi-source pricing for a card."""
    tcgdex_id: str
    name: str = ""
    set_name: str = ""
    language: str = "en"
    cardmarket: dict = {}
    tcgplayer: dict = {}
    ebay: dict = {}
    graded: dict = {}
    links: dict = {}
    last_updated: str = ""


@app.get("/card/{tcgdex_id}/prices", response_model=PriceDetail)
async def get_card_prices(tcgdex_id: str):
    """Get full multi-source pricing data for a card.

    Returns prices from CardMarket, TCGPlayer, eBay, and graded sales
    with country-level detail (DE, FR, ES, IT) where available.
    """
    matcher = _get_matcher()
    conn = matcher.conn

    # Get card info
    card = conn.execute("""
        SELECT c.tcgdex_id, c.name, c.eng_name, c.language, c.set_id,
               c.cm_id_product, c.tcgplayer_id, c.has_graded,
               s.name as set_name, s.abbreviation
        FROM cards c
        LEFT JOIN sets s ON c.set_id = s.set_id AND s.language = c.language
        WHERE c.tcgdex_id = ?
    """, (tcgdex_id,)).fetchone()

    if not card:
        raise HTTPException(status_code=404, detail="Card not found")

    # Get all price rows
    prices = conn.execute("""
        SELECT source, marketplace, condition, country, currency,
               price_avg, price_low, price_high, price_trend,
               avg_1d, avg_7d, avg_30d, sale_count, confidence,
               snapshot_date, updated_at
        FROM prices_external
        WHERE tcgdex_id = ?
        ORDER BY snapshot_date DESC
    """, (tcgdex_id,)).fetchall()

    # Organize by marketplace
    cardmarket = {}
    tcgplayer = {}
    ebay = {}
    graded = {}
    last_updated = ""

    for p in prices:
        mp = p["marketplace"]
        cond = p["condition"]
        country = p["country"]
        updated = p["updated_at"] or ""
        if updated > last_updated:
            last_updated = updated

        price_data = {
            "avg": p["price_avg"],
            "low": p["price_low"],
            "high": p["price_high"],
            "trend": p["price_trend"],
            "avg_7d": p["avg_7d"],
            "avg_30d": p["avg_30d"],
            "sale_count": p["sale_count"],
            "currency": p["currency"],
            "date": p["snapshot_date"],
        }
        # Remove None values
        price_data = {k: v for k, v in price_data.items() if v is not None}

        # Graded conditions
        if cond.startswith(("PSA_", "BGS_", "CGC_", "SGC_", "ACE_", "TAG_")):
            graded[cond.lower()] = price_data
            continue

        if mp in ("cardmarket", "cardmarket_unsold"):
            key = f"{cond}_{country}".lower() if country != "ALL" else cond.lower()
            cardmarket[key] = price_data

        elif mp == "tcgplayer":
            tcgplayer[cond.lower()] = price_data

        elif mp == "ebay":
            ebay[cond.lower()] = price_data

    # Build links
    links = {}
    cm_id = card["cm_id_product"]
    if cm_id:
        links["cardmarket"] = f"https://www.cardmarket.com/en/Pokemon/Products/Singles?idProduct={cm_id}"
    tcg_id = card["tcgplayer_id"]
    if tcg_id:
        links["tcgplayer"] = f"https://www.tcgplayer.com/product/{tcg_id}"
    pc_url = _build_pricecharting_url(dict(card))
    if pc_url:
        links["pricecharting"] = pc_url

    return PriceDetail(
        tcgdex_id=tcgdex_id,
        name=card["name"] or card["eng_name"] or "",
        set_name=card["set_name"] or "",
        language=card["language"],
        cardmarket=cardmarket,
        tcgplayer=tcgplayer,
        ebay=ebay,
        graded=graded,
        links=links,
        last_updated=last_updated,
    )


# ------------------------------------------------------------------
# Gemini endpoints (alternative AI-based recognition & grading)
# ------------------------------------------------------------------

class GeminiIdentifyResponse(BaseModel):
    """Response from Gemini-based card identification."""
    success: bool
    processing_time_ms: float
    model_used: str = ""
    search_used: bool = False
    card_name: str = ""
    card_name_english: str = ""
    collector_number: str = ""
    set_name: str = ""
    set_abbreviation: str = ""
    language: str = "en"
    rarity: str = ""
    cardmarket_url: str = ""
    cardmarket_url_db: str = ""
    price_trend_eur: Optional[float] = None
    price_from_eur: Optional[float] = None
    confidence: float = 0.0
    notes: str = ""


class GeminiPillarScoreResponse(BaseModel):
    score: float = 0.0
    notes: str = ""
    front_lr: str = ""
    front_tb: str = ""


class GeminiDefectResponse(BaseModel):
    location: str = ""
    type: str = ""
    severity: str = ""


class GeminiGradeResponse(BaseModel):
    """Response from Gemini-based card grading."""
    success: bool
    processing_time_ms: float
    model_used: str = ""
    overall_grade: float = 0.0
    grade_label: str = ""
    centering: Optional[GeminiPillarScoreResponse] = None
    corners: Optional[GeminiPillarScoreResponse] = None
    edges: Optional[GeminiPillarScoreResponse] = None
    surface: Optional[GeminiPillarScoreResponse] = None
    key_defects: list[GeminiDefectResponse] = []
    explanation: str = ""
    grade_probabilities: dict[str, float] = {}
    image_quality_warning: Optional[str] = None


def _enrich_gemini_from_db(result) -> dict | None:
    """Try to find the Gemini-identified card in our local DB.

    Searches by collector_number + set_abbreviation, then by name.
    Returns the best matching card dict or None.
    """
    import re

    # Parse collector number (e.g. "32/106" → number=32)
    num_match = re.match(r"(\d+)", str(result.collector_number or ""))
    number = int(num_match.group(1)) if num_match else None
    abbrev = (result.set_abbreviation or "").strip()
    name = (result.card_name_english or result.card_name or "").strip()

    candidates = []

    # Strategy 1: number + set abbreviation (most precise)
    if number is not None and abbrev:
        candidates = _matcher._query_number_and_code(number, abbrev, lang="en")
        if not candidates:
            # Try without lang filter
            candidates = _matcher._query_number_and_code(number, abbrev)

    # Strategy 2: number + total
    if not candidates and number is not None:
        total_match = re.search(r"/(\d+)", str(result.collector_number or ""))
        if total_match:
            total = int(total_match.group(1))
            candidates = _matcher._query_number_and_total(number, total)

    # Strategy 3: name search
    if not candidates and name:
        candidates = _matcher._query_by_name(name, limit=10, lang="en")

    if not candidates:
        return None

    # If multiple candidates, prefer the one matching the name
    if len(candidates) > 1 and name:
        name_lower = name.lower()
        for c in candidates:
            c_name = (c.get("name") or "").lower()
            if c_name == name_lower or name_lower in c_name:
                return c

    return candidates[0]


@app.post("/gemini/identify", response_model=GeminiIdentifyResponse)
async def gemini_identify(
    file: UploadFile = File(...),
    use_search: bool = Query(
        default=True,
        description="Use Google Search to find CardMarket URL and price (adds ~$0.035/call)",
    ),
):
    """Identify a Pokemon card using Gemini Vision AI.

    This is the Gemini-powered alternative to /identify-v2.
    It uses Google's Gemini model to visually identify the card,
    and optionally searches Google for the CardMarket listing.

    Slower than /identify-v2 (~1-3s vs ~100ms) but requires no
    local CLIP/FAISS index or OCR setup.
    """
    if _gemini_identifier is None:
        raise HTTPException(
            status_code=503,
            detail="Gemini not configured. Set GEMINI_API_KEY environment variable.",
        )

    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image")

    contents = await file.read()
    mime = file.content_type or "image/jpeg"

    result = _gemini_identifier.identify(contents, mime_type=mime, use_search=use_search)

    # Enrich with local DB data — prices, CardMarket URL, etc.
    db_card = None
    cm_url_gemini = result.cardmarket_url  # URL from Gemini/Google Search
    cm_url_db = ""                          # URL from our DB
    price_trend = result.price_trend_eur
    price_from = result.price_from_eur

    if result.success and _matcher:
        try:
            db_card = _enrich_gemini_from_db(result)
        except Exception as e:
            print(f"[Gemini] DB enrichment error: {e}")
            db_card = None

    print(f"[Gemini] db_card found: {db_card is not None}")
    if db_card:
        print(f"[Gemini] db_card: name={db_card.get('name')}, cm_id={db_card.get('cm_id_product')}, set={db_card.get('abbreviation')}")

    if db_card:
        cm_url_db = card_url(
            {
                "id_product": db_card.get("cm_id_product"),
                "name": db_card.get("cm_name") or db_card.get("name", ""),
                "eng_name": db_card.get("eng_name", ""),
                "language": db_card.get("language", "en"),
                "cm_expansion_id": db_card.get("cm_expansion_id"),
                "set_id": db_card.get("set_id", ""),
                "collector_number": db_card.get("collector_number"),
            },
            locale="en",
        )
        if price_trend is None:
            price_trend = db_card.get("price_trend")
        if price_from is None:
            price_from = db_card.get("price_low")

    print(f"[Gemini] URLs: gemini='{cm_url_gemini}' db='{cm_url_db}'")

    return GeminiIdentifyResponse(
        success=result.success,
        processing_time_ms=result.processing_time_ms,
        model_used=result.model_used,
        search_used=result.search_used,
        card_name=result.card_name,
        card_name_english=result.card_name_english,
        collector_number=result.collector_number,
        set_name=result.set_name,
        set_abbreviation=result.set_abbreviation,
        language=result.language,
        rarity=result.rarity,
        cardmarket_url=cm_url_gemini,
        cardmarket_url_db=cm_url_db,
        price_trend_eur=price_trend,
        price_from_eur=price_from,
        confidence=result.confidence,
        notes=result.notes,
    )


@app.post("/gemini/grade", response_model=GeminiGradeResponse)
async def gemini_grade(
    file: UploadFile = File(...),
):
    """Grade a Pokemon card's physical condition using Gemini Vision AI.

    Evaluates 4 pillars (Centering, Corners, Edges, Surface) following
    PSA/BGS/CGC-style grading standards. Returns overall grade 1-10
    with detailed explanation.

    Note: This is an estimated grade, not an official PSA/BGS/CGC grade.
    """
    if _gemini_grader is None:
        raise HTTPException(
            status_code=503,
            detail="Gemini not configured. Set GEMINI_API_KEY environment variable.",
        )

    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image")

    contents = await file.read()
    mime = file.content_type or "image/jpeg"

    result = _gemini_grader.grade(contents, mime_type=mime)

    centering = None
    if result.centering:
        centering = GeminiPillarScoreResponse(
            score=result.centering.score,
            notes=result.centering.notes,
            front_lr=result.centering.front_lr,
            front_tb=result.centering.front_tb,
        )

    corners = None
    if result.corners:
        corners = GeminiPillarScoreResponse(
            score=result.corners.score, notes=result.corners.notes,
        )

    edges = None
    if result.edges:
        edges = GeminiPillarScoreResponse(
            score=result.edges.score, notes=result.edges.notes,
        )

    surface = None
    if result.surface:
        surface = GeminiPillarScoreResponse(
            score=result.surface.score, notes=result.surface.notes,
        )

    defects = [
        GeminiDefectResponse(
            location=d.location, type=d.type, severity=d.severity,
        )
        for d in result.key_defects
    ]

    return GeminiGradeResponse(
        success=result.success,
        processing_time_ms=result.processing_time_ms,
        model_used=result.model_used,
        overall_grade=result.overall_grade,
        grade_label=result.grade_label,
        centering=centering,
        corners=corners,
        edges=edges,
        surface=surface,
        key_defects=defects,
        explanation=result.explanation,
        grade_probabilities=result.grade_probabilities,
        image_quality_warning=result.image_quality_warning,
    )


# Serve the web UI
STATIC_DIR = Path("./static")
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/", include_in_schema=False)
    async def root():
        return FileResponse(str(STATIC_DIR / "index.html"))

    @app.get("/detect", include_in_schema=False)
    async def detect_page():
        return FileResponse(str(STATIC_DIR / "detect.html"))

    @app.get("/scan", include_in_schema=False)
    async def scan_page():
        return FileResponse(str(STATIC_DIR / "scan.html"))

    @app.get("/detect-test", include_in_schema=False)
    async def detect_test_page():
        return FileResponse(str(STATIC_DIR / "detect-test.html"))

    @app.get("/scan_2", include_in_schema=False)
    async def scan_2_page():
        return FileResponse(str(STATIC_DIR / "scan_2.html"))


if __name__ == "__main__":
    uvicorn.run("src.api:app", host="0.0.0.0", port=8000, reload=True)
