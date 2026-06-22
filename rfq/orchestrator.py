from __future__ import annotations

import logging
from typing import Dict, List, Optional

from django.conf import settings

from rfq.attachment_service import AttachmentService
from rfq.data_extractors import OpenAiExtractor, KeywordExtractor
from rfq.document_parsers import extract_text, get_parser
from rfq.interfaces import (
    DataExtractor,
    EmailClassification,
    EmailClassifier,
    EmailMessage,
    EmailProvider,
    ExtractedRfqData,
    FileStorage,
)
from rfq.models import Order
from rfq.rfq_builder import RfqBuilder

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Backward-compatible RFQ detectors (delegated to the new classifier)
# ---------------------------------------------------------------------------

class RfqDetector:
    """Check whether an email is RFQ-related (legacy binary detector)."""

    def __init__(self, keywords: Optional[List[str]] = None) -> None:
        self._keywords = keywords or list(getattr(settings, 'RFQ_KEYWORDS', []))

    def is_rfq(self, email: EmailMessage) -> bool:
        subject = (email.get('subject') or '').lower()
        body = (email.get('body') or '').lower()
        return any(
            kw.lower() in subject or kw.lower() in body
            for kw in self._keywords
        )


class AiRfqDetector:
    """LLM-based RFQ detection (legacy binary detector)."""

    def is_rfq(self, email: EmailMessage) -> bool:
        classification = AiEmailClassifier().classify(email)
        return classification == 'rfq_po'


# ---------------------------------------------------------------------------
# New three-way email classifier
# ---------------------------------------------------------------------------

class EmailClassifier:
    """Keyword-based three-way email classifier."""

    RFQ_KEYWORDS = [
        'rfq', 'request for quotation', 'request for quote',
        'purchase order', 'po number', 'po#', 'quotation request',
        'quote request', 'request for proposal', 'rfp',
        'request for bid', 'bid request', 'tender',
    ]

    QUOTATION_KEYWORDS = [
        'quotation', 'quote', 'price list', 'pricelist',
        'proposal', 'offer', 'estimate', 'pricing',
        'price quote', 'budgetary quote',
    ]

    def classify(self, email: EmailMessage) -> EmailClassification:
        subject = (email.get('subject') or '').lower()
        body = (email.get('body') or '').lower()
        combined = f'{subject} {body}'

        if any(kw in combined for kw in self.RFQ_KEYWORDS):
            return 'rfq_po'

        if any(kw in combined for kw in self.QUOTATION_KEYWORDS):
            return 'quotation'

        return 'other'


class AiEmailClassifier:
    """LLM-based three-way email classifier with keyword fallback."""

    def classify(self, email: EmailMessage) -> EmailClassification:
        subject = (email.get('subject') or '').lower()
        body = (email.get('body') or '').lower()[:2000]
        text = f'Subject: {subject}\n\nBody: {body}'

        from rfq.data_extractors import OpenAiExtractor
        extractor = OpenAiExtractor()
        if not extractor._client:
            return EmailClassifier().classify(email)

        prompt = (
            'Classify the following email as one of:\n'
            '- RFQ_PO: A customer requesting a quotation or placing a purchase order\n'
            '- QUOTATION: A supplier sending a price quote, proposal, or quotation\n'
            '- OTHER: Anything else\n\n'
            'Reply with only a single word: RFQ_PO, QUOTATION, or OTHER.\n\n'
            f'{text}'
        )
        try:
            response = extractor._client.chat.completions.create(
                model=getattr(settings, 'OPENAI_MODEL', 'gpt-3.5-turbo'),
                messages=[
                    {
                        'role': 'system',
                        'content': (
                            'You classify emails as RFQ_PO, QUOTATION, or OTHER. '
                            'Reply with only one word.'
                        ),
                    },
                    {'role': 'user', 'content': prompt},
                ],
                temperature=0,
                max_tokens=10,
            )
            answer = response.choices[0].message.content.strip().upper()
            if answer == 'RFQ_PO':
                return 'rfq_po'
            if answer == 'QUOTATION':
                return 'quotation'
            return 'other'
        except Exception as exc:
            logger.warning('AI classification failed, falling back to keywords: %s', exc)
            return EmailClassifier().classify(email)


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

class EmailIngestionOrchestrator:
    """
    Thin coordinator for the email → Order ingestion pipeline.

    Dependencies are injected so the class is testable without
    real Microsoft / OpenAI / file-system access.
    """

    def __init__(
        self,
        email_provider: EmailProvider,
        data_extractor: Optional[DataExtractor] = None,
        fallback_extractor: Optional[DataExtractor] = None,
        rfq_builder: Optional[RfqBuilder] = None,
        attachment_service: Optional[AttachmentService] = None,
        classifier: Optional[EmailClassifier] = None,
        use_ai_classification: bool = True,
    ) -> None:
        self._email_provider = email_provider
        self._data_extractor = data_extractor or OpenAiExtractor()
        self._fallback_extractor = fallback_extractor or KeywordExtractor()
        self._rfq_builder = rfq_builder or RfqBuilder()
        self._attachment_service = attachment_service or AttachmentService()
        self._classifier = classifier or (AiEmailClassifier() if use_ai_classification else EmailClassifier())

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def poll_new_emails(self, days_back: int = 1) -> Dict:
        """
        Check the inbox for new emails, classify and process each one.
        Returns a summary dict.
        """
        emails = self._email_provider.fetch_emails(
            limit=50,
            days_back=days_back,
        )
        if not emails:
            logger.info('No emails found')
            return {'success': True, 'processed': 0, 'errors': []}

        processed = 0
        errors: List[str] = []
        existing_ids = set(
            Order.objects.exclude(email_message_id='')
            .values_list('email_message_id', flat=True)
        )

        for email in emails:
            classification = self._classifier.classify(email)
            if classification == 'other':
                logger.debug('Email %s classified as OTHER, skipping', email.get('id', ''))
                continue

            msg_id = email.get('id', '')
            if msg_id in existing_ids:
                logger.debug('Email %s already processed, skipping', msg_id)
                continue

            try:
                order = self._process_one_email(email, classification)
                if order:
                    processed += 1
                    self._email_provider.mark_as_processed(msg_id)
            except Exception as exc:
                logger.exception(
                    'Error processing email %s', msg_id,
                )
                errors.append(str(exc))

        logger.info('Processed %d emails (%d errors)', processed, len(errors))
        return {
            'success': True,
            'processed': processed,
            'errors': errors,
        }

    def process_single_email(self, email: EmailMessage) -> Optional[Order]:
        """Process one email independently (useful for on-demand API calls)."""
        classification = self._classifier.classify(email)
        if classification == 'other':
            logger.debug('Email classified as OTHER, skipping')
            return None
        return self._process_one_email(email, classification)

    # ------------------------------------------------------------------
    # Internal pipeline
    # ------------------------------------------------------------------

    def _process_one_email(self, email: EmailMessage, classification: EmailClassification) -> Optional[Order]:
        order = self._rfq_builder.create_from_email(
            subject=email.get('subject', ''),
            sender_email=email.get('sender_email', ''),
            sender_name=email.get('sender_name', ''),
            received_at=email.get('received_at'),
            body=email.get('body', ''),
            source='email',
            email_message_id=email.get('id', ''),
            email_classification=classification,
        )

        handler = {
            'rfq_po': self._handle_rfq_po,
            'quotation': self._handle_quotation,
        }.get(classification)

        if handler:
            handler(email, order)

        return order

    # ------------------------------------------------------------------
    # Per-classification handlers
    # ------------------------------------------------------------------

    def _handle_rfq_po(self, email: EmailMessage, order: Order) -> None:
        """
        Extract description, part number, quantity, delivery date
        from an RFQ/PO email and save to the Order + OrderItem records.
        """
        text_to_extract = email.get('body', '')

        if email.get('has_attachments'):
            attachments = self._email_provider.get_attachments(email['id'])
            for att in attachments:
                content = self._email_provider.download_attachment(
                    email['id'], att['id'],
                )
                if content:
                    saved = self._attachment_service.save_attachment(
                        order, att, content,
                    )
                    if saved:
                        file_text = extract_text(saved.file_path)
                        if file_text and not _has_extracted_items(text_to_extract, self._data_extractor):
                            text_to_extract = file_text

        extracted = self._data_extractor.extract(text_to_extract)
        if extracted is None:
            extracted = self._fallback_extractor.extract(text_to_extract)

        if extracted:
            self._rfq_builder.update_from_extraction(order, extracted)

        if not order.supplier and not order.supplier_email:
            try:
                from tasks.services import TaskService
                TaskService.create_supplier_assignment_task(order)
            except Exception as exc:
                logger.error(
                    'Failed to create supplier-assignment task for Order %s: %s',
                    order.rfq_number, exc,
                )

        if order.supplier_email or order.supplier:
            from rfq.tasks import dispatch_to_supplier
            dispatch_to_supplier.delay(order.id)

    def _handle_quotation(self, email: EmailMessage, order: Order) -> None:
        """
        Stub: handle incoming supplier quotation.
        Will be implemented in a future phase to extract pricing
        and match items against the original RFQ.
        """
        logger.info(
            'Quotation received for Order %s — handler not yet implemented',
            order.rfq_number,
        )

    def _handle_other(self, email: EmailMessage, order: Order) -> None:
        """Stub: handle other email types (future use)."""
        logger.info(
            'Other email received for Order %s — handler not yet implemented',
            order.rfq_number,
        )


def _has_extracted_items(text: str, extractor: DataExtractor) -> bool:
    """Check if the body text already contains extractable items."""
    if not text.strip():
        return False
    result = extractor.extract(text[:1000])
    if result and result.get('items'):
        return True
    return False
