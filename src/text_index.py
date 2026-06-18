"""
Text-based card index for fast lookup by name and collector number.

Built from the same metadata as the FAISS index. Maps:
- (set_code, collector_number) → list of FAISS indices
- normalized_name → list of FAISS indices

Used by the hybrid recognition pipeline: after OCR extracts a card name
and/or collector number, this index finds matching FAISS entries in O(1).
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from rapidfuzz import fuzz

from src.ocr import CollectorNumber

# Characters to strip when normalizing card names for matching
_STRIP_RE = re.compile(r"[\s\-'.,:;!\?\(\)\[\]]+")
_BRACKET_RE = re.compile(r"\s*\[.*?\]")
_PARENS_RE = re.compile(r"\s*\(.*?\)")


def normalize_name(name: str) -> str:
    """Normalize a card name for fuzzy matching.

    'Pikachu ex [Resolute Heart | Topaz Bolt]' → 'pikachuex'
    'Mr. Mime (123/456)' → 'mrmime'
    """
    name = _BRACKET_RE.sub("", name)
    name = _PARENS_RE.sub("", name)
    name = _STRIP_RE.sub("", name)
    return name.lower().strip()


# A query token that is a collector number: "96", "096", "096/080", "96/80".
_NUM_TOKEN_RE = re.compile(r"^(\d{1,4})(?:/(\d{1,5}))?$")
# A short alphabetic token that *might* be a printed set code: "SVE", "SSP".
_SETCODE_RE = re.compile(r"^[A-Za-z]{2,4}$")


@dataclass
class SearchQuery:
    """Parsed free-text search query.

    `set_code` and `name` are deliberately non-exclusive: a leading short
    token like "Mew" or "SVE" is exposed BOTH as a candidate set code and as
    part of `name`, because the two cases ("Mew 25" = name+number vs
    "SVE 096" = setcode+number) are indistinguishable without the catalog.
    The endpoint resolves the ambiguity by trying both against SQL.
    """

    raw: str
    number: Optional[int] = None
    total: Optional[int] = None
    set_code: Optional[str] = None
    name: str = ""
    mode: str = "name"  # "number" | "name" | "combo"


def parse_search_query(q: str) -> SearchQuery:
    """Classify a free-text query into number / name / combo signals.

    Examples:
        "096/080"              -> number=96, total=80, mode=number
        "25"                   -> number=25, mode=number (ambiguous; caller returns top-N)
        "Pikachu"              -> name="Pikachu", mode=name
        "Pikachu 25"           -> name="Pikachu", number=25, mode=combo
        "Charizard ex 199/197" -> name="Charizard ex", number=199, total=197, mode=combo
        "SVE 096"              -> set_code="SVE", name="SVE", number=96, mode=combo
    """
    raw = (q or "").strip()
    tokens = raw.split()

    number: Optional[int] = None
    total: Optional[int] = None
    number_idx: Optional[int] = None

    # First token that looks like a collector number wins.
    for i, tok in enumerate(tokens):
        m = _NUM_TOKEN_RE.match(tok)
        if m:
            n = int(m.group(1))
            if 1 <= n <= 9999:
                number = n
                total = int(m.group(2)) if m.group(2) else None
                number_idx = i
                break

    # A leading 2-4 letter token (not itself the number) may be a set code.
    set_code: Optional[str] = None
    if number is not None and tokens and number_idx != 0 and _SETCODE_RE.match(tokens[0]):
        set_code = tokens[0].upper()

    # Name keeps every non-number token (including a candidate set-code token,
    # so "Mew 25" can still match the Pokémon "Mew").
    name = " ".join(t for i, t in enumerate(tokens) if i != number_idx).strip()

    if number is not None and name:
        mode = "combo"
    elif number is not None:
        mode = "number"
    else:
        mode = "name"

    return SearchQuery(
        raw=raw, number=number, total=total, set_code=set_code, name=name, mode=mode
    )


class CardTextIndex:
    """Fast lookup of cards by name and/or collector number."""

    def __init__(
        self,
        cards_by_idx: dict[int, dict],
        card_ids: list,
        set_abbreviations: dict[str, str] | None = None,
    ):
        """
        Build text index from FAISS metadata.

        Args:
            cards_by_idx: FAISS position → card data dict
            card_ids: FAISS position → product ID
            set_abbreviations: TCGdex set ID → printed set code (e.g. "sv08" → "SSP")
        """
        self._cards_by_idx = cards_by_idx
        self._card_ids = card_ids

        # set_id → printed code  ("sv08" → "SSP")
        self._set_to_code: dict[str, str] = set_abbreviations or {}
        # printed code → set_ids  ("SSP" → ["sv08"])
        self._code_to_sets: dict[str, list[str]] = defaultdict(list)
        for set_id, code in self._set_to_code.items():
            if code:
                self._code_to_sets[code.upper()].append(set_id)

        # (set_id, local_number) → [faiss_idx, ...]
        self._by_set_and_number: dict[tuple[str, int], list[int]] = defaultdict(list)

        # (set_code_upper, local_number) → [faiss_idx, ...]
        self._by_code_and_number: dict[tuple[str, int], list[int]] = defaultdict(list)

        # local_number → [faiss_idx, ...]  (ambiguous, many sets share same numbers)
        self._by_number: dict[int, list[int]] = defaultdict(list)

        # normalized_name → [faiss_idx, ...]
        self._by_name: dict[str, list[int]] = defaultdict(list)

        # All unique normalized names (for fuzzy search)
        self._all_names: list[str] = []
        self._name_to_indices: dict[str, list[int]] = defaultdict(list)

        self._build()

    def _build(self) -> None:
        """Build all lookup tables from card metadata."""
        seen_names: set[str] = set()

        for idx, card in self._cards_by_idx.items():
            # --- Collector number indexing ---
            # Prefer enriched fields (_printed_number, _printed_set_code)
            printed_num = card.get("_printed_number")
            printed_code = card.get("_printed_set_code", "")

            if printed_num is not None:
                # Use enriched fields directly
                self._by_number[printed_num].append(idx)
                if printed_code:
                    self._by_code_and_number[
                        (printed_code.upper(), printed_num)
                    ].append(idx)
                # Also index by TCGdex set_id for backward compat
                tcgdex_id = card.get("_tcgdex_id", "")
                if tcgdex_id and "-" in tcgdex_id:
                    set_id = tcgdex_id.rsplit("-", 1)[0]
                    self._by_set_and_number[(set_id, printed_num)].append(idx)
            else:
                # Fallback: parse _tcgdex_id (pre-enrichment compat)
                tcgdex_id = card.get("_tcgdex_id", "")
                if tcgdex_id and "-" in tcgdex_id:
                    parts = tcgdex_id.rsplit("-", 1)
                    set_id = parts[0]
                    try:
                        local_num = int(parts[1])
                    except ValueError:
                        local_num = None

                    if local_num is not None:
                        self._by_set_and_number[(set_id, local_num)].append(idx)
                        self._by_number[local_num].append(idx)
                        code = self._set_to_code.get(set_id, "").upper()
                        if code:
                            self._by_code_and_number[
                                (code, local_num)
                            ].append(idx)

            # --- Name indexing ---
            name = card.get("name", "")
            if name:
                norm = normalize_name(name)
                if norm:
                    self._by_name[norm].append(idx)
                    if norm not in seen_names:
                        self._all_names.append(norm)
                        seen_names.add(norm)
                    self._name_to_indices[norm].append(idx)

    # ------------------------------------------------------------------
    # Lookup methods
    # ------------------------------------------------------------------

    def lookup_by_collector_number(
        self,
        number: int,
        set_code: Optional[str] = None,
        total: Optional[int] = None,
    ) -> list[int]:
        """
        Find FAISS indices matching a collector number.

        If set_code provided: exact match on (code, number).
        Otherwise: match by number only (ambiguous).
        """
        if set_code:
            key = (set_code.upper(), number)
            results = list(self._by_code_and_number.get(key, []))
            if results:
                return results

            # Try matching set_code to set_ids directly
            possible_sets = self._code_to_sets.get(set_code.upper(), [])
            for sid in possible_sets:
                key2 = (sid, number)
                results.extend(self._by_set_and_number.get(key2, []))
            if results:
                return results

        # Fallback: match by number only
        return list(self._by_number.get(number, []))

    def lookup_by_name(
        self,
        name: str,
        threshold: float = 75.0,
        limit: int = 20,
    ) -> list[tuple[int, float]]:
        """
        Fuzzy name match. Returns [(faiss_idx, similarity), ...].

        Uses rapidfuzz for fast Levenshtein-based matching.
        """
        norm = normalize_name(name)
        if not norm:
            return []

        # Exact match first
        exact = self._by_name.get(norm, [])
        if exact:
            return [(idx, 100.0) for idx in exact]

        # Fuzzy match against all unique names
        matches: list[tuple[str, float]] = []
        for candidate_name in self._all_names:
            score = fuzz.ratio(norm, candidate_name)
            if score >= threshold:
                matches.append((candidate_name, score))

        # Sort by score descending
        matches.sort(key=lambda x: x[1], reverse=True)
        matches = matches[:limit]

        # Expand to FAISS indices
        results: list[tuple[int, float]] = []
        for matched_name, score in matches:
            for idx in self._name_to_indices.get(matched_name, []):
                results.append((idx, score))

        return results

    def lookup_combined(
        self,
        name: Optional[str] = None,
        number: Optional[CollectorNumber] = None,
    ) -> list[int]:
        """
        Combined lookup: collector number first (strongest signal),
        then intersect/extend with name matches.
        """
        number_results: set[int] = set()
        name_results: set[int] = set()

        # Collector number lookup
        if number is not None:
            indices = self.lookup_by_collector_number(
                number=number.number,
                set_code=number.set_code,
                total=number.total,
            )
            number_results = set(indices)

        # Name lookup
        if name:
            name_matches = self.lookup_by_name(name, threshold=75.0, limit=30)
            name_results = {idx for idx, _ in name_matches}

        # If we have both, prefer intersection; fall back to union
        if number_results and name_results:
            intersection = number_results & name_results
            if intersection:
                return list(intersection)
            # No intersection — number is more reliable, return those
            return list(number_results)

        if number_results:
            return list(number_results)

        if name_results:
            return list(name_results)

        return []

    def get_set_code(self, set_id: str) -> Optional[str]:
        """Get the printed set code for a TCGdex set ID."""
        return self._set_to_code.get(set_id)

    @classmethod
    def load_set_abbreviations(
        cls, path: str | Path = "./data/cardmarket/_set_abbreviations.json"
    ) -> dict[str, str]:
        """Load set abbreviations from disk."""
        p = Path(path)
        if p.exists():
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}
