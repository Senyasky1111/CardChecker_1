"""
Gemini-based card identification with Google Search grounding.

Sends a card photo to Gemini Vision → gets card name, set, number →
optionally searches CardMarket via Google Search for direct URL and price.

Usage:
    identifier = GeminiIdentifier(api_key="...")
    result = await identifier.identify(image_bytes)
    # result.card_name, result.cardmarket_url, result.price, etc.
"""

from __future__ import annotations

import json
import os
import base64
import time
from dataclasses import dataclass, field
from typing import Optional

from google import genai
from google.genai import types


# ------------------------------------------------------------------
# System prompt for card identification
# ------------------------------------------------------------------

IDENTIFY_SYSTEM_PROMPT = """You are a Pokemon trading card identification expert.

Given a photo of a Pokemon card, you must identify it precisely.

## Your task
1. Read the card name from the card image
2. Read the collector number (e.g. "057/191") from the bottom of the card
3. Identify the expansion/set name and its abbreviation (e.g. "SSP" for Surging Sparks)
4. Determine the card language (English, Japanese, Chinese, etc.)
5. Identify the rarity (Common, Uncommon, Rare, Holo Rare, Ultra Rare, etc.)
6. Search CardMarket for this exact card to find its product page URL and current price

## Important rules
- Read the ACTUAL text on the card — do not guess or hallucinate
- The collector number is usually at the bottom: format "XXX/YYY" followed by set abbreviation
- For Japanese cards, the name will be in Japanese — provide both Japanese name and English name
- For the CardMarket URL, search for the exact card (name + set + number) on cardmarket.com
- For the price, look for the "Price Trend" or "From" price on CardMarket

## Response format
You MUST respond with valid JSON only, no markdown, no extra text:
{
    "card_name": "exact name as printed on card",
    "card_name_english": "English name (same as card_name if English card)",
    "collector_number": "057/191",
    "set_name": "Surging Sparks",
    "set_abbreviation": "SSP",
    "language": "en",
    "rarity": "Illustration Rare",
    "cardmarket_url": "https://www.cardmarket.com/en/Pokemon/Products/Singles/...",
    "price_trend_eur": 12.50,
    "price_from_eur": 9.80,
    "confidence": 0.95,
    "notes": "any relevant notes about identification"
}

If you cannot identify the card, set confidence to 0 and explain in notes.
For price fields, use null if price is not available.
"""

IDENTIFY_PROMPT_NO_SEARCH = """You are a Pokemon trading card identification expert.

Given a photo of a Pokemon card, identify it precisely.

## Your task
1. Read the card name from the card image
2. Read the collector number (e.g. "057/191") from the bottom of the card
3. Identify the expansion/set name and its abbreviation
4. Determine the card language
5. Identify the rarity

## Important rules
- Read the ACTUAL text on the card — do not guess
- The collector number is usually at the bottom: "XXX/YYY" + set abbreviation
- For Japanese cards, provide both Japanese and English names

## Response format
Respond with valid JSON only:
{
    "card_name": "exact name as printed on card",
    "card_name_english": "English name",
    "collector_number": "057/191",
    "set_name": "Surging Sparks",
    "set_abbreviation": "SSP",
    "language": "en",
    "rarity": "Illustration Rare",
    "confidence": 0.95,
    "notes": ""
}
"""


# ------------------------------------------------------------------
# Result dataclass
# ------------------------------------------------------------------

@dataclass
class GeminiIdentifyResult:
    """Result from Gemini card identification."""
    success: bool = False
    card_name: str = ""
    card_name_english: str = ""
    collector_number: str = ""
    set_name: str = ""
    set_abbreviation: str = ""
    language: str = "en"
    rarity: str = ""
    cardmarket_url: str = ""
    price_trend_eur: Optional[float] = None
    price_from_eur: Optional[float] = None
    confidence: float = 0.0
    notes: str = ""
    processing_time_ms: float = 0.0
    model_used: str = ""
    search_used: bool = False
    raw_response: str = ""


# ------------------------------------------------------------------
# Main class
# ------------------------------------------------------------------

class GeminiIdentifier:
    """Identify Pokemon cards using Gemini Vision API."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "gemini-2.5-flash",
        use_search: bool = True,
    ):
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY", "")
        if not self.api_key:
            raise ValueError(
                "Gemini API key required. Set GEMINI_API_KEY env var or pass api_key="
            )
        self.model = model
        self.use_search = use_search
        self.client = genai.Client(api_key=self.api_key)

    def identify(
        self,
        image_bytes: bytes,
        mime_type: str = "image/jpeg",
        use_search: Optional[bool] = None,
    ) -> GeminiIdentifyResult:
        """Identify a Pokemon card from image bytes.

        Args:
            image_bytes: Raw image bytes (JPEG or PNG)
            mime_type: MIME type of the image
            use_search: Override instance-level search setting

        Returns:
            GeminiIdentifyResult with card details
        """
        search = use_search if use_search is not None else self.use_search
        t0 = time.time()

        # Build tools list
        tools = []
        if search:
            tools.append(types.Tool(google_search=types.GoogleSearch()))

        # Select prompt
        system_prompt = IDENTIFY_SYSTEM_PROMPT if search else IDENTIFY_PROMPT_NO_SEARCH

        # Build content with image
        image_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
        text_part = types.Part.from_text(text="Identify this Pokemon card. Return JSON only.")

        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=[image_part, text_part],
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    tools=tools if tools else None,
                    temperature=0.1 if not search else 1.0,  # search needs temp=1.0
                    response_mime_type="application/json" if not search else None,
                ),
            )
        except Exception as e:
            return GeminiIdentifyResult(
                success=False,
                notes=f"Gemini API error: {e}",
                processing_time_ms=(time.time() - t0) * 1000,
                model_used=self.model,
            )

        elapsed_ms = (time.time() - t0) * 1000
        raw_text = response.text or ""

        # Parse JSON from response
        result = self._parse_response(raw_text)
        result.processing_time_ms = elapsed_ms
        result.model_used = self.model
        result.search_used = search
        result.raw_response = raw_text

        # Extract CardMarket URL from grounding metadata if available
        if search and not result.cardmarket_url:
            result.cardmarket_url = self._extract_cardmarket_url(response)

        return result

    def _parse_response(self, raw_text: str) -> GeminiIdentifyResult:
        """Parse Gemini's JSON response into a result object."""
        # Strip markdown code fences if present
        text = raw_text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            # Remove first and last lines (```json and ```)
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines)

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            # Try to find JSON in the response
            import re
            match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', text, re.DOTALL)
            if match:
                try:
                    data = json.loads(match.group())
                except json.JSONDecodeError:
                    return GeminiIdentifyResult(
                        success=False,
                        notes=f"Failed to parse JSON from response: {raw_text[:200]}",
                    )
            else:
                return GeminiIdentifyResult(
                    success=False,
                    notes=f"No JSON found in response: {raw_text[:200]}",
                )

        confidence = float(data.get("confidence", 0))
        return GeminiIdentifyResult(
            success=confidence > 0.3,
            card_name=data.get("card_name", ""),
            card_name_english=data.get("card_name_english", ""),
            collector_number=data.get("collector_number", ""),
            set_name=data.get("set_name", ""),
            set_abbreviation=data.get("set_abbreviation", ""),
            language=data.get("language", "en"),
            rarity=data.get("rarity", ""),
            cardmarket_url=data.get("cardmarket_url", "") or "",
            price_trend_eur=data.get("price_trend_eur"),
            price_from_eur=data.get("price_from_eur"),
            confidence=confidence,
            notes=data.get("notes", ""),
        )

    def _extract_cardmarket_url(self, response) -> str:
        """Extract CardMarket URL from grounding metadata."""
        try:
            metadata = response.candidates[0].grounding_metadata
            if metadata and metadata.grounding_chunks:
                for chunk in metadata.grounding_chunks:
                    if chunk.web and chunk.web.uri:
                        uri = chunk.web.uri
                        if "cardmarket.com" in uri:
                            return uri
        except (AttributeError, IndexError):
            pass
        return ""
