from __future__ import annotations

import pytest

from rfq.email_categories import (
    CATEGORY_PRIORITY,
    DEFAULT_CATEGORY,
    EMAIL_CATEGORY_CHOICES,
    category_priority,
    normalize_category,
    resolve_thread_category,
)


class TestPriorityLadder:
    def test_other_is_lowest_and_po_is_highest(self) -> None:
        assert CATEGORY_PRIORITY['other'] < CATEGORY_PRIORITY['rfq']
        assert CATEGORY_PRIORITY['rfq'] < CATEGORY_PRIORITY['quotation']
        assert CATEGORY_PRIORITY['quotation'] < CATEGORY_PRIORITY['po']

    def test_choices_cover_every_ranked_category(self) -> None:
        assert {value for value, _ in EMAIL_CATEGORY_CHOICES} == set(CATEGORY_PRIORITY)


class TestNormalizeCategory:
    @pytest.mark.parametrize('value', ['rfq', 'quotation', 'po', 'other'])
    def test_passes_known_values_through(self, value: str) -> None:
        assert normalize_category(value) == value

    def test_is_strict_about_the_four_known_values(self) -> None:
        # The classifier maps its raw enum labels ('PURCHASE_ORDER') to codes
        # before returning, so anything else is not a stored category and
        # must degrade rather than pass through.
        assert normalize_category('  PURCHASE_ORDER  ') == 'other'
        assert normalize_category('  RFQ  ') == 'rfq'

    @pytest.mark.parametrize('value', [None, '', '   ', 'nonsense', 'invoice'])
    def test_unknown_values_fall_back_to_other(self, value) -> None:
        assert normalize_category(value) == DEFAULT_CATEGORY


class TestCategoryPriority:
    def test_unknown_category_degrades_to_other_rank(self) -> None:
        assert category_priority('nonsense') == category_priority('other')

    def test_none_never_outranks_a_real_tag(self) -> None:
        assert category_priority(None) < category_priority('rfq')


class TestResolveThreadCategory:
    def test_empty_thread_is_other(self) -> None:
        assert resolve_thread_category([]) == 'other'

    def test_all_other_is_other(self) -> None:
        assert resolve_thread_category(['other', 'other']) == 'other'

    def test_single_message_passes_through(self) -> None:
        assert resolve_thread_category(['quotation']) == 'quotation'

    def test_po_beats_quotation(self) -> None:
        assert resolve_thread_category(['rfq', 'quotation', 'po']) == 'po'

    def test_quotation_beats_rfq(self) -> None:
        assert resolve_thread_category(['other', 'rfq', 'quotation']) == 'quotation'

    def test_rfq_beats_other(self) -> None:
        assert resolve_thread_category(['other', 'rfq']) == 'rfq'

    def test_po_wins_regardless_of_position(self) -> None:
        assert resolve_thread_category(['po', 'other', 'rfq']) == 'po'
        assert resolve_thread_category(['other', 'rfq', 'po']) == 'po'

    def test_repeated_tag_is_stable(self) -> None:
        # Every distinct category has a unique priority, so a 'tie' can only be
        # the same tag repeating. It must not drift.
        assert resolve_thread_category(['rfq', 'rfq']) == 'rfq'
        assert resolve_thread_category(['other', 'other', 'other']) == 'other'

    def test_unknown_values_never_win(self) -> None:
        assert resolve_thread_category(['invoice', 'nonsense', 'rfq']) == 'rfq'

    def test_all_unknown_becomes_other(self) -> None:
        assert resolve_thread_category(['invoice', 'nonsense']) == 'other'
