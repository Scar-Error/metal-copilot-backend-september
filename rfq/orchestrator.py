from __future__ import annotations

import logging
from datetime import datetime, date
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
            msg_id = email.get('id', '')
            # Skip emails that already exist
            if msg_id in existing_ids:
                logger.debug('Email %s is new (already in system), skipping', msg_id)
                continue

            classification = self._classifier.classify(email)
            if classification == 'other':
                logger.debug('Email %s classified as OTHER, skipping', msg_id)
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
        logger.info('='*80)
        logger.info('Processing RFQ/PO email for Order %s', order.rfq_number)
        logger.info('Email Details:')
        logger.info('  - Subject: %s', email.get('subject', 'N/A')[:100])
        logger.info('  - Sender: %s', email.get('sender_email', 'N/A'))
        logger.info('  - Has Attachments: %s', email.get('has_attachments', False))
        logger.info('='*80)
        
        text_to_extract = email.get('body', '')
        logger.info('Email body length: %d chars', len(text_to_extract))

        if email.get('has_attachments'):
            attachments = self._email_provider.get_attachments(email['id'])
            logger.info('Found %d attachments', len(attachments))
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
                        # Always use attachment text if available (it likely has the full table)
                        if file_text:
                            text_to_extract = file_text
                            logger.info('Using attachment text for extraction. Attachment: %s', att.get('name', 'unknown'))
                            logger.info('Text length: %d chars, first 500 chars: %s', len(file_text), file_text[:500])
                            break

        logger.info('Starting data extraction from text (length: %d chars)', len(text_to_extract))
        extracted = self._data_extractor.extract(text_to_extract)
        if extracted is None:
            logger.info('Primary extractor failed, trying fallback extractor')
            extracted = self._fallback_extractor.extract(text_to_extract)

        if extracted:
            logger.info('Data extraction successful, updating order')
            self._rfq_builder.update_from_extraction(order, extracted)
        else:
            logger.warning('Data extraction failed for Order %s', order.rfq_number)

        if not order.supplier and not order.supplier_email:
            try:
                from tasks.services import TaskService
                TaskService.create_supplier_assignment_task(order)
                logger.info('Created supplier assignment task for Order %s', order.rfq_number)
            except Exception as exc:
                logger.error(
                    'Failed to create supplier-assignment task for Order %s: %s',
                    order.rfq_number, exc,
                )

        # Sync to Business Central (optional - skip if BC is not configured or unreachable)
        bc_enabled = getattr(settings, 'BC_SYNC_ENABLED', True)
        logger.info('BC Sync Enabled: %s', bc_enabled)
        if bc_enabled:
            try:
                logger.info('Starting BC sync for Order %s', order.rfq_number)
                from rfq.business_central import create_quotation_in_bc
                result = create_quotation_in_bc(order)
                if result:
                    order.status = 'processing'
                    order.save(update_fields=['status'])
                    logger.info('BC sync complete for Order %s', order.rfq_number)
                else:
                    logger.warning('BC sync failed for Order %s (order saved in local system)', order.rfq_number)
            except Exception as exc:
                logger.warning(
                    'Failed to sync to BC for Order %s: %s (order saved in local system)',
                    order.rfq_number, exc,
                )
        else:
            logger.info('BC sync disabled for Order %s', order.rfq_number)

        if order.supplier_email or order.supplier:
            logger.info('Dispatching to supplier for Order %s', order.rfq_number)
            from rfq.tasks import dispatch_to_supplier
            dispatch_to_supplier.delay(order.id)
        else:
            logger.info('No supplier assigned for Order %s, skipping dispatch', order.rfq_number)

    def _handle_quotation(self, email: EmailMessage, order: Order) -> None:
        """
        Handle incoming supplier quotation.
        Extract item prices from email/attachment, match to RFQ items,
        update OrderItem records with supplier prices, and set stage to negotiation.
        """
        logger.info('='*80)
        logger.info('Processing supplier quotation for Order %s', order.rfq_number)
        logger.info('Email Details:')
        logger.info('  - Subject: %s', email.get('subject', 'N/A')[:100])
        logger.info('  - Sender: %s', email.get('sender_email', 'N/A'))
        logger.info('  - Has Attachments: %s', email.get('has_attachments', False))
        logger.info('='*80)

        text_to_extract = email.get('body', '')
        logger.info('Email body length: %d chars', len(text_to_extract))

        # Extract text from attachments if present
        if email.get('has_attachments'):
            attachments = self._email_provider.get_attachments(email['id'])
            logger.info('Found %d attachments', len(attachments))
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
                        if file_text:
                            text_to_extract = file_text
                            logger.info(
                                'Extracted text from attachment %s for quotation (length: %d chars)',
                                att.get('name', 'unknown'), len(file_text)
                            )
                            break

        # Extract prices using AI or keyword extractor
        logger.info('Starting price extraction from quotation text (length: %d chars)', len(text_to_extract))
        extracted = self._data_extractor.extract(text_to_extract)
        if extracted is None:
            logger.info('Primary extractor failed, trying fallback extractor')
            extracted = self._fallback_extractor.extract(text_to_extract)

        if not extracted or not extracted.get('items'):
            logger.warning(
                'No items extracted from quotation for Order %s',
                order.rfq_number
            )
            return
        
        logger.info('Extracted %d items from quotation', len(extracted.get('items', [])))

        # Match extracted items to existing OrderItems
        items_updated = 0
        for extracted_item in extracted.get('items', []):
            item_name = extracted_item.get('name', '').lower()
            item_code = extracted_item.get('part_number', '').lower()
            supplier_price = extracted_item.get('unit_price')

            if not supplier_price:
                logger.debug('Skipping item with no supplier price: %s', extracted_item.get('name', 'unknown'))
                continue

            # Try to match by item code first, then by name
            matched_item = None
            for order_item in order.items.all():
                if item_code and order_item.item_code and item_code == order_item.item_code.lower():
                    matched_item = order_item
                    logger.info('Matched by item code: %s', item_code)
                    break
                if item_name and item_name in order_item.item_name.lower():
                    matched_item = order_item
                    logger.info('Matched by item name: %s', item_name)
                    break

            if matched_item:
                matched_item.supplier_price = supplier_price
                matched_item.save()
                items_updated += 1
                logger.info(
                    'Updated supplier price for item %s: %s (old: %s)',
                    matched_item.item_name, supplier_price, matched_item.unit_price
                )
            else:
                logger.warning(
                    'Could not match extracted item "%s" (code: %s) to any OrderItem',
                    extracted_item.get('name', 'unknown'), extracted_item.get('part_number', 'N/A')
                )

        if items_updated > 0:
            order.stage = 'negotiation'
            order.save(update_fields=['stage'])
            logger.info(
                'Updated %d item prices from quotation for Order %s, stage set to negotiation',
                items_updated, order.rfq_number
            )
        else:
            logger.warning(
                'No items were updated from quotation for Order %s',
                order.rfq_number
            )

        # Sync to Business Central
        logger.info('Starting BC sync for quotation Order %s', order.rfq_number)
        try:
            from rfq.business_central import create_quotation_in_bc
            result = create_quotation_in_bc(order)
            if result:
                logger.info('BC sync complete for Order %s (quotation)', order.rfq_number)
            else:
                logger.error('BC sync failed for Order %s (quotation)', order.rfq_number)
        except Exception as exc:
            logger.error(
                'Failed to sync to BC for Order %s: %s',
                order.rfq_number, exc,
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
