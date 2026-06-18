"""
Tests for the smart card search feature.

Coverage:
  1. parse_search_query (unit, no DB)
  2. CardMatcher._query_by_name_fuzzy (integration, real DB)
  3. search_cards endpoint dispatch (integration, real DB)

Integration tests are skipped automatically when data/cards.db is absent.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Optional

import pytest

from src.text_index import SearchQuery, parse_search_query

DB_PATH = Path("data/cards.db")


def _db_available() -> bool:
    return DB_PATH.exists()


# ===========================================================================
# 1. parse_search_query — pure unit tests, no DB
# ===========================================================================


@pytest.mark.parametrize(
    "query, expected_number, expected_total, expected_set_code, expected_name, expected_mode",
    [
        # --- number-only mode ---
        # "096/080" -> leading zero stripped, total parsed, empty name
        ("096/080", 96, 80, None, "", "number"),
        # "96/80" without leading zeros — same result
        ("96/80", 96, 80, None, "", "number"),
        # bare number
        ("25", 25, None, None, "", "number"),
        # max valid number
        ("9999", 9999, None, None, "", "number"),
        # --- name-only mode ---
        ("Pikachu", None, None, None, "Pikachu", "name"),
        ("base set", None, None, None, "base set", "name"),
        # "ex" alone is NOT a number and NOT a set code (only 2 chars but it IS
        # a valid _SETCODE_RE match; however with no number present set_code is
        # never populated, so set_code stays None)
        ("ex", None, None, None, "ex", "name"),
        # empty / whitespace-only
        ("", None, None, None, "", "name"),
        ("   ", None, None, None, "", "name"),
        # --- combo mode ---
        ("Pikachu 25", 25, None, None, "Pikachu", "combo"),
        # "Charizard ex 199/197" — "ex" must NOT be parsed as a number or code
        ("Charizard ex 199/197", 199, 197, None, "Charizard ex", "combo"),
        # "SVE 096" — leading alphabetic token IS a set-code candidate
        ("SVE 096", 96, None, "SVE", "SVE", "combo"),
        # "Mew 25" — "Mew" exposed both as set_code candidate AND as name
        ("Mew 25", 25, None, "MEW", "Mew", "combo"),
        # --- boundary / invalid numbers ---
        # n=0 must NOT be treated as a number token
        ("0", None, None, None, "0", "name"),
        # n>9999 must NOT be treated as a number token
        ("10000", None, None, None, "10000", "name"),
    ],
    ids=[
        "leading_zero_with_total",
        "number_slash_total_no_leading_zero",
        "bare_number",
        "max_valid_number_9999",
        "name_only",
        "multiword_name",
        "ex_token_name_only",
        "empty_string",
        "whitespace_only",
        "name_and_number_combo",
        "charizard_ex_combo_ex_not_parsed_as_code",
        "set_code_sve_combo",
        "mew_25_ambiguous_set_code_candidate",
        "zero_not_a_number",
        "over_9999_not_a_number",
    ],
)
def test_parse_search_query_parametrized(
    query: str,
    expected_number: Optional[int],
    expected_total: Optional[int],
    expected_set_code: Optional[str],
    expected_name: str,
    expected_mode: str,
) -> None:
    sq = parse_search_query(query)

    assert sq.number == expected_number, (
        f"q={query!r}: number expected {expected_number}, got {sq.number}"
    )
    assert sq.total == expected_total, (
        f"q={query!r}: total expected {expected_total}, got {sq.total}"
    )
    assert sq.set_code == expected_set_code, (
        f"q={query!r}: set_code expected {expected_set_code!r}, got {sq.set_code!r}"
    )
    assert sq.name == expected_name, (
        f"q={query!r}: name expected {expected_name!r}, got {sq.name!r}"
    )
    assert sq.mode == expected_mode, (
        f"q={query!r}: mode expected {expected_mode!r}, got {sq.mode!r}"
    )


def test_parse_search_query_returns_dataclass() -> None:
    """Return type is always SearchQuery regardless of input."""
    sq = parse_search_query("anything")
    assert isinstance(sq, SearchQuery)


def test_parse_search_query_raw_preserved() -> None:
    """raw field stores the stripped original query."""
    sq = parse_search_query("  Pikachu 25  ")
    assert sq.raw == "Pikachu 25"


def test_parse_search_query_set_code_uppercased() -> None:
    """set_code is always uppercased when present."""
    sq = parse_search_query("sve 096")
    assert sq.set_code == "SVE"


def test_parse_search_query_leading_zero_stripped() -> None:
    """Leading zeros in number tokens are stripped ('096' -> 96)."""
    sq = parse_search_query("096")
    assert sq.number == 96


# ===========================================================================
# 2. CardMatcher._query_by_name_fuzzy — integration tests (real DB)
# ===========================================================================


@pytest.fixture(scope="module")
def matcher():
    """Shared CardMatcher connected to the real DB for integration tests."""
    if not _db_available():
        pytest.skip("data/cards.db not present — skipping integration tests")
    from src.card_matcher import CardMatcher
    return CardMatcher(str(DB_PATH))


@pytest.mark.integration
def test_fuzzy_name_typo_finds_pikachu(matcher) -> None:
    """Typo 'pikchu' should return >=1 result whose name contains 'Pikachu'."""
    results = matcher._query_by_name_fuzzy("pikchu", limit=10, threshold=80)
    assert len(results) >= 1, "Expected at least one result for 'pikchu'"
    assert any(
        "pikachu" in r.get("name", "").lower() for r in results
    ), f"No Pikachu in results: {[r.get('name') for r in results]}"


@pytest.mark.integration
def test_fuzzy_name_nonsense_returns_empty(matcher) -> None:
    """Clearly nonsense string should return no results."""
    results = matcher._query_by_name_fuzzy("zzzznotacard", limit=10, threshold=80)
    assert results == [], f"Expected [], got {results}"


@pytest.mark.integration
def test_fuzzy_name_result_shape(matcher) -> None:
    """Result dicts must contain the minimum required keys."""
    results = matcher._query_by_name_fuzzy("pikchu", limit=5, threshold=80)
    assert results, "Need at least one result to check shape"
    required_keys = {"name", "collector_number", "tcgdex_id", "language"}
    for row in results:
        missing = required_keys - set(row.keys())
        assert not missing, f"Result row missing keys: {missing}"


# ===========================================================================
# 3. /search endpoint dispatch — integration tests (real DB)
# ===========================================================================


@pytest.fixture(scope="module")
def search_ready(matcher):
    """Patch api._matcher so search_cards works without the lifespan."""
    import src.api as api
    api._matcher = matcher
    return api


@pytest.mark.integration
def test_search_mew_25_name_beats_set_code(search_ready) -> None:
    """
    'Mew 25' is ambiguous: 'Mew' could be the Pokemon name OR a set code.
    The name-match path must win and results[0].name must be exactly 'Mew'.
    """
    from src.api import search_cards
    resp = asyncio.run(search_cards(q="Mew 25", lang=None, limit=8, locale="en"))
    assert resp.results, "Expected non-empty results for 'Mew 25'"
    assert resp.results[0].name == "Mew", (
        f"Expected 'Mew' first, got {resp.results[0].name!r}"
    )


@pytest.mark.integration
def test_search_mew_25_query_interpretation(search_ready) -> None:
    """query_interpretation must carry the correct parsed fields for 'Mew 25'."""
    from src.api import search_cards
    resp = asyncio.run(search_cards(q="Mew 25", lang=None, limit=8, locale="en"))
    qi = resp.query_interpretation
    assert qi.parsed_number == 25
    assert qi.parsed_set_code == "MEW"
    assert qi.mode == "combo"


@pytest.mark.integration
def test_search_charizard_ex_number_and_total(search_ready) -> None:
    """
    'Charizard ex 199/165' must surface Charizard ex #199 first.
    'ex' must NOT prevent the name from matching or collapse to wrong card.
    """
    from src.api import search_cards
    resp = asyncio.run(search_cards(q="Charizard ex 199/165", lang=None, limit=8, locale="en"))
    assert resp.results, "Expected results for 'Charizard ex 199/165'"
    top = resp.results[0]
    assert top.name.startswith("Charizard ex"), (
        f"Expected name starting with 'Charizard ex', got {top.name!r}"
    )
    assert top.collector_number == 199, (
        f"Expected collector_number=199, got {top.collector_number}"
    )


@pytest.mark.integration
def test_search_fuzzy_fallback_wired_to_endpoint(search_ready) -> None:
    """
    Typo query 'pikchu' must return results via the fuzzy fallback.
    At least one result's name must contain 'Pikachu'.
    """
    from src.api import search_cards
    resp = asyncio.run(search_cards(q="pikchu", lang=None, limit=8, locale="en"))
    assert resp.results, "Expected results for 'pikchu' via fuzzy fallback"
    assert any(
        "pikachu" in r.name.lower() for r in resp.results
    ), f"No Pikachu in fuzzy results: {[r.name for r in resp.results]}"


@pytest.mark.integration
def test_search_number_only_all_match_collector_number(search_ready) -> None:
    """
    '096/080' is a pure number query. Every returned result must have
    collector_number == 96 (no stray cards from name matches).
    """
    from src.api import search_cards
    resp = asyncio.run(search_cards(q="096/080", lang=None, limit=8, locale="en"))
    assert resp.results, "Expected results for '096/080'"
    for r in resp.results:
        assert r.collector_number == 96, (
            f"Expected collector_number=96 for all results, got {r.collector_number} for {r.name!r}"
        )


@pytest.mark.integration
def test_search_nonsense_returns_empty_with_zero_count(search_ready) -> None:
    """'zzzznotacard' must return [] and result_count == 0."""
    from src.api import search_cards
    resp = asyncio.run(search_cards(q="zzzznotacard", lang=None, limit=8, locale="en"))
    assert resp.results == [], f"Expected empty results, got {resp.results}"
    assert resp.query_interpretation.result_count == 0


@pytest.mark.integration
def test_search_response_fields_populated(search_ready) -> None:
    """SQLCardMatch fields that must always be populated for a real hit."""
    from src.api import search_cards
    resp = asyncio.run(search_cards(q="Pikachu", lang=None, limit=5, locale="en"))
    assert resp.results, "Expected at least one result for 'Pikachu'"
    for r in resp.results:
        assert r.name, "name must be non-empty"
        assert r.tcgdex_id, "tcgdex_id must be non-empty"
        assert r.language in ("en", "ja", "zh-tw"), f"unexpected language: {r.language}"
