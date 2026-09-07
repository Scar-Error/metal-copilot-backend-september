from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

import pytest

from rfq.interfaces import ExtractedRfqData
from rfq.models import Order, OrderItem
from rfq.rfq_builder import (
    COMMENT_ITEM_CODE,
    ITEM_FIELD_MAX_LEN,
    RfqBuilder,
)


@pytest.mark.django_db
class TestRfqBuilderItems:
    @staticmethod
    def _build(
        items: List[Dict[str, Any]],
        notes: Optional[str] = None,
    ) -> Order:
        order = Order.objects.create(
            rfq_number='RFQ-BUILDER-1',
            company_name='Acme',
        )
        data = ExtractedRfqData(
            company_name='Acme',
            items_description='parts',
            quantity=1,
            items=items,
        )
        if notes is not None:
            data['notes'] = notes
        RfqBuilder().update_from_extraction(order, data)
        return order

    def test_notes_saved_to_order(self) -> None:
        order = self._build(
            [
                {
                    'name': 'Gearbox assembly',
                    'part_number': 'GB-100',
                    'quantity': 3,
                    'unit': 'pcs',
                },
            ],
            notes='Deliver on wooden pallets, FOB port.',
        )
        order.refresh_from_db()
        assert order.notes == 'Deliver on wooden pallets, FOB port.'

    def test_unit_normalized_to_allowed_values(self) -> None:
        order = self._build([
            {'name': 'a', 'part_number': 'P1', 'quantity': 1, 'unit': 'PC'},
            {'name': 'b', 'part_number': 'P2', 'quantity': 1, 'unit': 'Kg'},
            {'name': 'c', 'part_number': 'P3', 'quantity': 1, 'unit': 'LITER'},
            {'name': 'd', 'part_number': 'P4', 'quantity': 1, 'unit': 'basket'},
            {'name': 'e', 'part_number': 'P5', 'quantity': 1, 'unit': None},
        ])
        units = {item.item_name: item.unit for item in order.items.all()}
        assert units['a'] == 'pc'
        assert units['b'] == 'kg'
        assert units['c'] == 'ltr'
        assert units['d'] == 'pc'
        assert units['e'] == 'pc'

    def test_part_number_truncated_to_max_len(self) -> None:
        long_part = 'X' * 150
        order = self._build([
            {'name': 'Part', 'part_number': long_part, 'quantity': 1, 'unit': 'pc'},
        ])
        item = order.items.first()
        assert len(item.item_code) == ITEM_FIELD_MAX_LEN
        assert item.item_code == 'X' * ITEM_FIELD_MAX_LEN

    def test_long_description_split_into_comment_items(self) -> None:
        desc = 'A' * 98 + 'B' * 98 + 'C' * 54  # 250 chars total
        order = self._build([
            {
                'name': desc,
                'part_number': 'COMBO-1',
                'quantity': 4,
                'unit': 'pcs',
                'unit_price': 12.5,
                'total_price': 50.0,
            },
        ])
        items = list(order.items.all())
        chunks = [desc[i:i + ITEM_FIELD_MAX_LEN] for i in range(0, len(desc), ITEM_FIELD_MAX_LEN)]
        assert len(items) == len(chunks) == 3

        primary = items[0]
        assert primary.item_name == chunks[0]
        assert primary.item_code == 'COMBO-1'
        assert primary.description == chunks[0]
        assert primary.quantity == 4
        assert primary.unit == 'pcs'
        assert primary.unit_price == 12.5
        assert primary.total_price == 50.0

        for comment, chunk in zip(items[1:], chunks[1:]):
            assert comment.item_code == COMMENT_ITEM_CODE
            assert comment.item_name == chunk
            assert comment.description == chunk
            assert comment.quantity == 0
            assert comment.unit == ''
            assert comment.unit_price is None
            assert comment.total_price is None
            assert comment.extraction_confidence is None

    def test_primary_item_name_falls_back_to_description(self) -> None:
        order = self._build([
            {
                'description': 'Steel widget',
                'part_number': 'WGT-100',
                'item_code': 'WGT-100',
                'quantity': 100,
                'unit': 'pcs',
            },
        ])
        item = order.items.first()
        assert item.item_code == 'WGT-100'
        assert item.item_name == 'Steel widget'
        assert item.description == 'Steel widget'
        assert item.quantity == 100
        assert item.unit == 'pcs'
        assert item.unit_price is None
        assert item.total_price is None


@pytest.mark.django_db
class TestOrderItemSerializer:
    @staticmethod
    def _order() -> Order:
        return Order.objects.create(
            rfq_number=f'RFQ-SER-{uuid.uuid4().hex[:8]}',
            company_name='Acme',
        )

    def test_rejects_unit_outside_allowed(self) -> None:
        from rfq.serializers import OrderItemSerializer
        ser = OrderItemSerializer(data={
            'order': self._order().id,
            'item_name': 'x',
            'item_code': 'y',
            'quantity': 1,
            'unit': 'tons',
        })
        assert ser.is_valid() is False
        assert 'unit' in ser.errors
        assert 'pc, pcs, kg, ltr' in str(ser.errors['unit'])

    def test_normalizes_unit_case(self) -> None:
        from rfq.serializers import OrderItemSerializer
        ser = OrderItemSerializer(data={
            'order': self._order().id,
            'item_name': 'x',
            'item_code': 'y',
            'quantity': 1,
            'unit': 'PC',
        })
        assert ser.is_valid() is True
        assert ser.validated_data['unit'] == 'pc'

    def test_allows_empty_unit(self) -> None:
        from rfq.serializers import OrderItemSerializer
        ser = OrderItemSerializer(data={
            'order': self._order().id,
            'item_name': 'x',
            'item_code': 'y',
            'quantity': 1,
            'unit': '',
        })
        assert ser.is_valid() is True

    def test_rejects_item_name_over_99(self) -> None:
        from rfq.serializers import OrderItemSerializer
        ser = OrderItemSerializer(data={
            'order': self._order().id,
            'item_name': 'X' * 100,
            'item_code': 'y',
            'quantity': 1,
            'unit': 'pc',
        })
        assert ser.is_valid() is False
        assert 'item_name' in ser.errors

    def test_rejects_item_code_over_99(self) -> None:
        from rfq.serializers import OrderItemSerializer
        ser = OrderItemSerializer(data={
            'order': self._order().id,
            'item_name': 'x',
            'item_code': 'Y' * 100,
            'quantity': 1,
            'unit': 'pc',
        })
        assert ser.is_valid() is False
        assert 'item_code' in ser.errors