from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from django.utils import timezone

from authentication.models import CustomUser
from rfq.interfaces import EmailClassification, ExtractedRfqData
from rfq.models import Order, OrderItem, OrderAiMetadata
from rfq.utils import generate_rfq_number

logger = logging.getLogger(__name__)

# Accepted item unit values (lowercase canonical form).
ALLOWED_UNITS = ('pc', 'pcs', 'kg', 'ltr')
DEFAULT_UNIT = 'pc'
# Aliases mapped to their canonical unit (for robustness against AI output).
UNIT_ALIASES = {
    'pc': 'pc',
    'pcs': 'pcs',
    'piece': 'pc',
    'pieces': 'pcs',
    'kg': 'kg',
    'kilogram': 'kg',
    'kilograms': 'kg',
    'kgs': 'kg',
    'ltr': 'ltr',
    'l': 'ltr',
    'liter': 'ltr',
    'litre': 'ltr',
    'liters': 'ltr',
    'litres': 'ltr',
}
# Max length for the 'Description' (part number) and 'Description 2' (name) item columns.
ITEM_FIELD_MAX_LEN = 99
# Marker used on spill-over items when a description exceeds ITEM_FIELD_MAX_LEN.
COMMENT_ITEM_CODE = 'comment'


class RfqBuilder:
    """Construct and persist Order records from extracted data."""

    def create_from_email(
        self,
        *,
        subject: str,
        sender_email: str,
        sender_name: str,
        received_at: Optional[str],
        body: str,
        source: str = 'email',
    ) -> Order:
        """Create a minimal Order record from email metadata."""
        parsed_dt: datetime
        if received_at:
            try:
                parsed_dt = datetime.fromisoformat(
                    received_at.replace('Z', '+00:00'),
                )
            except (ValueError, TypeError):
                parsed_dt = timezone.now()
        else:
            parsed_dt = timezone.now()

        company = sender_name or sender_email.split('@')[0]

        order = Order.objects.create(
            rfq_number=generate_rfq_number(),
            company_name=company,
            type='rfq',
            source=source,
        )

        # Create AI metadata
        OrderAiMetadata.objects.create(
            order=order,
            processed=False,
            classification='rfq',
        )

        # Auto-create or link contact. The contact's company name and phone
        # number come from the email address and the signature, not from the
        # order, and an existing contact is never overwritten.
        from contacts.utils import upsert_contact_from_email
        contact, _ = upsert_contact_from_email(
            email=sender_email,
            sender_name=sender_name,
            body=body,
        )
        if contact is not None:
            order.contact = contact
            order.save(update_fields=['contact'])

        logger.info('Created Order %s from email', order.rfq_number)
        return order

    def update_from_extraction(
        self,
        order: Order,
        data: ExtractedRfqData,
    ) -> Order:
        """Update an Order record with AI-extracted data (no pricing)."""
        order.company_name = data.get('company_name', order.company_name)
        order.items_description = data.get('description') or data.get('items_description', '')

        qty = data.get('quantity')
        try:
            if isinstance(qty, str):
                qty = float(qty) if qty.replace('.', '', 1).isdigit() else None
            elif qty is None or qty == 'Not specified':
                qty = None
        except (ValueError, TypeError, AttributeError):
            qty = None
            logger.warning(
                'Invalid quantity "%s" for order %s, setting to None',
                data.get('quantity'), order.rfq_number
            )
        order.quantity = qty

        order.specifications = data.get('specifications', '')
        order.notes = data.get('notes') or order.notes or ''

        delivery = data.get('delivery_date')
        if delivery:
            try:
                order.delivery_date = datetime.strptime(delivery, '%Y-%m-%d').date()
            except (ValueError, TypeError):
                pass

        order.save(update_fields=[
            'company_name', 'items_description', 'quantity',
            'specifications', 'delivery_date', 'notes',
        ])

        # Update AI metadata
        ai_meta, _ = OrderAiMetadata.objects.get_or_create(order=order)
        ai_meta.processed = True
        ai_meta.confidence_score = data.get('confidence_score')
        ai_meta.save(update_fields=['processed', 'confidence_score', 'updated_at'])

        self._create_items(order, data.get('items', []))
        logger.info(
            'Updated Order %s with AI data (confidence=%.2f)',
            order.rfq_number, data.get('confidence_score', 0),
        )
        return order

    @staticmethod
    def _normalize_unit(unit: Any) -> str:
        """Map a raw unit string to a canonical allowed value, else 'pc'."""
        if not unit:
            return DEFAULT_UNIT
        normalized = str(unit).strip().lower()
        return UNIT_ALIASES.get(normalized, DEFAULT_UNIT)

    @staticmethod
    def _split_long_description(text: str) -> List[str]:
        """Break a description into at-most-99-char chunks ('' for empty text)."""
        text = (text or '').strip()
        if not text:
            return ['']
        return [
            text[i:i + ITEM_FIELD_MAX_LEN]
            for i in range(0, len(text), ITEM_FIELD_MAX_LEN)
        ]

    @classmethod
    def _create_items(cls, order: Order, items: List[Dict[str, Any]]) -> None:
        for idx, item_data in enumerate(items):
            part = (
                str(item_data.get('item_code') or item_data.get('part_number') or '').strip()
            )[:ITEM_FIELD_MAX_LEN]
            desc = (
                item_data.get('name')
                or item_data.get('item_name')
                or item_data.get('description')
                or ''
            )

            qty = item_data.get('quantity', 1)
            try:
                if isinstance(qty, str):
                    qty = float(qty) if qty.replace('.', '', 1).isdigit() else 1
                elif qty is None or qty == 0:
                    qty = 1
            except (ValueError, TypeError, AttributeError):
                qty = 1
                logger.warning(
                    'Invalid quantity "%s" for item %s, defaulting to 1',
                    item_data.get('quantity'), part or f'Item {idx + 1}'
                )

            unit = cls._normalize_unit(item_data.get('unit'))

            # A description longer than 99 chars is continued on extra "comment"
            # items ("Description 2" holds each remaining chunk).
            chunks = cls._split_long_description(desc)
            for ci, chunk in enumerate(chunks):
                is_primary = ci == 0
                OrderItem.objects.create(
                    order=order,
                    item_name=chunk,
                    item_code=part if is_primary else COMMENT_ITEM_CODE,
                    description=chunk,
                    quantity=int(qty) if is_primary else 0,
                    unit=unit if is_primary else '',
                    unit_price=item_data.get('unit_price') if is_primary else None,
                    total_price=item_data.get('total_price') if is_primary else None,
                    extraction_confidence=item_data.get('confidence_score') if is_primary else None,
                )
