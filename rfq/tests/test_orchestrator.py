from __future__ import annotations

from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import pytest

from rfq.ai_classifier import AiEmailClassifier, ClassificationUnavailable
from rfq.attachment_service import AttachmentService, LocalFileStorage
from rfq.interfaces import (
    AttachmentData,
    EmailClassification,
    EmailMessage,
    EmailProvider,
    ExtractedRfqData,
)
from rfq.orchestrator import EmailIngestionOrchestrator
from rfq.rfq_builder import RfqBuilder


class FakeEmailProvider:
    """In-memory EmailProvider for testing."""

    def __init__(self) -> None:
        self._processed: set = set()

    def fetch_emails(
        self, folder: str = 'Inbox', limit: int = 50, days_back: int = 7,
    ) -> List[EmailMessage]:
        emails = [
            EmailMessage(
                id='msg-1',
                subject='RFQ for widgets',
                sender_name='Alice',
                sender_email='alice@example.com',
                received_at='2026-06-21T10:00:00Z',
                body='We need 100 widgets delivered by July.',
                conversation_id='conv-1',
            ),
        ]
        return [e for e in emails if e['id'] not in self._processed]

    def get_email_by_id(self, email_id: str) -> Optional[EmailMessage]:
        return None

    def mark_as_processed(self, email_id: str) -> bool:
        self._processed.add(email_id)
        return True

    def get_user_email(self) -> str:
        return 'bot@example.com'


class FakeExtractor:
    def extract(
        self,
        text: str,
        source_label: str = '',
        is_quotation: bool = False,
        images: Optional[List[Dict[str, Any]]] = None,
        order_id: Optional[int] = None,
    ) -> Optional[ExtractedRfqData]:
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


class RfqClassifier:
    def classify(self, email: EmailMessage) -> EmailClassification:
        return 'rfq'


@pytest.mark.django_db
class TestEmailIngestionOrchestrator:
    def test_poll_new_emails_creates_order(self) -> None:
        provider = FakeEmailProvider()
        orchestrator = EmailIngestionOrchestrator(
            email_provider=provider,
            data_extractor=FakeExtractor(),
            rfq_builder=RfqBuilder(),
            classifier=RfqClassifier(),
        )

        result = orchestrator.poll_new_emails()
        assert result['success'] is True
        assert result['processed'] == 1

    def test_deduplication_by_email_id(self) -> None:
        provider = FakeEmailProvider()
        orchestrator = EmailIngestionOrchestrator(
            email_provider=provider,
            data_extractor=FakeExtractor(),
            rfq_builder=RfqBuilder(),
            classifier=RfqClassifier(),
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
            rfq_builder=RfqBuilder(),
            classifier=RfqClassifier(),
        )

        result = orchestrator.poll_new_emails()
        assert result['processed'] == 1

        from rfq.models import Order
        order = Order.objects.first()
        assert order is not None
        assert order.email_classification == 'rfq'

    def test_skips_other_classified_emails(self) -> None:
        class OtherClassifier:
            def classify(self, email: EmailMessage) -> EmailClassification:
                return 'other'

        provider = FakeEmailProvider()
        orchestrator = EmailIngestionOrchestrator(
            email_provider=provider,
            data_extractor=FakeExtractor(),
            rfq_builder=RfqBuilder(),
            classifier=OtherClassifier(),
        )

        result = orchestrator.poll_new_emails()
        assert result['processed'] == 0

    def test_other_classified_emails_marked_processed(self) -> None:
        class OtherClassifier:
            def __init__(self) -> None:
                self.calls = 0

            def classify(self, email: EmailMessage) -> EmailClassification:
                self.calls += 1
                return 'other'

        provider = FakeEmailProvider()
        classifier = OtherClassifier()
        orchestrator = EmailIngestionOrchestrator(
            email_provider=provider,
            data_extractor=FakeExtractor(),
            rfq_builder=RfqBuilder(),
            classifier=classifier,
        )

        result = orchestrator.poll_new_emails()
        assert result['processed'] == 0
        assert 'msg-1' in provider._processed
        assert classifier.calls == 1

        # Second poll must not re-fetch/re-classify the same email (no repeat API call).
        r2 = orchestrator.poll_new_emails()
        assert r2['processed'] == 0
        assert classifier.calls == 1

    def test_processes_quotation_classified_emails(self) -> None:
        class QuotationClassifier:
            def classify(self, email: EmailMessage) -> EmailClassification:
                return 'quotation'

        provider = FakeEmailProvider()
        orchestrator = EmailIngestionOrchestrator(
            email_provider=provider,
            data_extractor=FakeExtractor(),
            rfq_builder=RfqBuilder(),
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
            rfq_builder=RfqBuilder(),
            classifier=RfqClassifier(),
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

    def test_creates_deduped_task_on_classification_failure(self) -> None:
        class FailingClassifier:
            def classify(self, email: EmailMessage) -> EmailClassification:
                raise ClassificationUnavailable('no api key')

        provider = FakeEmailProvider()
        orchestrator = EmailIngestionOrchestrator(
            email_provider=provider,
            data_extractor=FakeExtractor(),
            rfq_builder=RfqBuilder(),
            classifier=FailingClassifier(),
        )

        result = orchestrator.poll_new_emails()
        assert result['processed'] == 0
        assert 'msg-1' not in provider._processed

        from tasks.models import Task
        assert Task.objects.count() == 1
        task = Task.objects.first()
        assert task.title == 'RFQ classification failed — review email'
        assert 'conv-1' in task.description

        result = orchestrator.poll_new_emails()
        assert result['processed'] == 0
        assert Task.objects.count() == 1


@pytest.mark.django_db
class TestAiEmailClassifier:
    @staticmethod
    def _make_provider(text: str) -> MagicMock:
        provider = MagicMock()
        provider.name = 'anthropic'
        provider.complete.return_value = text
        return provider

    def test_classifies_rfq(self) -> None:
        classifier = AiEmailClassifier(provider=self._make_provider('RFQ'))
        email = EmailMessage(subject='RFQ for parts', body='Please quote.')
        assert classifier.classify(email) == 'rfq'

    def test_classifies_po(self) -> None:
        classifier = AiEmailClassifier(provider=self._make_provider('PURCHASE_ORDER'))
        email = EmailMessage(subject='PO-123', body='Please process the order.')
        assert classifier.classify(email) == 'po'

    def test_classifies_quotation(self) -> None:
        classifier = AiEmailClassifier(provider=self._make_provider('QUOTATION'))
        email = EmailMessage(subject='Quotation', body='Prices attached.')
        assert classifier.classify(email) == 'quotation'

    def test_classifies_other(self) -> None:
        classifier = AiEmailClassifier(provider=self._make_provider('OTHER'))
        email = EmailMessage(subject='Meeting', body='Can we reschedule?')
        assert classifier.classify(email) == 'other'

    def test_raises_on_client_failure(self) -> None:
        provider = MagicMock()
        provider.name = 'anthropic'
        provider.complete.side_effect = Exception('boom')
        classifier = AiEmailClassifier(provider=provider)
        email = EmailMessage(subject='x', body='y')
        with pytest.raises(ClassificationUnavailable):
            classifier.classify(email)


class AttachmentProvider:
    """In-memory EmailProvider that serves attachments."""

    def __init__(self, attachments: List[Dict[str, Any]]) -> None:
        self.attachments = attachments
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
                conversation_id='conv-1',
                has_attachments=True,
                attachments=[
                    AttachmentData(
                        id=a['id'],
                        name=a['name'],
                        size=len(a['content']),
                        content_type=a['content_type'],
                    )
                    for a in self.attachments
                ],
            ),
        ]

    def get_email_by_id(self, email_id: str) -> Optional[EmailMessage]:
        return None

    def get_attachments(self, email_id: str) -> List[AttachmentData]:
        return [
            AttachmentData(
                id=a['id'],
                name=a['name'],
                size=len(a['content']),
                content_type=a['content_type'],
            )
            for a in self.attachments
        ]

    def download_attachment(self, email_id: str, attachment_id: str) -> Optional[bytes]:
        for a in self.attachments:
            if a['id'] == attachment_id:
                return a['content']
        return None

    def mark_as_processed(self, email_id: str) -> bool:
        self._processed.add(email_id)
        return True

    def get_user_email(self) -> str:
        return 'bot@example.com'


class RecordingExtractor:
    """Records what the orchestrator passed to the AI extractor."""

    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []

    def extract(
        self,
        text: str,
        source_label: str = '',
        is_quotation: bool = False,
        images: Optional[List[Dict[str, Any]]] = None,
        order_id: Optional[int] = None,
    ) -> Optional[ExtractedRfqData]:
        self.calls.append({
            'text': text,
            'images': images,
            'is_quotation': is_quotation,
            'order_id': order_id,
        })
        return ExtractedRfqData(
            company_name='Test Corp',
            description='100 widgets',
            items_description='100 widgets',
            quantity=100,
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
class TestAttachmentProcessing:
    @staticmethod
    def _make_docx_bytes(text: str) -> bytes:
        from docx import Document
        import io
        doc = Document()
        doc.add_paragraph(text)
        buf = io.BytesIO()
        doc.save(buf)
        return buf.getvalue()

    @staticmethod
    def _make_png_bytes() -> bytes:
        from PIL import Image
        import io
        img = Image.new('RGB', (10, 10), color=(73, 109, 137))
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        return buf.getvalue()

    def _orchestrator(self, provider, extractor, tmp_path):
        storage = LocalFileStorage(base_dir=str(tmp_path))
        return EmailIngestionOrchestrator(
            email_provider=provider,
            data_extractor=extractor,
            rfq_builder=RfqBuilder(),
            classifier=RfqClassifier(),
            attachment_service=AttachmentService(storage=storage),
        )

    def test_rfq_docx_attachment_text_fed_to_extractor(self, tmp_path) -> None:
        docx_bytes = self._make_docx_bytes('IS-100 Sensor, quantity 25, delivery 2026-08-01')
        provider = AttachmentProvider([
            {
                'id': 'att-1',
                'name': 'rfq.docx',
                'content_type': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                'content': docx_bytes,
            },
        ])
        extractor = RecordingExtractor()
        orchestrator = self._orchestrator(provider, extractor, tmp_path)

        result = orchestrator.poll_new_emails()
        assert result['processed'] == 1

        assert len(extractor.calls) == 1
        assert 'IS-100 Sensor, quantity 25' in extractor.calls[0]['text']
        assert 'We need 100 widgets' in extractor.calls[0]['text']

        from rfq.models import Order
        order = Order.objects.first()
        assert order is not None
        from rfq.models import OrderAiMetadata
        ai_meta = OrderAiMetadata.objects.get(order=order)
        assert ai_meta.processed is True
        assert order.items_description == '100 widgets'
        assert (tmp_path / 'temp_attachments' / str(order.id) / 'rfq.docx').exists()

    def test_rfq_image_attachment_kept_temporarily(self, tmp_path) -> None:
        png_bytes = self._make_png_bytes()
        provider = AttachmentProvider([
            {
                'id': 'att-1',
                'name': 'drawing.png',
                'content_type': 'image/png',
                'content': png_bytes,
            },
        ])
        extractor = RecordingExtractor()
        orchestrator = self._orchestrator(provider, extractor, tmp_path)

        result = orchestrator.poll_new_emails()
        assert result['processed'] == 1

        assert len(extractor.calls) == 1
        images = extractor.calls[0]['images']
        assert images is not None and len(images) == 1
        assert images[0]['media_type'] == 'image/png'
        assert images[0]['data'] == png_bytes
        assert images[0]['name'] == 'drawing.png'

        from rfq.models import Order
        order = Order.objects.first()
        assert (tmp_path / 'temp_attachments' / str(order.id) / 'drawing.png').exists()

    def test_rfq_docx_and_image_attachment_both_handled(self, tmp_path) -> None:
        docx_bytes = self._make_docx_bytes('CM-250 Control Module, quantity 5')
        png_bytes = self._make_png_bytes()
        provider = AttachmentProvider([
            {
                'id': 'att-1',
                'name': 'specs.docx',
                'content_type': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                'content': docx_bytes,
            },
            {
                'id': 'att-2',
                'name': 'drawing.png',
                'content_type': 'image/png',
                'content': png_bytes,
            },
        ])
        extractor = RecordingExtractor()
        orchestrator = self._orchestrator(provider, extractor, tmp_path)

        result = orchestrator.poll_new_emails()
        assert result['processed'] == 1

        assert len(extractor.calls) == 1
        call = extractor.calls[0]
        assert 'CM-250 Control Module, quantity 5' in call['text']
        assert call['images'] is not None and len(call['images']) == 1
        assert call['images'][0]['media_type'] == 'image/png'

    def test_email_without_attachments_no_extractor_images(self, tmp_path) -> None:
        provider = FakeEmailProvider()
        extractor = RecordingExtractor()
        orchestrator = self._orchestrator(provider, extractor, tmp_path)

        result = orchestrator.poll_new_emails()
        assert result['processed'] == 1
        assert len(extractor.calls) == 1
        assert extractor.calls[0]['images'] is None

    def test_quotation_bc_sync_respects_flag(self, tmp_path) -> None:
        from django.test import override_settings
        from unittest.mock import patch

        class QuotationClassifier:
            def classify(self, email: EmailMessage) -> EmailClassification:
                return 'quotation'

        provider = AttachmentProvider([])
        extractor = RecordingExtractor()
        orchestrator = EmailIngestionOrchestrator(
            email_provider=provider,
            data_extractor=extractor,
            rfq_builder=RfqBuilder(),
            classifier=QuotationClassifier(),
            attachment_service=AttachmentService(
                storage=LocalFileStorage(base_dir=str(tmp_path)),
            ),
        )

        with override_settings(BC_SYNC_ENABLED=False), patch(
            'rfq.business_central.create_quotation_in_bc',
        ) as mock_bc:
            result = orchestrator.poll_new_emails()
            assert result['processed'] == 1
            mock_bc.assert_not_called()

        with override_settings(BC_SYNC_ENABLED=True), patch(
            'rfq.business_central.create_quotation_in_bc',
            return_value=True,
        ) as mock_bc:
            result = orchestrator.poll_new_emails()
            assert result['processed'] == 1
            mock_bc.assert_called_once()

    @pytest.mark.django_db
class TestDebugEmailMailbox:
    def test_poll_records_processed_email_snapshot(self) -> None:
        provider = FakeEmailProvider()
        orchestrator = EmailIngestionOrchestrator(
            email_provider=provider,
            data_extractor=FakeExtractor(),
            rfq_builder=RfqBuilder(),
            classifier=RfqClassifier(),
        )

        result = orchestrator.poll_new_emails()
        assert result['processed'] == 1

        from rfq.models import ProcessedEmail
        snap = ProcessedEmail.objects.get(email_message_id='msg-1')
        assert snap.classification == 'rfq'
        assert snap.conversation_id == 'conv-1'
        assert snap.order is not None

    def test_process_single_email_records_snapshot(self) -> None:
        email = EmailMessage(
            id='msg-single',
            subject='RFQ for pumps',
            sender_name='Bob',
            sender_email='bob@example.com',
            received_at='2026-06-22T09:00:00Z',
            body='Need 5 pumps.',
            conversation_id='conv-9',
        )
        orchestrator = EmailIngestionOrchestrator(
            email_provider=FakeEmailProvider(),
            data_extractor=FakeExtractor(),
            rfq_builder=RfqBuilder(),
            classifier=RfqClassifier(),
        )

        order = orchestrator.process_single_email(email)
        assert order is not None

        from rfq.models import ProcessedEmail
        snap = ProcessedEmail.objects.get(email_message_id='msg-single')
        assert snap.conversation_id == 'conv-9'
        assert snap.order_id == order.id

    def test_mailbox_endpoint_groups_by_conversation(self) -> None:
        from rest_framework.test import APIClient
        from django.contrib.auth import get_user_model

        from rfq.models import ProcessedEmail

        User = get_user_model()
        user = User.objects.create_user(username='mailboxuser', password='pass123')

        ProcessedEmail.objects.create(
            email_message_id='m1',
            conversation_id='thread-a',
            subject='RFQ parts',
            sender_name='Alice',
            sender_email='alice@example.com',
            received_at='2026-07-01T10:00:00Z',
            body='body1',
            classification='rfq',
        )
        ProcessedEmail.objects.create(
            email_message_id='m2',
            conversation_id='thread-a',
            subject='Quotation for RFQ parts',
            sender_name='Supplies Inc',
            sender_email='sales@supplies.com',
            received_at='2026-07-02T10:00:00Z',
            body='body2',
            classification='quotation',
        )
        ProcessedEmail.objects.create(
            email_message_id='m3',
            conversation_id='thread-b',
            subject='PO-9001',
            sender_name='Buyer Co',
            sender_email='buyer@example.com',
            received_at='2026-07-03T10:00:00Z',
            body='body3',
            classification='po',
        )

        client = APIClient()
        client.force_authenticate(user=user)

        res = client.get('/api/rfq/monitor/emails/mailbox/')
        assert res.status_code == 200
        data = res.json()
        assert data['success'] is True
        assert data['count'] == 2

        threads = {t['conversation_id']: t for t in data['threads']}
        thread_a = threads['thread-a']
        assert thread_a['email_count'] == 2
        assert thread_a['primary_classification'] == 'quotation'
        assert set(thread_a['classifications']) == {'rfq', 'quotation'}
        assert len(thread_a['emails']) == 2

        assert threads['thread-b']['primary_classification'] == 'po'

        # Tag filter keeps only matching threads.
        res_tag = client.get('/api/rfq/monitor/emails/mailbox/?tag=po')
        assert res_tag.status_code == 200
        tag_data = res_tag.json()
        assert tag_data['count'] == 1
        assert tag_data['threads'][0]['conversation_id'] == 'thread-b'
