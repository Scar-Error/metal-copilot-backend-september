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
    """Keyword-based four-way email classifier."""

    RFQ_KEYWORDS = [
        'rfq', 'request for quotation', 'request for quote',
        'quotation request', 'quote request', 'request for proposal', 'rfp',
        'request for bid', 'bid request', 'tender', 'inquiry',
    ]

    PO_KEYWORDS = [
        'purchase order', 'po number', 'po#', 'p.o.', 'order confirmation',
        'we are pleased to place the following order', 'we order',
    ]

    QUOTATION_KEYWORDS = [
        'quotation', 'quote', 'price list', 'pricelist',
        'proposal', 'offer', 'estimate', 'pricing',
        'price quote', 'budgetary quote', 'thank you for your inquiry',
        'please find our quotation',
    ]

    def classify(self, email: EmailMessage) -> EmailClassification:
        subject = (email.get('subject') or '').lower()
        body = (email.get('body') or '').lower()
        combined = f'{subject} {body}'

        # Check for PO first (more specific)
        if any(kw in combined for kw in self.PO_KEYWORDS):
            return 'po'

        # Check for Quotation BEFORE RFQ (supplier quotations may reference RFQ in subject)
        if any(kw in combined for kw in self.QUOTATION_KEYWORDS):
            return 'quotation'

        # Check for RFQ
        if any(kw in combined for kw in self.RFQ_KEYWORDS):
            return 'rfq'

        return 'other'


class AiEmailClassifier:
    """LLM-based four-way email classifier with keyword fallback and hybrid signals."""

    def classify(self, email: EmailMessage) -> EmailClassification:
        subject = (email.get('subject') or '').lower()
        body = (email.get('body') or '').lower()
        full_body = body[:5000]  # Use more body for signal detection
        
        # If email has attachments, assume it's a quotation (suppliers send quotations with attachments)
        # This is a heuristic since we can't extract attachment text without email_provider
        has_attachments = email.get('has_attachments', False)
        logger.info('Email classification - has_attachments: %s', has_attachments)
        
        text = f'Subject: {subject}\n\nBody: {full_body}'
        
        logger.info('Email classification - Subject: %s', subject[:100])

        # HYBRID SIGNAL 1: Check for pricing data (strong quotation signal)
        pricing_indicators = [
            'unit price', 'unit_price', 'unit $', 'price:', '$', 'total price',
            'pricing', 'price list', 'quotation', 'quote', 'proposal',
            'thank you for your inquiry', 'please find our quotation',
            'we are pleased to quote', 'our quotation', 'price per',
            'cost per', 'rate', 'amount', 'invoice', 'bill'
        ]
        has_pricing = any(indicator in full_body for indicator in pricing_indicators)
        
        # Additional: Check for currency patterns (numbers with $)
        import re
        currency_pattern = r'\$\s*\d+\.?\d*'
        has_currency = bool(re.search(currency_pattern, full_body))
        
        logger.info('Signal detection - has_pricing: %s, has_currency: %s', has_pricing, has_currency)
        
        # HYBRID SIGNAL 2: Check for RFQ request language (strong RFQ signal)
        rfq_request_indicators = [
            'request for quotation', 'please quote', 'we need a quote',
            'please provide pricing', 'request for proposal', 'rfp',
            'we would like to request', 'can you provide us with',
            'we are looking for', 'please send us your quote'
        ]
        has_rfq_request = any(indicator in full_body for indicator in rfq_request_indicators)
        
        logger.info('Signal detection - has_rfq_request: %s', has_rfq_request)
        
        # HYBRID SIGNAL 3: Check for PO language (strong PO signal)
        po_indicators = [
            'purchase order', 'po number', 'we order', 'we are pleased to place',
            'order confirmation', 'please process our order'
        ]
        has_po = any(indicator in full_body for indicator in po_indicators)
        
        logger.info('Signal detection - has_po: %s', has_po)
        
        # HYBRID SIGNAL 4: Check for RFQ number in subject (could be quotation referencing RFQ)
        import re
        rfq_number_pattern = r'[Rr][Ff][Qq][-\s]?(\d{8}[-\s]?[A-Fa-f0-9]{8}|\d{4}[-\s]?\d{3})'
        has_rfq_number = bool(re.search(rfq_number_pattern, subject))
        logger.info('Signal detection - has_rfq_number: %s', has_rfq_number)
        
        # Apply hybrid signals (override AI if strong signals present)
        # Priority 1: RFQ number + pricing/currency → quotation referencing RFQ (strongest quotation signal)
        if has_rfq_number and (has_pricing or has_currency):
            logger.info('Hybrid signal: RFQ number + pricing detected, classifying as QUOTATION')
            return 'quotation'
        
        # Priority 2: Attachments + RFQ number → quotation (suppliers send quotations with attachments)
        if has_attachments and has_rfq_number:
            logger.info('Hybrid signal: Attachments + RFQ number detected, classifying as QUOTATION')
            return 'quotation'
        
        # Priority 3: Attachments + pricing → quotation
        if has_attachments and (has_pricing or has_currency):
            logger.info('Hybrid signal: Attachments + pricing detected, classifying as QUOTATION')
            return 'quotation'
        
        # Priority 4: PO indicators (but only if no RFQ number - quotations may have "order" in body)
        if has_po and not has_rfq_number:
            logger.info('Hybrid signal: PO indicators detected (no RFQ number), classifying as PO')
            return 'po'
        
        # Priority 5: Pricing without RFQ request → quotation
        if has_pricing and not has_rfq_request:
            logger.info('Hybrid signal: Pricing indicators detected without RFQ request, classifying as QUOTATION')
            return 'quotation'
        
        # Priority 6: RFQ request without pricing → RFQ
        if has_rfq_request and not has_pricing:
            logger.info('Hybrid signal: RFQ request detected without pricing, classifying as RFQ')
            return 'rfq'
        
        # Priority 7: PO indicators with RFQ number → likely quotation (supplier referencing RFQ)
        if has_po and has_rfq_number:
            logger.info('Hybrid signal: PO indicators + RFQ number detected, classifying as QUOTATION')
            return 'quotation'

        # If signals are mixed or unclear, use AI classifier
        from rfq.data_extractors import OpenAiExtractor
        extractor = OpenAiExtractor()
        if not extractor._client:
            logger.info('AI classifier unavailable, using keyword classifier')
            return EmailClassifier().classify(email)
        
        logger.info('Using AI classifier for email classification (hybrid signals were mixed/unclear)')

        prompt = (
            'Classify the following email as one of:\n'
            '- RFQ: A customer REQUESTING a quotation or inquiry (asking for prices)\n'
            '- PO: A customer placing a purchase order (confirming an order)\n'
            '- QUOTATION: A supplier SENDING a price quote, proposal, or quotation (providing prices)\n'
            '- OTHER: Anything else\n\n'
            'IMPORTANT DISTINCTIONS:\n'
            '- If the email says "thank you for your inquiry" or "please find our quotation" → QUOTATION\n'
            '- If the email contains unit prices, price tables, or pricing details → QUOTATION\n'
            '- If the email references an RFQ number but is FROM a supplier → QUOTATION\n'
            '- If the email asks for prices or quotes → RFQ\n'
            '- If the email places an order → PO\n\n'
            'Reply with only a single word: RFQ, PO, QUOTATION, or OTHER.\n\n'
            f'{text}'
        )
        try:
            response = extractor._client.messages.create(
                model=getattr(settings, 'ANTHROPIC_MODEL', 'claude-sonnet-4-6'),
                max_tokens=10,
                temperature=0,
                messages=[
                    {
                        'role': 'user',
                        'content': (
                            'You classify emails as RFQ, PO, QUOTATION, or OTHER. '
                            'Reply with only one word.\n\n'
                            f'{prompt}'
                        ),
                    },
                ],
            )
            answer = response.content[0].text.strip().upper()
            logger.info('AI classifier result: %s', answer)
            if answer == 'RFQ':
                return 'rfq'
            if answer == 'PO':
                return 'po'
            if answer == 'QUOTATION':
                return 'quotation'
            logger.warning('AI classifier returned unexpected result: %s, defaulting to other', answer)
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

        # Then try by sender email
        recent_orders = Order.objects.filter(
            email_sender=sender_email,
            created_at__gte=thirty_days_ago,
        ).order_by('-created_at')
        
        if recent_orders.exists():
            order = recent_orders.first()
            logger.info('Found recent Order %s from sender %s (fallback match)', order.rfq_number, sender_email)
            return order

        # Finally try by email_subject containing existing rfq_number
        for o in Order.objects.filter(created_at__gte=thirty_days_ago).only('rfq_number', 'email_subject'):
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
        
        # For quotations, try to find existing order by RFQ number in subject
        if classification == 'quotation':
            order = self._find_order_for_quotation(email)
            if order:
                logger.info('Processing quotation for existing Order %s', order.rfq_number)
                self._handle_quotation(email, order)
                return order
            else:
                logger.info('No existing Order found for quotation, creating new order')

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

    def _handle_rfq_po(self, email: EmailMessage, order: Order) -> None:
        """
        Extract description, part number, quantity, delivery date
        from an RFQ email and save to the Order + OrderItem records.
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
                        if file_text:
                            text_to_extract = file_text
                            break

        extracted = self._data_extractor.extract(text_to_extract)
        if extracted is None:
            extracted = self._fallback_extractor.extract(text_to_extract)

        if extracted:
            self._rfq_builder.update_from_extraction(order, extracted)
        else:
            logger.warning('Data extraction failed for Order %s', order.rfq_number)

        if not order.supplier and not order.supplier_email:
            try:
                from tasks.services import TaskService
                TaskService.create_supplier_assignment_task(order)
            except Exception as exc:
                logger.error(
                    'Failed to create supplier-assignment task for Order %s: %s',
                    order.rfq_number, exc,
                )

        bc_enabled = getattr(settings, 'BC_SYNC_ENABLED', True)
        if bc_enabled:
            try:
                from rfq.business_central import create_quotation_in_bc
                result = create_quotation_in_bc(order)
                if result:
                    order.status = 'processing'
                    order.save(update_fields=['status'])
            except Exception:
                pass

        order.stage = 'inquiry'
        order.save(update_fields=['stage'])

        if order.supplier_email or order.supplier:
            from rfq.tasks import dispatch_to_supplier
            dispatch_to_supplier.delay(order.id)

    def _handle_quotation(self, email: EmailMessage, order: Order) -> None:
        """
        Handle incoming supplier quotation.
        Extract item prices from email/attachment, match to RFQ items,
        update OrderItem records with supplier prices, set stage to negotiation,
        and send quotation email to customer.
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
                        if file_text:
                            text_to_extract = file_text
                            break

        extracted = self._data_extractor.extract(text_to_extract, is_quotation=True)
        if extracted is None:
            extracted = self._fallback_extractor.extract(text_to_extract, is_quotation=True)

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

        try:
            from rfq.business_central import create_quotation_in_bc
            create_quotation_in_bc(order)
        except Exception:
            pass

        try:
            from rfq.email_service import CustomerQuotationService
            from microsoft_auth.graph_api import GraphEmailProvider
            from django.contrib.auth import get_user_model

            # Check if quotation email has already been sent to avoid duplicates
            if order.quotation_email_sent:
                logger.info('Quotation email already sent for Order %s, skipping', order.rfq_number)
                return

            User = get_user_model()
            user = User.objects.filter(microsoft_token__isnull=False).first()
            if not user:
                logger.warning('No user with Microsoft token available for sending quotation email')
                return

            token = user.microsoft_token
            token.refresh_if_expired()
            provider = GraphEmailProvider(
                access_token=token.access_token,
                refresh_token=token.refresh_token,
                token_expires_at=token.token_expires_at,
                user=user,
            )

            email_service = CustomerQuotationService(email_provider=provider)
            result = email_service.send_quotation_to_customer(order)

            if result['success']:
                order.quotation_email_sent = True
                order.save(update_fields=['quotation_email_sent'])
                logger.info('Quotation email sent successfully for Order %s', order.rfq_number)
            else:
                logger.error('Failed to send quotation email to customer for Order %s: %s', order.rfq_number, result['message'])
        except Exception as exc:
            logger.error('Error sending quotation email to customer for Order %s: %s', order.rfq_number, exc)

    def _handle_po(self, email: EmailMessage, order: Order) -> None:
        """
        Handle customer Purchase Order.
        Extract PO data, update order with PO details, set stage to order,
        and create Purchase Order in Business Central.
        """
        text_to_extract = email.get('body', '')

        po_number = None
        import re
        po_match = re.search(r'PO\s*[-:]?\s*([A-Z0-9-]+)', email.get('subject', '') + ' ' + email.get('body', ''), re.IGNORECASE)
        if po_match:
            po_number = po_match.group(1)

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
                        if file_text:
                            text_to_extract = file_text
                            break

        extracted = self._data_extractor.extract(text_to_extract)
        if extracted is None:
            extracted = self._fallback_extractor.extract(text_to_extract)

        if extracted:
            self._rfq_builder.update_from_extraction(order, extracted)
        else:
            logger.warning('Data extraction failed for Order %s', order.rfq_number)

        if po_number:
            order.po_number = po_number

        order.type = 'purchase_order'
        order.stage = 'order'
        order.status = 'processing'
        order.save(update_fields=['type', 'stage', 'status', 'po_number'])

        bc_enabled = getattr(settings, 'BC_SYNC_ENABLED', True)
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
