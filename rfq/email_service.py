from __future__ import annotations

import logging
from typing import Optional

from django.template.loader import render_to_string
from django.utils import timezone

from rfq.interfaces import EmailProvider
from rfq.models import Order

logger = logging.getLogger(__name__)


class SupplierEmailService:
    """
    Send RFQ emails to suppliers.

    Uses an ``EmailProvider`` to send the message and a Django template
    for the body, keeping presentation and infrastructure separate.
    """

    def __init__(self, email_provider: EmailProvider) -> None:
        self._email_provider = email_provider

    def send_rfq_to_supplier(self, order: Order) -> dict:
        """
        Send the Order (with its items) to the supplier.

        Returns ``{'success': True, 'message': ...}`` or
        ``{'success': False, 'message': ...}``.
        """
        recipient = order.supplier.email if order.supplier else order.supplier_email
        if not recipient:
            return {
                'success': False,
                'message': 'No supplier configured for this order',
            }

        items = list(order.items.all())
        subject = f'RFQ {order.rfq_number} - {order.company_name}'

        html_body = render_to_string(
            'email/rfq_to_supplier.html',
            {'rfq': order, 'items': items},
        )

        ok = self._email_provider.send_email(
            to=recipient,
            subject=subject,
            body=html_body,
            content_type='HTML',
        )

        if ok:
            order.supplier_email = recipient
            order.supplier_email_sent = True
            order.supplier_email_sent_at = timezone.now()
            order.supplier_email_error = ''
            order.stage = 'quotation'
            order.save(update_fields=[
                'supplier_email', 'supplier_email_sent', 'supplier_email_sent_at',
                'supplier_email_error', 'stage',
            ])
            logger.info(
                'Sent order %s to supplier %s', order.rfq_number, recipient,
            )
            return {
                'success': True,
                'message': f'Email sent to {recipient}',
            }

        error = 'Failed to send email via provider'
        order.supplier_email_sent = False
        order.supplier_email_error = error
        order.save(update_fields=[
            'supplier_email_sent', 'supplier_email_error',
        ])
        logger.error('Failed to send order %s: %s', order.rfq_number, error)
        return {'success': False, 'message': error}


class CustomerQuotationService:
    """
    Send quotation emails to customers with supplier pricing.

    Uses an ``EmailProvider`` to send the message and a Django template
    for the body, keeping presentation and infrastructure separate.
    """

    def __init__(self, email_provider: EmailProvider) -> None:
        self._email_provider = email_provider

    def send_quotation_to_customer(self, order: Order) -> dict:
        """
        Send the quotation (with supplier prices) to the customer.

        Returns ``{'success': True, 'message': ...}`` or
        ``{'success': False, 'message': ...}``.
        """
        recipient = order.email_sender
        if not recipient:
            return {
                'success': False,
                'message': 'No customer email available for this order',
            }

        items = list(order.items.all())
        subject = f'Quotation {order.rfq_number} - {order.company_name}'

        # Calculate line totals and grand total
        for item in items:
            if item.unit_price:
                item.line_total = item.unit_price * item.quantity
            else:
                item.line_total = 0

        total_amount = sum(item.line_total for item in items)

        html_body = render_to_string(
            'email/quotation_to_customer.html',
            {
                'order': order,
                'items': items,
                'total_amount': total_amount,
            },
        )

        ok = self._email_provider.send_email(
            to=recipient,
            subject=subject,
            body=html_body,
            content_type='HTML',
        )

        if ok:
            logger.info(
                'Sent quotation for order %s to customer %s',
                order.rfq_number, recipient,
            )
            return {
                'success': True,
                'message': f'Quotation email sent to {recipient}',
            }

        error = 'Failed to send quotation email via provider'
        logger.error('Failed to send quotation for order %s: %s', order.rfq_number, error)
        return {'success': False, 'message': error}

