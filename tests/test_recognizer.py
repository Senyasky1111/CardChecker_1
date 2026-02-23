"""
Unit tests for the CardRecognizer and CardMarket URL generation.

These tests use mocked FAISS index and CLIP model so they run
without downloading real data or model weights.
"""

import numpy as np
import pytest
from unittest.mock import MagicMock
from PIL import Image

from src.recognizer import CardRecognizer
from src.cardmarket_url import (
    card_url,
    search_url,
    _clean_card_name,
)


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------

FAKE_CARDS = {
    100: {
        "id_product": 100,
        "name": "Pikachu [Thunder Shock | Electro Ball]",
        "expansion_name": "Prismatic Evolutions",
        "expansion_id": 6259,
        "price_trend": 5.50,
        "price_low": 3.00,
    },
    200: {
        "id_product": 200,
        "name": "Charizard ex [Blazing Destruction]",
        "expansion_name": "Scarlet & Violet",
        "expansion_id": 5318,
        "price_trend": 42.0,
        "price_low": 35.0,
    },
}

FAKE_CARD_IDS = [100, 200]


def _make_recognizer() -> CardRecognizer:
    """Build a CardRecognizer with mocked internals."""
    mock_index = MagicMock()
    mock_index.search.return_value = (
        np.array([[0.95, 0.80]], dtype=np.float32),
        np.array([[0, 1]], dtype=np.int64),
    )

    metadata = {
        "card_ids": FAKE_CARD_IDS,
        "cards_by_idx": {0: FAKE_CARDS[100], 1: FAKE_CARDS[200]},
        "cards_by_id": FAKE_CARDS,
        "model_name": "openai/clip-vit-base-patch32",
        "embedding_dim": 512,
        "total_cards": 2,
    }

    mock_model = MagicMock()
    mock_processor = MagicMock()

    return CardRecognizer(
        index=mock_index,
        metadata=metadata,
        model=mock_model,
        processor=mock_processor,
        device="cpu",
    )


# ------------------------------------------------------------------
# CardRecognizer tests
# ------------------------------------------------------------------


class TestCardRecognizer:
    def setup_method(self):
        self.rec = _make_recognizer()
        self.rec._embed_image = MagicMock(
            return_value=np.random.randn(512).astype(np.float32)
        )

    def test_identify_returns_correct_structure(self):
        image = Image.new("RGB", (224, 224), color="red")
        results = self.rec.identify(image, k=2)

        assert len(results) == 2
        first = results[0]
        assert first["id_product"] == 100
        assert first["name"] == "Pikachu [Thunder Shock | Electro Ball]"
        assert first["confidence"] == pytest.approx(0.95, abs=0.01)
        assert "cardmarket_url" in first
        assert "cardmarket.com" in first["cardmarket_url"]

    def test_identify_respects_k(self):
        image = Image.new("RGB", (224, 224))
        results = self.rec.identify(image, k=1)
        assert len(results) == 1

    def test_identify_from_path(self, tmp_path):
        img_path = tmp_path / "test_card.jpg"
        Image.new("RGB", (100, 140), color="blue").save(img_path)
        results = self.rec.identify(str(img_path), k=2)
        assert len(results) >= 1

    def test_identify_from_ndarray(self):
        arr = np.zeros((224, 224, 3), dtype=np.uint8)
        results = self.rec.identify(arr, k=2)
        assert len(results) >= 1

    def test_multi_crop_returns_results(self):
        image = Image.new("RGB", (400, 560), color="green")
        results = self.rec.identify_multi_crop(image, k=2)
        assert len(results) >= 1
        assert results[0]["confidence"] >= 0.0

    def test_prices_in_results(self):
        image = Image.new("RGB", (224, 224))
        results = self.rec.identify(image, k=2)
        assert results[0]["price_trend"] == 5.50
        assert results[0]["price_low"] == 3.00

    def test_deduplication(self):
        """If the index returns the same card_id twice, deduplicate."""
        self.rec.index.search.return_value = (
            np.array([[0.95, 0.90]], dtype=np.float32),
            np.array([[0, 0]], dtype=np.int64),
        )
        image = Image.new("RGB", (224, 224))
        results = self.rec.identify(image, k=5)
        assert len(results) == 1

    def test_cardmarket_url_uses_id_product(self):
        image = Image.new("RGB", (224, 224))
        results = self.rec.identify(image, k=2)
        url = results[0]["cardmarket_url"]
        # Should use idProduct redirect since fake card has id_product=100
        assert "?idProduct=100" in url

    def test_cardmarket_url_locale(self):
        image = Image.new("RGB", (224, 224))
        results = self.rec.identify(image, k=2, locale="it")
        url = results[0]["cardmarket_url"]
        assert "/it/Pokemon/" in url

    def test_get_card_by_id(self):
        card = self.rec.get_card(100)
        assert card is not None
        assert card["name"] == "Pikachu [Thunder Shock | Electro Ball]"

    def test_get_card_not_found(self):
        card = self.rec.get_card(999)
        assert card is None

    def test_backward_compat_old_metadata(self):
        """Test that old metadata format (cards keyed by product ID) still works."""
        mock_index = MagicMock()
        mock_index.search.return_value = (
            np.array([[0.90]], dtype=np.float32),
            np.array([[0]], dtype=np.int64),
        )
        old_metadata = {
            "card_ids": [100],
            "cards": {100: FAKE_CARDS[100]},
            "model_name": "openai/clip-vit-base-patch32",
        }
        rec = CardRecognizer(
            index=mock_index,
            metadata=old_metadata,
            model=MagicMock(),
            processor=MagicMock(),
            device="cpu",
        )
        rec._embed_image = MagicMock(
            return_value=np.random.randn(512).astype(np.float32)
        )
        results = rec.identify(Image.new("RGB", (224, 224)), k=1)
        assert len(results) == 1
        assert results[0]["id_product"] == 100


# ------------------------------------------------------------------
# CardMarket URL tests
# ------------------------------------------------------------------


class TestCardMarketURL:
    def test_clean_card_name_removes_abilities(self):
        assert _clean_card_name("Pikachu [Thunder Shock | Electro Ball]") == "Pikachu"

    def test_clean_card_name_removes_set_numbers(self):
        assert _clean_card_name("Charizard (25/102)") == "Charizard"

    def test_clean_card_name_removes_parenthetical_notes(self):
        assert _clean_card_name("Charizard ex (Special Art Rare)") == "Charizard ex"

    def test_clean_card_name_preserves_plain_name(self):
        assert _clean_card_name("Mega Gengar ex") == "Mega Gengar ex"

    def test_search_url_basic(self):
        url = search_url("Pikachu")
        assert url == (
            "https://www.cardmarket.com/en/Pokemon/Products/Search"
            "?searchString=Pikachu"
        )

    def test_search_url_with_expansion(self):
        url = search_url("Pikachu", expansion_id=6259)
        assert "idExpansion=6259" in url
        assert "idCategory=51" in url

    def test_search_url_with_locale(self):
        url = search_url("Pikachu", locale="it")
        assert "/it/Pokemon/" in url

    def test_search_url_encodes_spaces(self):
        url = search_url("Mega Gengar ex")
        assert "Mega+Gengar+ex" in url

    def test_card_url_uses_id_product_redirect(self):
        card = {
            "name": "Pikachu",
            "id_product": 794329,
            "expansion_id": 1523,
        }
        url = card_url(card)
        assert "?idProduct=794329" in url
        assert "Search" not in url

    def test_card_url_uses_cm_id_product_redirect(self):
        card = {
            "name": "Pikachu",
            "cm_id_product": 794329,
        }
        url = card_url(card)
        assert "?idProduct=794329" in url

    def test_card_url_falls_back_to_search(self):
        card = {
            "name": "Pikachu [Thunder Shock]",
            "expansion_id": 1523,
        }
        url = card_url(card)
        assert "Search" in url
        assert "searchString=Pikachu" in url

    def test_card_url_no_expansion(self):
        card = {"name": "Unknown Card"}
        url = card_url(card)
        assert "searchString=Unknown+Card" in url
        assert "idExpansion" not in url

    def test_card_url_locale_with_id(self):
        card = {"id_product": 123456}
        url = card_url(card, locale="de")
        assert "/de/Pokemon/Products?idProduct=123456" in url
