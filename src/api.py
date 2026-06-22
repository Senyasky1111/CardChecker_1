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

# Load .env file (API keys for Gemini, etc.)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv not installed, rely on system env vars

import uvicorn
from fastapi import FastAPI, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from PIL import Image
from pydantic import BaseModel

from src.card_detector import (
    get_detector, visualize_detection,
    rectify_for_centering, seed_inner_frame, compute_centering,
)
from src.card_matcher import CardMatcher, MatchResult, _normalize_name as _normalize_card_name
from src.text_index import parse_search_query
from src.cardmarket_url import card_url
from src.ebay_url import ebay_sold_url
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
_claude_grader = None  # ClaudeGrader for /grade (pregrading); lazy import to keep anthropic optional


# ------------------------------------------------------------------
# Lifespan (replaces deprecated @app.on_event)
# ------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _recognizer, _matcher, _detector, _gemini_identifier, _gemini_grader, _claude_grader

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

    # Initialize Claude grader for /grade (pregrading) — requires ANTHROPIC_API_KEY (backend env only)
    if os.environ.get("ANTHROPIC_API_KEY", ""):
        try:
            from src.claude_grade import ClaudeGrader
            _claude_grader = ClaudeGrader()  # reads ANTHROPIC_API_KEY from env
            print(f"Claude grader ready (model: {_claude_grader.model}).")
        except Exception as e:
            print(f"Claude grader init failed: {e}")
    else:
        print("ANTHROPIC_API_KEY not set, /grade disabled.")

    # Billing/auth gate ledger for /grade (separate DB; never the catalog cards.db)
    try:
        from src.grade_gate import init_db as _init_grade_gate
        _init_grade_gate()
    except Exception as e:
        print(f"grade_gate init failed: {e}")

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
    _claude_grader = None


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
    ebay_url: str = ""


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


class QueryInterpretation(BaseModel):
    """How /search understood the raw query — lets the UI show 'matched by ...'."""
    mode: str = "name"  # "number" | "name" | "combo"
    parsed_number: Optional[int] = None
    parsed_total: Optional[int] = None
    parsed_set_code: Optional[str] = None
    parsed_name: str = ""
    result_count: int = 0


class SearchResponse(BaseModel):
    """Response from /search — ranked candidates in the same shape as identify-v2."""
    results: list[SQLCardMatch] = []
    query_interpretation: QueryInterpretation


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


def _build_tcgplayer_url(tcgplayer_id: int | None, card: dict | None = None) -> str:
    """Get TCGPlayer URL — prefer stored DB value, fall back to product ID."""
    # Use stored URL from database (pre-computed by fill_tcgplayer_ids.py)
    if card:
        stored = (card.get("tcgplayer_url") or "").strip()
        if stored:
            return stored
    # Fallback: direct product link
    if tcgplayer_id:
        return f"https://www.tcgplayer.com/product/{tcgplayer_id}"
    return ""


def _build_pricecharting_url(card: dict) -> str:
    """Get PriceCharting URL — prefer stored DB value, fall back to generation."""
    # Use stored URL from database (pre-computed by build_pricecharting_map.py)
    stored = (card.get("pricecharting_url") or "").strip()
    if stored:
        return stored

    # Fallback: generate on-the-fly for cards not yet in DB
    from scripts.build_pricecharting_map import build_pricecharting_url
    return build_pricecharting_url(card)


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
        "abbreviation": card.get("abbreviation", ""),
        "collector_number": card.get("collector_number"),
    }
    cm_url = card_url(cm_card, locale=locale) if (cm_id or card.get("name")) else ""

    # TCGPlayer ID
    tcgplayer_id = card.get("tcgplayer_id")
    tcgplayer_url = _build_tcgplayer_url(tcgplayer_id, card)

    # PriceCharting URL
    pc_url = _build_pricecharting_url(card)

    # eBay sold search URL
    ebay_url = ebay_sold_url(card)

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
        ebay_url=ebay_url,
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


@app.post("/centering")
async def centering_endpoint(
    file: UploadFile = File(...),
    backend: str = Query(default="opencv", description="opencv (no expand) recommended"),
):
    """Rectify a card to a hi-res, aspect-exact (0.716) top-down view for CENTERING.

    Returns the rectified image URL + canvas dims + a ROUGH inner-frame seed (4 line positions
    in canvas px) + a `reliable` flag. The seed is only a starting guess — the client lets the
    user drag the 4 inner lines to the true frame, then calls /centering/compute (or computes
    locally) for the precise ratio. Outer edges = the canvas edges (the card fills the canvas).
    """
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image")
    contents = await file.read()
    image = Image.open(io.BytesIO(contents)).convert("RGB")

    t0 = time.time()
    rect = rectify_for_centering(image, backend=backend)
    seed = seed_inner_frame(rect["warped"], rect["outer"])
    elapsed_ms = (time.time() - t0) * 1000

    import hashlib
    fh = hashlib.md5(contents[:1024]).hexdigest()[:8]
    warp_name = f"centering_{fh}.jpg"
    rect["warped"].save(f"static/{warp_name}")

    return {
        "warped_url": f"/static/{warp_name}",
        "canvas": {"w": rect["W"], "h": rect["H"]},
        "outer": rect["outer"],          # card edge (draggable in the UI; sits inside the margin)
        "seed": {k: seed[k] for k in ("left", "right", "top", "bottom")},
        "seed_reliable": seed["reliable"],
        "detect_method": rect["method"],
        "detect_confidence": round(rect["confidence"], 4),
        "processing_time_ms": round(elapsed_ms, 1),
    }


class _Lines(BaseModel):
    left: float
    right: float
    top: float
    bottom: float


class CenteringComputeRequest(BaseModel):
    outer: _Lines
    inner: _Lines


@app.post("/centering/compute")
async def centering_compute_endpoint(req: CenteringComputeRequest):
    """Given (user-adjusted) OUTER card edges + INNER frame lines in canvas px, return per-axis
    centering % and worst-axis offset. The client also computes this live; this is authoritative."""
    o, i = req.outer, req.inner
    return compute_centering(
        {"left": o.left, "right": o.right, "top": o.top, "bottom": o.bottom},
        {"left": i.left, "right": i.right, "top": i.top, "bottom": i.bottom},
    )


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


@app.get("/search", response_model=SearchResponse)
async def search_cards(
    q: str = Query(..., min_length=1, description="Free text: number, name, or combo"),
    lang: Optional[str] = Query(
        default=None, description="Filter by language: en, ja, zh-tw"
    ),
    limit: int = Query(default=20, ge=1, le=50),
    locale: str = Query(default="en", description="CardMarket locale for URLs"),
):
    """Smart manual card search by collector number, name, or combo.

    Accepts one flexible query and tries SQL lookups from most specific to
    broadest, deduping by card. Ambiguous number-only queries (e.g. "25")
    return top-N candidates rather than asserting a single card. Results use
    the same enriched shape as /identify-v2 so the frontend needs no new
    render logic.
    """
    matcher = _get_matcher()
    sq = parse_search_query(q)

    ordered: list[dict] = []
    seen: set = set()

    def _add(rows: Optional[list[dict]]) -> None:
        for r in rows or []:
            if lang and r.get("language") != lang:
                continue
            # Stable dedup key — fall back to a composite when tcgdex_id is
            # absent, so the same card from two strategies still collapses.
            key = r.get("tcgdex_id") or (
                r.get("cm_id_product"),
                r.get("set_id"),
                r.get("collector_number"),
                r.get("language"),
            )
            if key in seen:
                continue
            seen.add(key)
            ordered.append(r)

    number, total, name, set_code = sq.number, sq.total, sq.name, sq.set_code

    # COMBO — the user typed a name, so the name is the selective signal and
    # the number just refines it. Name-matching cards always outrank pure
    # number matches (e.g. "Charizard 199/197" must surface Charizard first,
    # not every card numbered 199).
    deferred_name_rows: Optional[list[dict]] = None
    if number is not None and name:
        norm = _normalize_card_name(name)
        # Is the token a REAL exact card name ("Mew"), or only a loose/set-code
        # token ("SVE", which just substring-matches "Sabrina's Venonat")? Probe
        # with an exact-first lookup so the answer doesn't depend on whether the
        # base card happens to be in a trend-sorted top-N.
        exact_probe = matcher._query_by_name(name, limit=1, lang=lang)
        is_exact_name = bool(exact_probe) and exact_probe[0].get("name_normalized") == norm
        # name + collector number, direct SQL ("gengar 114" -> "Gengar EX" #114).
        num_match = matcher._query_name_and_number(name, number, total=total, lang=lang)
        if is_exact_name or not set_code:
            _add(num_match)
        # Broad name matches (variants / same family) are a LATE fallback, added
        # after the number strategies — otherwise the wide substring set
        # ("mew" -> Mewtwo, Mew ex, ...) floods an ambiguous combo and buries the
        # actual name+number hit. When set_code looks more likely than a name,
        # the set-code path also gets to lead before these.
        deferred_name_rows = matcher._query_by_name_substring(name, limit=50, lang=lang)

    # NUMBER strategies — most specific first; also the only path when no name.
    if number is not None and set_code:
        rows = matcher._query_number_and_code(number, set_code, lang=lang)
        if not rows:
            rows = matcher._query_number_and_code(number, set_code)
        _add(rows)
    if number is not None and total is not None:
        _add(matcher._query_number_and_total(number, total))
    if number is not None:
        _add(matcher._query_number_only(number, lang=lang))
    if deferred_name_rows:
        _add(deferred_name_rows)

    # NAME only — substring match (all variants: "gengar" -> "Gengar EX" too),
    # then typo-tolerant fuzzy fallback.
    if name and number is None:
        _add(matcher._query_by_name_substring(name, limit=limit, lang=lang))
        if not ordered:
            _add(matcher._query_by_name_fuzzy(name, limit=limit, lang=lang))

    results = [_match_to_card(c, locale) for c in ordered[:limit]]

    return SearchResponse(
        results=results,
        query_interpretation=QueryInterpretation(
            mode=sq.mode,
            parsed_number=number,
            parsed_total=total,
            parsed_set_code=set_code,
            parsed_name=name,
            result_count=len(results),
        ),
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
               c.collector_number, c.pricecharting_url, c.tcgplayer_url,
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
    tcg_url = _build_tcgplayer_url(tcg_id, dict(card))
    if tcg_url:
        links["tcgplayer"] = tcg_url
    pc_url = _build_pricecharting_url(dict(card))
    if pc_url:
        links["pricecharting"] = pc_url
    ebay_link = ebay_sold_url(dict(card))
    if ebay_link:
        links["ebay"] = ebay_link

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
# Price history endpoint
# ------------------------------------------------------------------

class PriceHistoryPoint(BaseModel):
    date: str
    avg: Optional[float] = None
    low: Optional[float] = None
    high: Optional[float] = None
    sale_count: Optional[int] = None


class PriceHistoryResponse(BaseModel):
    tcgdex_id: str
    marketplace: str
    condition: str
    country: str
    data_points: list[PriceHistoryPoint] = []


@app.get("/card/{tcgdex_id}/price-history", response_model=PriceHistoryResponse)
async def get_price_history(
    tcgdex_id: str,
    marketplace: str = Query(default="cardmarket", description="cardmarket, tcgplayer, or ebay"),
    condition: str = Query(default="NEAR_MINT", description="NEAR_MINT, AGGREGATED, PSA_10, etc."),
    country: str = Query(default="ALL", description="ALL, DE, FR, ES, IT"),
    days: int = Query(default=90, ge=1, le=365, description="Number of days of history"),
):
    """Get price history time series for a card.

    Combines data from two sources:
    1. price_history table — deep history from PokeTrace /history endpoint
    2. prices_external table — our daily snapshots

    Returns deduplicated data points sorted by date ascending.
    """
    matcher = _get_matcher()
    conn = matcher.conn

    # Verify card exists
    card = conn.execute("SELECT tcgdex_id FROM cards WHERE tcgdex_id = ?", (tcgdex_id,)).fetchone()
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")

    # Source 1: price_history (deep history from PokeTrace)
    points_map: dict[str, PriceHistoryPoint] = {}

    try:
        rows = conn.execute("""
            SELECT date, avg, low, high, sale_count
            FROM price_history
            WHERE tcgdex_id = ? AND marketplace = ? AND condition = ?
                  AND date >= date('now', '-' || ? || ' days')
            ORDER BY date ASC
        """, (tcgdex_id, marketplace, condition, days)).fetchall()
        for r in rows:
            points_map[r["date"]] = PriceHistoryPoint(
                date=r["date"], avg=r["avg"], low=r["low"],
                high=r["high"], sale_count=r["sale_count"],
            )
    except Exception:
        pass  # Table may not exist yet on old DBs

    # Source 2: prices_external (our daily snapshots — overwrite/fill gaps)
    rows = conn.execute("""
        SELECT snapshot_date, price_avg, price_low, price_high, sale_count
        FROM prices_external
        WHERE tcgdex_id = ? AND marketplace = ? AND condition = ? AND country = ?
              AND snapshot_date >= date('now', '-' || ? || ' days')
        ORDER BY snapshot_date ASC
    """, (tcgdex_id, marketplace, condition, country, days)).fetchall()

    for r in rows:
        d = r["snapshot_date"]
        # Prefer prices_external (our own snapshots) over poketrace history
        points_map[d] = PriceHistoryPoint(
            date=d, avg=r["price_avg"], low=r["price_low"],
            high=r["price_high"], sale_count=r["sale_count"],
        )

    # Sort by date
    data_points = sorted(points_map.values(), key=lambda p: p.date)

    return PriceHistoryResponse(
        tcgdex_id=tcgdex_id,
        marketplace=marketplace,
        condition=condition,
        country=country,
        data_points=data_points,
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
    # Enriched fields from local DB (for multi-source pricing)
    tcgdex_id: str = ""
    tcgplayer_url: str = ""
    pricecharting_url: str = ""
    price_usd: Optional[float] = None
    price_ebay_usd: Optional[float] = None
    graded_psa10: Optional[float] = None
    graded_psa9: Optional[float] = None
    graded_cgc10: Optional[float] = None
    has_graded: bool = False
    price_avg: Optional[float] = None
    price_foil_trend: Optional[float] = None


class GeminiPillarScoreResponse(BaseModel):
    score: float = 0.0
    notes: str = ""
    lr: str = ""    # centering only: left/right ratio
    tb: str = ""    # centering only: top/bottom ratio


class GeminiSideGradeResponse(BaseModel):
    """Grades for one side (front or back) of the card."""
    grade: float = 0.0
    centering: Optional[GeminiPillarScoreResponse] = None
    corners: Optional[GeminiPillarScoreResponse] = None
    edges: Optional[GeminiPillarScoreResponse] = None
    surface: Optional[GeminiPillarScoreResponse] = None


class GeminiDefectResponse(BaseModel):
    side: str = ""       # "front" or "back"
    location: str = ""
    type: str = ""
    severity: str = ""
    visibility: str = "" # "clearly visible" or "faintly visible at angle"


class GeminiGradeResponse(BaseModel):
    """Response from Gemini-based card grading with front/back separation."""
    success: bool
    processing_time_ms: float
    model_used: str = ""
    overall_grade: float = 0.0
    grade_label: str = ""
    front_grade: float = 0.0
    back_grade: float = 0.0
    front: Optional[GeminiSideGradeResponse] = None
    back: Optional[GeminiSideGradeResponse] = None
    # Legacy combined scores (backward compat)
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
        name_matches = [c for c in candidates if name_lower in (c.get("name") or "").lower()]
        if name_matches:
            candidates = name_matches

    # Prefer JP over TW when scores are otherwise equal
    _LANG_PRI = {"ja": 0, "en": 1, "zh-tw": 2}
    candidates.sort(key=lambda c: _LANG_PRI.get(c.get("language", ""), 9))

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

    # Enrich with multi-source prices if we found the card in DB
    tcgdex_id = ""
    tcgplayer_url = ""
    pc_url = ""
    price_usd = None
    price_ebay_usd = None
    graded_psa10 = None
    graded_psa9 = None
    graded_cgc10 = None
    has_graded = False
    price_avg = None
    price_foil_trend = None

    if db_card:
        tcgdex_id = db_card.get("tcgdex_id", "")
        tcgplayer_url = _build_tcgplayer_url(db_card.get("tcgplayer_id"), db_card)
        pc_url = _build_pricecharting_url(db_card)
        price_avg = db_card.get("price_avg")
        price_foil_trend = db_card.get("price_foil_trend")
        has_graded = db_card.get("has_graded", 0) == 1

        if tcgdex_id:
            enriched = _get_enriched_prices(tcgdex_id)
            price_usd = enriched.get("price_usd")
            price_ebay_usd = enriched.get("price_ebay_usd")
            graded_psa10 = enriched.get("graded_psa10")
            graded_psa9 = enriched.get("graded_psa9")
            graded_cgc10 = enriched.get("graded_cgc10")

    return GeminiIdentifyResponse(
        success=result.success,
        processing_time_ms=result.processing_time_ms,
        model_used=result.model_used or "",
        search_used=result.search_used,
        card_name=result.card_name or "",
        card_name_english=result.card_name_english or "",
        collector_number=result.collector_number or "",
        set_name=result.set_name or "",
        set_abbreviation=result.set_abbreviation or "",
        language=result.language or "en",
        rarity=result.rarity or "",
        cardmarket_url=cm_url_gemini,
        cardmarket_url_db=cm_url_db,
        price_trend_eur=price_trend,
        price_from_eur=price_from,
        confidence=result.confidence,
        notes=result.notes or "",
        # Enriched fields from local DB
        tcgdex_id=tcgdex_id,
        tcgplayer_url=tcgplayer_url,
        pricecharting_url=pc_url,
        price_usd=price_usd,
        price_ebay_usd=price_ebay_usd,
        graded_psa10=graded_psa10,
        graded_psa9=graded_psa9,
        graded_cgc10=graded_cgc10,
        has_graded=has_graded,
        price_avg=price_avg,
        price_foil_trend=price_foil_trend,
    )


def _pillar_to_response(p) -> Optional[GeminiPillarScoreResponse]:
    """Convert a PillarScore dataclass to API response model."""
    if not p:
        return None
    return GeminiPillarScoreResponse(
        score=p.score, notes=p.notes, lr=getattr(p, "lr", ""), tb=getattr(p, "tb", ""),
    )


def _side_to_response(side) -> Optional[GeminiSideGradeResponse]:
    """Convert a SideGrade dataclass to API response model."""
    if not side:
        return None
    return GeminiSideGradeResponse(
        grade=side.grade,
        centering=_pillar_to_response(side.centering),
        corners=_pillar_to_response(side.corners),
        edges=_pillar_to_response(side.edges),
        surface=_pillar_to_response(side.surface),
    )


@app.post("/gemini/grade", response_model=GeminiGradeResponse)
async def gemini_grade(
    file: UploadFile = File(..., description="Front image of the card"),
    back_file: Optional[UploadFile] = File(None, description="Back image of the card (optional)"),
):
    """Grade a Pokemon card's physical condition using Gemini Vision AI.

    Evaluates front and back SEPARATELY across 4 pillars
    (Centering, Corners, Edges, Surface) following PSA/BGS/CGC-style
    grading standards. Returns overall grade, front grade, and back
    grade (1-10) with detailed explanation.

    Note: This is an estimated grade, not an official PSA/BGS/CGC grade.
    """
    if _gemini_grader is None:
        raise HTTPException(
            status_code=503,
            detail="Gemini not configured. Set GEMINI_API_KEY environment variable.",
        )

    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Front file must be an image")

    front_bytes = await file.read()
    mime = file.content_type or "image/jpeg"

    back_bytes = None
    if back_file and back_file.filename:
        if not back_file.content_type or not back_file.content_type.startswith("image/"):
            raise HTTPException(status_code=400, detail="Back file must be an image")
        back_bytes = await back_file.read()

    result = _gemini_grader.grade(front_bytes, back_bytes=back_bytes, mime_type=mime)

    defects = [
        GeminiDefectResponse(
            side=d.side, location=d.location, type=d.type,
            severity=d.severity, visibility=d.visibility,
        )
        for d in result.key_defects
    ]

    return GeminiGradeResponse(
        success=result.success,
        processing_time_ms=result.processing_time_ms,
        model_used=result.model_used,
        overall_grade=result.overall_grade,
        grade_label=result.grade_label,
        front_grade=result.front_grade,
        back_grade=result.back_grade,
        front=_side_to_response(result.front),
        back=_side_to_response(result.back),
        centering=_pillar_to_response(result.centering),
        corners=_pillar_to_response(result.corners),
        edges=_pillar_to_response(result.edges),
        surface=_pillar_to_response(result.surface),
        key_defects=defects,
        explanation=result.explanation,
        grade_probabilities=result.grade_probabilities,
        image_quality_warning=result.image_quality_warning,
    )


# ------------------------------------------------------------------
# /grade — pregrading (Claude condition grade + confident distribution)
# TZ: vault/10-Projects/2026-Q2-pregrading-integration.md
# ------------------------------------------------------------------

MAX_GRADE_IMAGE_BYTES = 15 * 1024 * 1024     # 15 MB per side
MAX_GRADE_IMAGE_PIXELS = 40_000_000          # 40 MP — decompression-bomb guard


async def _read_grade_image(upload: "UploadFile", label: str) -> bytes:
    """Validate + read one side's image (content-type, size, decodability, pixel cap)."""
    if not upload or not upload.filename:
        raise HTTPException(status_code=400, detail=f"{label} image is required")
    if not upload.content_type or not upload.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail=f"{label} file must be an image")
    data = await upload.read()
    if not data:
        raise HTTPException(status_code=400, detail=f"{label} image is empty")
    if len(data) > MAX_GRADE_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail=f"{label} image too large (max 15 MB)")
    # verify it actually decodes and is within the pixel cap (don't trust content_type)
    import io
    from PIL import Image as _PILImage
    try:
        with _PILImage.open(io.BytesIO(data)) as im:
            w, h = im.size
    except Exception:
        raise HTTPException(status_code=400, detail=f"{label} file is not a readable image")
    if w * h > MAX_GRADE_IMAGE_PIXELS:
        raise HTTPException(status_code=413, detail=f"{label} image resolution too high")
    return data


@app.post("/grade")
async def grade_card_endpoint(
    file: UploadFile = File(..., description="FRONT image of the card (required)"),
    back_file: UploadFile = File(..., description="BACK image of the card (required)"),
    front_centering_off: Optional[float] = Form(default=None),
    back_centering_off: Optional[float] = Form(default=None),
    x_grade_secret: Optional[str] = Header(default=None, alias="X-Grade-Secret"),
    x_user_id: Optional[str] = Header(default=None, alias="X-User-Id"),
    authorization: Optional[str] = Header(default=None),
):
    """Pregrading: estimate a card's condition with the validated Claude grader.

    Returns a CONFIDENT empirical probability distribution over grades (most-likely grade +
    bucket + distribution), per-side pillars, the 'wear we found here' evidence (MODERATE+),
    and a sell-vs-grade decision. Both front AND back are REQUIRED.

    Auth + credits: prefers the Base44 user token (`Authorization: Bearer <jwt>`) — verified
    with Base44, which yields identity + tier, and the per-tier grade limit is enforced against
    the Base44 CreditTransaction ledger (the same counter the webapp shows). During beta only
    admins may grade. Falls back to a local shared-secret + ledger gate (X-Grade-Secret /
    X-User-Id) for dev/testing without Base44. Per-user rate limit + content-hash idempotency
    (a retry of the same images replays the cached result, no re-charge) apply in both modes.
    This is an estimate from photos, not an official PSA/BGS/CGC grade. ~$0.05/call, ~10-15s.
    """
    if _claude_grader is None:
        raise HTTPException(status_code=503,
                            detail="Grading not configured. Set ANTHROPIC_API_KEY.")

    from fastapi.concurrency import run_in_threadpool
    from src.pregrade_service import grade_card
    from src import grade_gate
    import json as _json
    import anthropic

    # --- Auth: Base44 token (authoritative) takes precedence; else local gate (dev) ---
    bearer = None
    if authorization and authorization.lower().startswith("bearer "):
        bearer = authorization[7:].strip()

    base44_user = None
    if bearer:
        from src import base44_auth
        base44_user = await run_in_threadpool(base44_auth.verify_user, bearer)   # 401/503
        base44_auth.assert_beta_access(base44_user)                              # 403 in beta
        user_id = base44_user.get("email") or base44_user.get("id") or "base44"
    elif os.getenv("GRADE_REQUIRE_BASE44") == "1":
        # prod posture: a Base44 token is mandatory (no anonymous/local-gate fallback)
        raise HTTPException(status_code=401, detail="Authentication required")
    else:
        user_id = grade_gate.authenticate(x_grade_secret, x_user_id)

    grade_gate.enforce_rate_limit(user_id)

    # Both sides mandatory (reject single-side).
    front_bytes = await _read_grade_image(file, "Front")
    back_bytes = await _read_grade_image(back_file, "Back")

    # Idempotency — a double-tap/retry of the same images replays the cached result (no re-charge).
    key = grade_gate.idem_key(user_id, front_bytes, back_bytes)
    cached = grade_gate.idem_get(key)
    if cached is not None:
        return cached

    # Quota check BEFORE spending money.
    if base44_user is not None:
        from src import base44_auth
        wk, mo = await run_in_threadpool(base44_auth.grade_counts, bearer, user_id)   # 503 if unavailable
        if not base44_auth.within_limit(base44_user.get("subscription_tier"), wk, mo):
            raise HTTPException(status_code=402, detail="No grade credits remaining")
        grade_gate.daily_reserve()        # global cost circuit-breaker (429 if hit)
        reserved_local = False
    else:
        grade_gate.reserve(user_id)        # local per-user + daily (402/429), reserve-then-refund
        reserved_local = True

    def _release():
        if reserved_local:
            grade_gate.refund(user_id)
        else:
            grade_gate.daily_refund()

    t0 = time.time()
    try:
        result = await run_in_threadpool(
            grade_card, _claude_grader, front_bytes, back_bytes,
            "card", front_centering_off, back_centering_off)
    except ValueError as e:
        _release()
        raise HTTPException(status_code=400, detail=str(e))
    except anthropic.RateLimitError:
        _release()
        raise HTTPException(status_code=429, detail="Grading is busy, please retry shortly")
    except anthropic.APITimeoutError:
        _release()
        raise HTTPException(status_code=504, detail="Grading timed out, please retry")
    except (anthropic.APIConnectionError, anthropic.InternalServerError) as e:
        # upstream unavailable / 'overloaded' (529) / other 5xx — retryable
        _release()
        print(f"/grade upstream error: {type(e).__name__}: {e}")
        raise HTTPException(status_code=503, detail="Grading temporarily unavailable, please retry")
    except (_json.JSONDecodeError, KeyError) as e:
        # grader returned empty / non-JSON / missing fields
        _release()
        print(f"/grade parse error: {type(e).__name__}: {e}")
        raise HTTPException(status_code=502, detail="Grading returned an unexpected response, please retry")
    except Exception as e:
        # Anthropic/runtime failure — release reservation, don't leak internals; log server-side.
        _release()
        print(f"/grade failed: {type(e).__name__}: {e}")
        raise HTTPException(status_code=502, detail="Grading failed, please retry")

    # Success: charge the credit (Base44 ledger written AFTER success), cache, observability line.
    if base44_user is not None:
        from src import base44_auth
        await run_in_threadpool(base44_auth.charge_grade, bearer, key[:16])
    grade_gate.idem_put(key, result)
    print(f"[grade] user={user_id} mode={'base44' if base44_user else 'local'} "
          f"ml={int((time.time()-t0)*1000)} "
          f"grade={result.get('overall', {}).get('most_likely')} "
          f"bucket={result.get('overall', {}).get('bucket')} "
          f"floor={result.get('safety_floor')} cost~=0.05")
    return result


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

    @app.get("/centering-ui", include_in_schema=False)
    async def centering_page():
        return FileResponse(str(STATIC_DIR / "centering.html"),
                            headers={"Cache-Control": "no-store, max-age=0"})

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
