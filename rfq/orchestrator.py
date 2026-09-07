from __future__ import annotations

import logging
import os
from datetime import datetime, date
from typing import Dict, List, Optional

from django.conf import settings

from rfq.ai_classifier import AiEmailClassifier, ClassificationUnavailable
from rfq.attachment_service import AttachmentService
from rfq.data_extractors import OpenAiExtractor
from rfq.interfaces import (
    DataExtractor,
    EmailClassification,
    EmailClassifier,
    EmailMessage,
    EmailProvider,
    ExtractedRfqData,
)
from rfq.models import Order
from rfq.rfq_builder import RfqBuilder

logger = logging.getLogger(__name__)

# Extensions whose text content we extract to feed the AI.
DOCUMENT_EXTENSIONS = {'.pdf', '.docx', '.doc'}
# Extensions we keep temporarily so the AI can inspect them visually.
IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp', '.tiff', '.tif'}


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
        rfq_builder: Optional[RfqBuilder] = None,
        classifier: Optional[EmailClassifier] = None,
        attachment_service: Optional[AttachmentService] = None,
        user=None,
    ) -> None:
        self._email_provider = email_provider
        self._data_extractor = data_extractor or OpenAiExtractor()
        self._rfq_builder = rfq_builder or RfqBuilder()
        self._classifier = classifier or AiEmailClassifier()
        self._attachment_service = attachment_service or AttachmentService()
        self._user = user

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def poll_new_emails(self, days_back: int = 1) -> Dict:
        """
        Check the inbox for new emails, classify and process each one.
        Returns a summary dict.
        """
        # Fetch emails from last 1 day - category filter prevents reprocessing
        emails = self._email_provider.fetch_emails(
            limit=50,
            days_back=1,  # 1 day
        )
        if emails:
            logger.info('Discovered %d new email(s)', len(emails))
            for e in emails:
                try:
                    logger.info(
                        'Email discovered - id=%s subject=%s from=%s received_at=%s',
                        e.get('id', ''),
                        (e.get('subject') or '')[:200],
                        e.get('sender_email', ''),
                        e.get('received_at', ''),
                    )
                except Exception:
                    logger.exception('Failed to log discovered email')
        if not emails:
            logger.info('No emails found')
            return {'success': True, 'processed': 0, 'errors': []}

        processed = 0
        errors: List[str] = []

        for email in emails:
            msg_id = email.get('id', '')
            
            # Skip emails without a message ID
            if not msg_id:
                logger.warning('Email has no message ID, skipping')
                continue

            try:
                classification = self._classifier.classify(email)
            except ClassificationUnavailable as exc:
                logger.error('Classification unavailable for email %s: %s', msg_id, exc)
                self._create_classification_failure_task(email, exc)
                continue

            # Debug: snapshot every classified email for the frontend mailbox.
            self._record_debug_email(email, classification)

            if classification == 'other':
                logger.debug('Email %s classified as OTHER, skipping', msg_id)
                # Mark as processed so the poll loop doesn't re-fetch and
                # re-classify this email on every run.
                try:
                    self._email_provider.mark_as_processed(msg_id)
                except Exception:
                    logger.exception('Failed to mark email %s as processed', msg_id)
                continue

            try:
                order = self._process_one_email(email, classification)
                if order:
                    processed += 1
                    self._email_provider.mark_as_processed(msg_id)
                    # Attach the generated order to the debug snapshot.
                    self._link_debug_email(msg_id, order)
            except Exception as exc:
                # Check if this is a duplicate email error (unique constraint violation)
                if 'UNIQUE constraint failed: rfq_rfq.email_message_id' in str(exc):
                    logger.info('Email %s already processed by another worker, skipping', msg_id)
                else:
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
        try:
            classification = self._classifier.classify(email)
        except ClassificationUnavailable as exc:
            logger.error('Classification unavailable for email: %s', exc)
            self._create_classification_failure_task(email, exc)
            return None
        self._record_debug_email(email, classification)
        order = None
        if classification != 'other':
            order = self._process_one_email(email, classification)
            if order:
                self._link_debug_email(email.get('id', ''), order)
        return order

    # ------------------------------------------------------------------
    # Internal pipeline
    # ------------------------------------------------------------------

    def _record_debug_email(self, email: EmailMessage, classification: str) -> None:
        """Snapshot a classified email for the debug mailbox (best-effort)."""
        try:
            from rfq.email_debug import record_processed_email
            record_processed_email(email, classification, user=self._user)
        except Exception:
            logger.exception('Failed to record debug email snapshot')

    def _link_debug_email(self, message_id: str, order: Order) -> None:
        """Attach the produced order to the debug snapshot (best-effort)."""
        try:
            from rfq.models import ProcessedEmail
            ProcessedEmail.objects.filter(
                email_message_id=message_id,
            ).update(order=order)
        except Exception:
            logger.exception('Failed to link order to debug email snapshot')

    def _create_classification_failure_task(self, email: EmailMessage, exc: Exception) -> None:
        """
        Record a failed email classification as a pending Task so a human
        can review it. Deduplicated by Outlook conversation ID.
        """
        conversation_id = email.get('conversation_id', '')
        if not conversation_id:
            logger.warning(
                'No conversation ID on email %s; cannot deduplicate classification task',
                email.get('id', ''),
            )
        try:
            from tasks.models import Task
            if conversation_id:
                exists = Task.objects.filter(
                    status='pending',
                    description__contains=conversation_id,
                ).exists()
                if exists:
                    logger.info(
                        'Pending classification task already exists for conversation %s, skipping',
                        conversation_id,
                    )
                    return
            Task.objects.create(
                title='RFQ classification failed — review email',
                description=(
                    f'Email classification failed for subject "{email.get("subject", "")}" '
                    f'from {email.get("sender_email", "")}. '
                    f'Conversation ID: {conversation_id}. Error: {exc}'
                ),
                status='pending',
            )
            logger.warning(
                'Created classification-failure task for conversation %s', conversation_id,
            )
        except Exception as task_exc:
            logger.error('Failed to create classification-failure task: %s', task_exc)

    def _find_order_for_quotation(self, email: EmailMessage) -> Optional[Order]:
        """
        Extract RFQ number from quotation email subject/body and find existing order.
        Matches patterns like: RFQ-20260703-A1B2C3D4, RFQ-2026-001, RFQ 2026-001
        Falls back to matching by company name and recent orders.
        """
        import re
        from datetime import timedelta
        from django.utils import timezone
        
        subject = email.get('subject', '')
        body = email.get('body', '')
        sender_email = email.get('sender_email', '')
        
        logger.info('Searching for RFQ number in subject: %s', subject)
        
        # Try multiple patterns to match different RFQ number formats
        patterns = [
            r'(RFQ[-\s#.]?\d{8}[-\s#.]?[A-F0-9]{8})',  # RFQ-YYYYMMDD-XXXXXXXX (system format)
            r'(RFQ[-\s#.]?\d{2,4}[-\s#.]?\d{2,4})',    # RFQ-2026-001 or RFQ-232-7556
            r'(RFQ[-\s#.]?[A-F0-9-]+)',                 # RFQ-XXXXXXXX (fallback)
        ]
        
        # First try subject
        for pattern in patterns:
            rfq_match = re.search(pattern, subject, re.IGNORECASE)
            if rfq_match:
                rfq_number = rfq_match.group(1).replace(' ', '-').upper()
                logger.info('Extracted RFQ number from subject: %s', rfq_number)
                try:
                    order = Order.objects.get(rfq_number=rfq_number)
                    logger.info('Found existing Order %s for quotation email', order.rfq_number)
                    return order
                except Order.DoesNotExist:
                    logger.warning('Order %s not found for quotation email', rfq_number)
                    # Continue to try next pattern
                    continue
        
        # If not found in subject, try body
        logger.info('RFQ number not found in subject, searching in body...')
        for pattern in patterns:
            rfq_match = re.search(pattern, body, re.IGNORECASE)
            if rfq_match:
                rfq_number = rfq_match.group(1).replace(' ', '-').upper()
                logger.info('Extracted RFQ number from body: %s', rfq_number)
                try:
                    order = Order.objects.get(rfq_number=rfq_number)
                    logger.info('Found existing Order %s for quotation email', order.rfq_number)
                    return order
                except Order.DoesNotExist:
                    logger.warning('Order %s not found for quotation email', rfq_number)
                    continue
        
        # Fallback: Try matching by sender email and recent orders (last 30 days)
        logger.info('RFQ number not found in subject or body, trying fallback matching')
        thirty_days_ago = timezone.now() - timedelta(days=30)

        # Try matching by company_name first (quotation sender = supplier, RFQ sender = customer)
        company_match = re.search(r'company[:\s]+([^\n,;]+)', body[:500], re.IGNORECASE)
        company_name = company_match.group(1).strip() if company_match else ''
        if company_name and len(company_name) > 2:
            recent_by_company = Order.objects.filter(
                company_name__icontains=company_name,
                created_at__gte=thirty_days_ago,
            ).order_by('-created_at')
            if recent_by_company.exists():
                order = recent_by_company.first()
                logger.info('Found recent Order %s matching company "%s" (fallback)', order.rfq_number, company_name)
                return order

        # Then try by sender email matching contact
        recent_orders = Order.objects.filter(
            contact__email=sender_email,
            created_at__gte=thirty_days_ago,
        ).order_by('-created_at')
        
        if recent_orders.exists():
            order = recent_orders.first()
            logger.info('Found recent Order %s from sender %s (fallback match)', order.rfq_number, sender_email)
            return order

        # Finally try by rfq_number in subject
        for o in Order.objects.filter(created_at__gte=thirty_days_ago).only('rfq_number'):
            if o.rfq_number and o.rfq_number.replace('RFQ-', '') in subject:
                logger.info('Found Order %s by rfq_number in subject (fallback)', o.rfq_number)
                return o
        
        logger.warning('No matching order found for quotation email')
        return None

    def _process_one_email(self, email: EmailMessage, classification: EmailClassification) -> Optional[Order]:
        # Skip processing for OTHER classification (bounce notifications, spam, etc.)
        if classification == 'other':
            logger.info('Email classified as OTHER, skipping order creation')
            return None
        
        # Skip bounce/delivery failure notifications
        subject = (email.get('subject') or '').lower()
        body = (email.get('body') or '').lower()
        bounce_indicators = [
            'delivery failure', 'delivery status notification', 'undelivered',
            'bounce', 'returned', 'failed', 'not delivered', 'delivery failed'
        ]
        if any(indicator in subject or indicator in body for indicator in bounce_indicators):
            logger.info('Email appears to be a bounce/delivery failure notification, skipping')
            return None
        
        # For quotations and POs, try to find existing order by RFQ number in subject
        if classification in ['quotation', 'po']:
            order = self._find_order_for_quotation(email)
            if order:
                logger.info('Processing %s for existing Order %s', classification.upper(), order.rfq_number)
                if classification == 'quotation':
                    self._handle_quotation(email, order)
                else:
                    logger.info('=== PO EMAIL PROCESSING ===')
                    self._handle_po(email, order)
                return order
            else:
                logger.info('No existing Order found for %s, creating new order', classification)

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

        # Ensure order type is set correctly based on classification
        if classification == 'po':
            order.type = 'purchase_order'
            order.stage = 'order'
            order.save(update_fields=['type', 'stage'])
            logger.info('Set order type to purchase_order for new PO email')

        handler = {
            'rfq': self._handle_rfq_po,
            'po': self._handle_po,
            'quotation': self._handle_quotation,
        }.get(classification)

        if handler:
            handler(email, order)

        return order

    # ------------------------------------------------------------------
    # Per-classification handlers
    # ------------------------------------------------------------------

    def _gather_attachments(
        self,
        email: EmailMessage,
        order: Order,
    ) -> tuple[str, List[Dict]]:
        """
        Inspect the email's attachments and prepare them for AI extraction.

        - PDF / DOCX attachments are saved temporarily and their text is
          extracted, so it can be fed to the AI alongside the email body.
        - Image attachments are saved temporarily and returned as image
          payloads (bytes + media type) so the AI can inspect them visually.

        Returns ``(attachment_text, images)`` where ``images`` is a list of
        ``{'data': bytes, 'media_type': str, 'path': str, 'name': str}``.
        """
        if not email.get('has_attachments') and not email.get('attachments'):
            return '', []

        msg_id = email.get('id', '')
        attachments = email.get('attachments') or []

        if not attachments and msg_id:
            try:
                attachments = self._email_provider.get_attachments(msg_id)
            except Exception as exc:
                logger.error(
                    'Failed to fetch attachments for email %s: %s', msg_id, exc,
                )
                return '', []

        if not attachments:
            return '', []

        text_parts: List[str] = []
        images: List[Dict] = []

        for att in attachments:
            att_name = att.get('name', 'unnamed')
            content_type = (att.get('content_type') or '').lower()
            _, ext = os.path.splitext(att_name)
            ext = ext.lower()

            content = None
            if msg_id and att.get('id'):
                try:
                    content = self._email_provider.download_attachment(
                        msg_id, att['id'],
                    )
                except Exception as exc:
                    logger.error(
                        'Failed to download attachment %s: %s', att_name, exc,
                    )
            else:
                content = att.get('content')

            if not content:
                logger.warning(
                    'No content downloaded for attachment %s on email %s',
                    att_name, msg_id,
                )
                continue

            saved_path = self._attachment_service.save_temp(
                order.id, att_name, content,
            )

            if ext in IMAGE_EXTENSIONS or content_type.startswith('image/'):
                import mimetypes
                media_type = content_type or mimetypes.guess_type(att_name)[0] or 'image/png'
                images.append({
                    'data': content,
                    'media_type': media_type,
                    'path': saved_path or '',
                    'name': att_name,
                })
                logger.info(
                    'Kept image attachment %s temporarily for Order %s',
                    att_name, order.rfq_number,
                )
                continue

            if ext in DOCUMENT_EXTENSIONS and saved_path:
                from rfq.document_parsers import extract_text
                doc_text = extract_text(saved_path)
                if doc_text:
                    text_parts.append(
                        f'--- Attachment: {att_name} ---\n{doc_text}',
                    )
                    logger.info(
                        'Extracted text from attachment %s for Order %s (%d chars)',
                        att_name, order.rfq_number, len(doc_text),
                    )
                else:
                    logger.warning(
                        'No text extracted from attachment %s for Order %s',
                        att_name, order.rfq_number,
                    )
            else:
                logger.info(
                    'Skipping unsupported attachment %s (type=%s) for Order %s',
                    att_name, content_type, order.rfq_number,
                )

        return '\n\n'.join(text_parts), images

    def _handle_rfq_po(self, email: EmailMessage, order: Order) -> None:
        """
        Extract description, part number, quantity, delivery date
        from an RFQ email and save to the Order + OrderItem records.
        """
        text_to_extract = email.get('body', '')
        images: List[Dict] = []

        if email.get('has_attachments') or email.get('attachments'):
            attachment_text, images = self._gather_attachments(email, order)
            if attachment_text:
                text_to_extract = f'{text_to_extract}\n\n{attachment_text}'

        extracted = self._data_extractor.extract(
            text_to_extract,
            images=images or None,
            order_id=order.id,
        )

        if extracted:
            self._rfq_builder.update_from_extraction(order, extracted)
        else:
            logger.warning('Data extraction failed for Order %s', order.rfq_number)

        bc_enabled = getattr(settings, 'BC_SYNC_ENABLED', False)
        if bc_enabled:
            try:
                from rfq.business_central import create_quotation_in_bc
                result = create_quotation_in_bc(order)
            except Exception:
                pass

        order.stage = 'inquiry'
        order.save(update_fields=['stage'])

    def _handle_quotation(self, email: EmailMessage, order: Order) -> None:
        """
        Handle incoming supplier quotation.
        Extract item prices from email/attachment, match to RFQ items,
        update OrderItem records with supplier prices, set stage to negotiation.
        """
        text_to_extract = email.get('body', '')
        images: List[Dict] = []

        if email.get('has_attachments') or email.get('attachments'):
            attachment_text, images = self._gather_attachments(email, order)
            if attachment_text:
                text_to_extract = f'{text_to_extract}\n\n{attachment_text}'

        extracted = self._data_extractor.extract(
            text_to_extract,
            is_quotation=True,
            images=images or None,
            order_id=order.id,
        )

        if not extracted or not extracted.get('items'):
            logger.warning('No items extracted from quotation for Order %s', order.rfq_number)
            return

        existing_items = list(order.items.all())
        items_updated = 0
        items_created = 0

        for extracted_item in extracted.get('items', []):
            item_name = extracted_item.get('name', '').lower()
            item_code = extracted_item.get('part_number', '').lower()
            supplier_price = extracted_item.get('unit_price')
            supplier_total = extracted_item.get('total_price')

            matched_item = None
            for order_item in existing_items:
                if item_code and order_item.item_code and item_code == order_item.item_code.lower():
                    matched_item = order_item
                    break
                if item_name and item_name in order_item.item_name.lower():
                    matched_item = order_item
                    break

            if matched_item:
                if supplier_price is not None:
                    matched_item.unit_price = supplier_price
                if supplier_total is not None:
                    matched_item.total_price = supplier_total
                matched_item.save()
                items_updated += 1
            else:
                # Create a new item on the order from the extracted quotation data
                from rfq.models import OrderItem
                OrderItem.objects.create(
                    order=order,
                    item_name=extracted_item.get('name') or extracted_item.get('description', 'Unknown Item'),
                    item_code=extracted_item.get('part_number', ''),
                    description=extracted_item.get('description') or extracted_item.get('name', ''),
                    quantity=extracted_item.get('quantity', 1),
                    unit=extracted_item.get('unit', 'PC'),
                    unit_price=supplier_price,
                    total_price=supplier_total,
                )
                items_created += 1

        if items_updated > 0 or items_created > 0:
            order.stage = 'negotiation'
            order.save(update_fields=['stage'])
            logger.info(
                'RFQ %s UPDATED: %d items updated, %d items created from quotation',
                order.rfq_number, items_updated, items_created
            )
        else:
            logger.warning('No items were updated/created from quotation for Order %s', order.rfq_number)

        bc_enabled = getattr(settings, 'BC_SYNC_ENABLED', False)
        if bc_enabled:
            try:
                from rfq.business_central import create_quotation_in_bc
                create_quotation_in_bc(order)
            except Exception:
                pass

    def _handle_po(self, email: EmailMessage, order: Order) -> None:
        """
        Handle customer Purchase Order.
        Extract PO data, update order with PO details, set stage to order,
        and create Purchase Order in Business Central.
        """
        text_to_extract = email.get('body', '')
        images: List[Dict] = []

        po_number = None
        import re
        po_match = re.search(r'PO\s*[-:]?\s*([A-Z0-9-]+)', email.get('subject', '') + ' ' + email.get('body', ''), re.IGNORECASE)
        if po_match:
            po_number = po_match.group(1)

        if email.get('has_attachments') or email.get('attachments'):
            attachment_text, images = self._gather_attachments(email, order)
            if attachment_text:
                text_to_extract = f'{text_to_extract}\n\n{attachment_text}'

        extracted = self._data_extractor.extract(
            text_to_extract,
            images=images or None,
            order_id=order.id,
        )

        if extracted:
            self._rfq_builder.update_from_extraction(order, extracted)
        else:
            logger.warning('Data extraction failed for Order %s', order.rfq_number)

        if po_number:
            order.po_number = po_number

        order.type = 'purchase_order'
        order.stage = 'order'
        order.save(update_fields=['type', 'stage', 'po_number'])

        bc_enabled = getattr(settings, 'BC_SYNC_ENABLED', False)
        if bc_enabled:
            try:
                from rfq.business_central import convert_quote_to_sales_order
                convert_quote_to_sales_order(order)

                from rfq.business_central import create_purchase_order_in_bc
                create_purchase_order_in_bc(order)
            except Exception:
                pass

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
