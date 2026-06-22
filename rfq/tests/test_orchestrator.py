from __future__ import annotations

from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import pytest

from rfq.interfaces import EmailClassification, EmailMessage, EmailProvider, ExtractedRfqData
from rfq.orchestrator import (
    EmailClassifier,
    AiEmailClassifier,
    EmailIngestionOrchestrator,
    RfqDetector,
)
from rfq.rfq_builder import RfqBuilder
from rfq.attachment_service import AttachmentService


class FakeEmailProvider:
    """In-memory EmailProvider for testing."""

    def __init__(self) -> None:
        self._sent: List[Dict[str, Any]] = []
        self._processed: set = set()

    def fetch_emails(
        self, folder: str = 'Inbox', limit: int = 50, days_back: int = 7,
    ) -> List[EmailMessage]:
        return [
            EmailMessage(
                id='msg-1',
                subject='RFQ for widgets',
                sender_name='Alice',
                sender_email='alice@example.com',
                received_at='2026-06-21T10:00:00Z',
                body='We need 100 widgets delivered by July.',
                has_attachments=False,
                attachments=[],
            ),
        ]

    def get_email_by_id(self, email_id: str) -> Optional[EmailMessage]:
        return None

    def download_attachment(self, email_id: str, attachment_id: str) -> Optional[bytes]:
        return None

    def get_attachments(self, email_id: str) -> list:
        return []

    def send_email(self, to: str, subject: str, body: str, content_type: str = 'HTML') -> bool:
        self._sent.append({'to': to, 'subject': subject})
        return True

    def mark_as_processed(self, email_id: str) -> bool:
        self._processed.add(email_id)
        return True

    def get_user_email(self) -> str:
        return 'bot@example.com'


class FakeExtractor:
    def extract(self, text: str, source_label: str = '') -> Optional[ExtractedRfqData]:
        return ExtractedRfqData(
            company_name='Test Corp',
            description='100 widgets',
            items_description='100 widgets',
            quantity=100,
            specifications='Steel',
            delivery_date='2026-07-15',
            confidence_score=0.85,
            items=[
                {
                    'description': 'Steel widget',
                    'part_number': 'WGT-100',
                    'item_code': 'WGT-100',
                    'quantity': 100,
                    'unit': 'pcs',
                },
            ],
        )


@pytest.mark.django_db
class TestEmailIngestionOrchestrator:
    def test_poll_new_emails_creates_order(self) -> None:
        provider = FakeEmailProvider()
        orchestrator = EmailIngestionOrchestrator(
            email_provider=provider,
            data_extractor=FakeExtractor(),
            fallback_extractor=FakeExtractor(),
            rfq_builder=RfqBuilder(),
            attachment_service=AttachmentService(),
            classifier=EmailClassifier(),
        )

        result = orchestrator.poll_new_emails()
        assert result['success'] is True
        assert result['processed'] == 1

    def test_deduplication_by_email_id(self) -> None:
        provider = FakeEmailProvider()
        orchestrator = EmailIngestionOrchestrator(
            email_provider=provider,
            data_extractor=FakeExtractor(),
            fallback_extractor=FakeExtractor(),
            rfq_builder=RfqBuilder(),
            attachment_service=AttachmentService(),
            classifier=EmailClassifier(),
        )

        r1 = orchestrator.poll_new_emails()
        assert r1['processed'] == 1

        r2 = orchestrator.poll_new_emails()
        assert r2['processed'] == 0

    def test_poll_new_emails_sets_email_classification(self) -> None:
        provider = FakeEmailProvider()
        orchestrator = EmailIngestionOrchestrator(
            email_provider=provider,
            data_extractor=FakeExtractor(),
            fallback_extractor=FakeExtractor(),
            rfq_builder=RfqBuilder(),
            attachment_service=AttachmentService(),
            classifier=EmailClassifier(),
        )

        result = orchestrator.poll_new_emails()
        assert result['processed'] == 1

        from rfq.models import Order
        order = Order.objects.first()
        assert order is not None
        assert order.email_classification == 'rfq_po'

    def test_skips_other_classified_emails(self) -> None:
        class OtherClassifier:
            def classify(self, email: EmailMessage) -> EmailClassification:
                return 'other'

        provider = FakeEmailProvider()
        orchestrator = EmailIngestionOrchestrator(
            email_provider=provider,
            data_extractor=FakeExtractor(),
            fallback_extractor=FakeExtractor(),
            rfq_builder=RfqBuilder(),
            attachment_service=AttachmentService(),
            classifier=OtherClassifier(),
        )

        result = orchestrator.poll_new_emails()
        assert result['processed'] == 0

    def test_processes_quotation_classified_emails(self) -> None:
        class QuotationClassifier:
            def classify(self, email: EmailMessage) -> EmailClassification:
                return 'quotation'

        provider = FakeEmailProvider()
        orchestrator = EmailIngestionOrchestrator(
            email_provider=provider,
            data_extractor=FakeExtractor(),
            fallback_extractor=FakeExtractor(),
            rfq_builder=RfqBuilder(),
            attachment_service=AttachmentService(),
            classifier=QuotationClassifier(),
        )

        result = orchestrator.poll_new_emails()
        assert result['processed'] == 1

        from rfq.models import Order
        order = Order.objects.first()
        assert order is not None
        assert order.email_classification == 'quotation'

    def test_extracted_data_no_pricing(self) -> None:
        provider = FakeEmailProvider()
        orchestrator = EmailIngestionOrchestrator(
            email_provider=provider,
            data_extractor=FakeExtractor(),
            fallback_extractor=FakeExtractor(),
            rfq_builder=RfqBuilder(),
            attachment_service=AttachmentService(),
            classifier=EmailClassifier(),
        )

        result = orchestrator.poll_new_emails()
        assert result['processed'] == 1

        from rfq.models import Order
        order = Order.objects.first()
        assert order is not None
        assert order.items_description == '100 widgets'
        assert order.quantity == 100
        assert order.budget is None

        items = order.items.all()
        assert items.count() == 1
        item = items[0]
        assert item.item_code == 'WGT-100'
        assert item.description == 'Steel widget'
        assert item.quantity == 100
        assert item.unit_price is None
        assert item.total_price is None


@pytest.mark.django_db
class TestEmailClassifier:
    def test_classifies_rfq_keywords(self) -> None:
        classifier = EmailClassifier()
        email = EmailMessage(
            subject='RFQ for steel pipes',
            body='Please provide a quotation for 500 units.',
        )
        assert classifier.classify(email) == 'rfq_po'

    def test_classifies_po_keywords(self) -> None:
        classifier = EmailClassifier()
        email = EmailMessage(
            subject='Purchase Order #12345',
            body='Please process the attached purchase order.',
        )
        assert classifier.classify(email) == 'rfq_po'

    def test_classifies_quotation_keywords(self) -> None:
        classifier = EmailClassifier()
        email = EmailMessage(
            subject='Quotation for Widgets',
            body='Please find our price quote attached.',
        )
        assert classifier.classify(email) == 'quotation'

    def test_classifies_other(self) -> None:
        classifier = EmailClassifier()
        email = EmailMessage(
            subject='Meeting tomorrow',
            body='Can we reschedule the meeting?',
        )
        assert classifier.classify(email) == 'other'

    def test_empty_body_classifies_other(self) -> None:
        classifier = EmailClassifier()
        email = EmailMessage(subject='', body='')
        assert classifier.classify(email) == 'other'


@pytest.mark.django_db
class TestRfqDetectorLegacy:
    """Ensure backward-compatible binary detector still works."""

    def test_is_rfq_returns_true_for_rfq_keywords(self) -> None:
        detector = RfqDetector(keywords=['rfq', 'purchase order'])
        email = EmailMessage(
            subject='RFQ for parts',
            body='Please quote.',
        )
        assert detector.is_rfq(email) is True

    def test_is_rfq_returns_false_for_other(self) -> None:
        detector = RfqDetector(keywords=['rfq', 'purchase order'])
        email = EmailMessage(
            subject='Meeting',
            body='Hello',
        )
        assert detector.is_rfq(email) is False
