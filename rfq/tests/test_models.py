from __future__ import annotations

import pytest
from django.db.utils import IntegrityError

from rfq.models import Order, OrderItem, OrderAnalytics


@pytest.mark.django_db
class TestOrderModel:
    def test_create_minimal(self) -> None:
        order = Order.objects.create(
            email_subject='RFQ for parts',
            email_sender='buyer@example.com',
            email_received_at='2026-06-21 10:00:00+00',
            rfq_number='RFQ-20260621-TEST0001',
            company_name='Test Corp',
        )
        assert order.pk is not None
        assert str(order) == 'RFQ-20260621-TEST0001 - Test Corp'
        assert order.status == 'pending'
        assert order.priority == 'medium'
        assert order.stage == 'inquiry'
        assert order.type == 'rfq'

    def test_rfq_number_unique(self) -> None:
        Order.objects.create(
            email_subject='RFQ A',
            email_sender='a@example.com',
            email_received_at='2026-06-21 10:00:00+00',
            rfq_number='RFQ-DUP',
            company_name='A',
        )
        with pytest.raises(IntegrityError):
            Order.objects.create(
                email_subject='RFQ B',
                email_sender='b@example.com',
                email_received_at='2026-06-21 10:00:00+00',
                rfq_number='RFQ-DUP',
                company_name='B',
            )

    def test_email_message_id_dedup(self) -> None:
        Order.objects.create(
            email_subject='RFQ',
            email_sender='x@example.com',
            email_received_at='2026-06-21 10:00:00+00',
            rfq_number='RFQ-001',
            company_name='X',
            email_message_id='msg-abc-123',
        )
        Order.objects.create(
            email_subject='RFQ 2',
            email_sender='y@example.com',
            email_received_at='2026-06-21 10:00:00+00',
            rfq_number='RFQ-002',
            company_name='Y',
            email_message_id='msg-abc-123',
        )
        assert Order.objects.filter(email_message_id='msg-abc-123').count() == 2


@pytest.mark.django_db
class TestOrderItemModel:
    def test_create_item(self) -> None:
        order = Order.objects.create(
            email_subject='RFQ',
            email_sender='s@example.com',
            email_received_at='2026-06-21 10:00:00+00',
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
