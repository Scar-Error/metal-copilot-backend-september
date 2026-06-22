from __future__ import annotations

import pytest

from rfq.data_extractors import KeywordExtractor


class TestKeywordExtractor:
    def test_company_from_keyword(self) -> None:
        text = 'from: Acme Corporation\nitems: steel bolts\n'
        result = KeywordExtractor().extract(text)
        assert result is not None
        assert 'acme' in result['company_name'].lower()

    def test_company_vendor(self) -> None:
        text = 'Vendor: XYZ Supplies Ltd\n'
        result = KeywordExtractor().extract(text)
        assert result is not None
        assert 'xyz' in result['company_name'].lower()

    def test_items_description(self) -> None:
        text = 'Items: Industrial pumps and valves\n'
        result = KeywordExtractor().extract(text)
        assert result is not None
        assert 'pumps' in result['items_description'].lower()

    def test_empty_text_returns_none(self) -> None:
        result = KeywordExtractor().extract('')
        assert result is None

    def test_confidence_score(self) -> None:
        text = 'from: Test Co\nitems: widgets'
        result = KeywordExtractor().extract(text)
        assert result is not None
        assert result['confidence_score'] == 0.5

    def test_no_match_uses_defaults(self) -> None:
        text = 'random text without keywords'
        result = KeywordExtractor().extract(text)
        assert result is not None
        assert result['company_name'] == 'Unknown Company'
        assert result['items_description'] == 'Various items'
