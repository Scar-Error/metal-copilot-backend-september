from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from django.utils import timezone

from authentication.models import CustomUser
from rfq.interfaces import EmailClassification, ExtractedRfqData
from rfq.models import Order, OrderItem
from rfq.utils import generate_rfq_number

logger = logging.getLogger(__name__)


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
        email_message_id: str = '',
        email_classification: EmailClassification = 'other',
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

        order = Order.objects.create(
            email_subject=subject,
            email_sender=sender_email,
            email_received_at=parsed_dt,
            email_body=body,
            rfq_number=generate_rfq_number(),
            company_name=sender_name or sender_email.split('@')[0],
            status='pending',
            stage='inquiry',
            type='rfq',
            priority='medium',
            source=source,
            ai_processed=False,
            email_message_id=email_message_id,
            email_classification=email_classification,
        )

        # Auto-create or link contact
        from contacts.models import Contact
        contact, _ = Contact.objects.get_or_create(
            email=sender_email,
            defaults={
                'company_name': sender_name or sender_email.split('@')[0],
                'contact_person': sender_name or '',
                'type': 'client',
            },
        )
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
        
        # Validate and convert quantity to number
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
        order.ai_confidence_score = data.get('confidence_score')

        delivery = data.get('delivery_date')
        if delivery:
            try:
                order.delivery_date = datetime.strptime(delivery, '%Y-%m-%d').date()
            except (ValueError, TypeError):
                pass

        order.ai_processed = True
        order.save(update_fields=[
            'company_name', 'items_description', 'quantity',
            'specifications', 'delivery_date',
            'ai_processed', 'ai_confidence_score',
        ])

        self._create_items(order, data.get('items', []))
        logger.info(
            'Updated Order %s with AI data (confidence=%.2f)',
            order.rfq_number, data.get('confidence_score', 0),
        )
        return order

    @staticmethod
    def _create_items(order: Order, items: List[Dict[str, Any]]) -> None:
        for idx, item_data in enumerate(items):
            # Validate and convert quantity to number
            qty = item_data.get('quantity', 1)
            try:
                if isinstance(qty, str):
                    # Try to convert string to number
                    qty = float(qty) if qty.replace('.', '', 1).isdigit() else 1
                elif qty is None or qty == 0:
                    qty = 1
            except (ValueError, TypeError, AttributeError):
                qty = 1
                logger.warning(
                    'Invalid quantity "%s" for item %s, defaulting to 1',
                    item_data.get('quantity'), item_data.get('description', f'Item {idx + 1}')
                )

            unit = item_data.get('unit', 'PC')
            if not unit or unit is None:
                unit = 'PC'

            OrderItem.objects.create(
                order=order,
                item_name=item_data.get('description', f'Item {idx + 1}'),
                item_code=item_data.get('part_number', ''),
                description=item_data.get('description', ''),
                quantity=int(qty),
                unit=unit,
                extraction_confidence=item_data.get('confidence_score'),
            )
