from __future__ import annotations

import pytest
from django.db.utils import IntegrityError

from rfq.models import Order, OrderItem, OrderAnalytics


@pytest.mark.django_db
class TestOrderModel:
    def test_create_minimal(self) -> None:
        order = Order.objects.create(
            rfq_number='RFQ-20260621-TEST0001',
            company_name='Test Corp',
        )
        assert order.pk is not None
        assert str(order) == 'RFQ-20260621-TEST0001 - Test Corp'
        assert order.type == 'rfq'

    def test_rfq_number_unique(self) -> None:
        Order.objects.create(
            rfq_number='RFQ-DUP',
            company_name='A',
        )
        with pytest.raises(IntegrityError):
            Order.objects.create(
                rfq_number='RFQ-DUP',
                company_name='B',
            )

    def test_email_message_id_dedup(self) -> None:
        Order.objects.create(
            rfq_number='RFQ-001',
            company_name='X',
            email_message_id='msg-abc-123',
        )
        with pytest.raises(IntegrityError):
            Order.objects.create(
                rfq_number='RFQ-002',
                company_name='Y',
                email_message_id='msg-abc-123',
            )


@pytest.mark.django_db
class TestOrderItemModel:
    def test_create_item(self) -> None:
        order = Order.objects.create(
            rfq_number='RFQ-20260621-ITEMTST',
            company_name='T',
        )
        item = OrderItem.objects.create(
            order=order,
            item_name='Widget',
            quantity=10,
            unit='pcs',
            unit_price=25.00,
            total_price=250.00,
        )
        assert str(item) == 'Widget (Qty: 10)'


@pytest.mark.django_db
class TestOrderAnalyticsModel:
    def test_date_unique(self) -> None:
        OrderAnalytics.objects.create(date='2026-06-21')
        with pytest.raises(IntegrityError):
            OrderAnalytics.objects.create(date='2026-06-21')
