from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import requests
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)


class BusinessCentralClient:
    """
    Low-level HTTP client for Microsoft Dynamics 365 Business Central API.

    Takes an access token at init – no model coupling.
    """

    def __init__(
        self,
        access_token: str,
        environment: str = 'Production',
    ) -> None:
        self._access_token = access_token
        tenant_id = settings.MICROSOFT_TENANT_ID
        self._base_url = (
            f'https://api.businesscentral.dynamics.com/v2.0'
            f'/{tenant_id}/{environment}/api/v2.0'
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_companies(self) -> List[Dict[str, Any]]:
        result = self._get('companies')
        return (result or {}).get('value', [])

    def get_items(self, company_id: str) -> List[Dict[str, Any]]:
        result = self._get(f'companies({company_id})/items')
        return (result or {}).get('value', [])

    def create_sales_quote(
        self,
        company_id: str,
        quote_data: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        return self._post(
            f'companies({company_id})/salesQuotes',
            data=quote_data,
        )

    def create_quote_line(
        self,
        company_id: str,
        quote_id: str,
        line_data: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        return self._post(
            f'companies({company_id})/salesQuotes({quote_id})/salesQuoteLines',
            data=line_data,
        )

    def create_purchase_order(
        self,
        company_id: str,
        po_data: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        return self._post(
            f'companies({company_id})/purchaseOrders',
            data=po_data,
        )

    def create_purchase_order_line(
        self,
        company_id: str,
        po_id: str,
        line_data: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        return self._post(
            f'companies({company_id})/purchaseOrders({po_id})/purchaseOrderLines',
            data=line_data,
        )

    # ------------------------------------------------------------------
    # Internal HTTP
    # ------------------------------------------------------------------

    def _request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        url = f'{self._base_url}/{endpoint}'
        headers = {
            'Authorization': f'Bearer {self._access_token}',
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        }
        try:
            resp = requests.request(
                method=method,
                url=url,
                headers=headers,
                json=data,
                timeout=30,
            )
            resp.raise_for_status()
            return resp.json()
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else 0
            logger.error(
                'BC %s %s failed [%d]: %s',
                method, endpoint, status,
                exc.response.text[:500] if exc.response is not None else '',
            )
            return None
        except requests.RequestException as exc:
            logger.error('BC %s %s error: %s', method, endpoint, exc)
            return None

    def _get(self, endpoint: str) -> Optional[Dict[str, Any]]:
        return self._request('GET', endpoint)

    def _post(
        self,
        endpoint: str,
        data: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        return self._request('POST', endpoint, data=data)


# ---------------------------------------------------------------------------
# Orchestration layer – connects the BC client to Django models
# ---------------------------------------------------------------------------


def build_bc_client_for_user(user) -> Optional[BusinessCentralClient]:
    """Helper: instantiate a BC client from a Django user's Microsoft token."""
    try:
        token = user.microsoft_token
        if not token or not token.access_token:
            logger.error('No valid Microsoft token for user %s', user)
            return None
        return BusinessCentralClient(access_token=token.access_token)
    except Exception as exc:
        logger.error('Failed to build BC client: %s', exc)
        return None


def create_quotation_in_bc(order) -> bool:
    """Create a sales quotation in BC from an Order record."""
    user = order.reviewed_by
    if not user:
        logger.error('Order %s has no reviewer', order.rfq_number)
        return False

    client = build_bc_client_for_user(user)
    if not client:
        return False

    companies = client.get_companies()
    if not companies:
        logger.error('No companies found in BC')
        return False

    company_id = companies[0].get('id')
    quote_data: Dict[str, Any] = {
        'sellToCustomerNumber': order.company_name,
        'documentDate': order.created_at.strftime('%Y-%m-%d'),
        'dueDate': (
            order.delivery_date.strftime('%Y-%m-%d')
            if order.delivery_date else ''
        ),
        'status': 'Draft',
    }
    quote = client.create_sales_quote(company_id, quote_data)
    if not quote:
        logger.error('Failed to create sales quote for order %s', order.rfq_number)
        return False

    quote_id = quote.get('id')
    for item in order.items.all():
        client.create_quote_line(company_id, quote_id, {
            'lineType': 'Item',
            'itemNumber': item.item_code or item.item_name,
            'quantity': item.quantity,
            'unitPrice': float(item.unit_price) if item.unit_price else 0,
        })

    order.bc_quote_id = quote_id
    order.bc_synced = True
    order.bc_synced_at = timezone.now()
    order.save(update_fields=['bc_quote_id', 'bc_synced', 'bc_synced_at'])

    logger.info(
        'Created BC quotation for order %s (quote id: %s)',
        order.rfq_number, quote_id,
    )
    return True


def sync_products_from_bc(user) -> int:
    """Sync product/item master from BC. Returns count of synced products."""
    client = build_bc_client_for_user(user)
    if not client:
        return 0

    companies = client.get_companies()
    if not companies:
        return 0

    company_id = companies[0].get('id')
    bc_items = client.get_items(company_id)
    count = 0

    from rfq.models import Product

    for bc_item in bc_items:
        bc_id = bc_item.get('id')
        if not bc_id:
            continue
        Product.objects.update_or_create(
            bc_product_id=bc_id,
            defaults={
                'number': bc_item.get('number', ''),
                'display_name': bc_item.get('displayName', ''),
                'description': bc_item.get('description', ''),
                'unit_price': bc_item.get('unitPrice'),
                'unit': bc_item.get('baseUnitOfMeasure', {}).get('code', ''),
                'type': bc_item.get('type', ''),
                'blocked': bc_item.get('blocked', False),
            },
        )
        count += 1

    logger.info('Synced %d products from BC', count)
    return count


def create_purchase_order_in_bc(order) -> bool:
    """Create a purchase order in BC from an Order record."""
    user = order.reviewed_by
    if not user:
        logger.error('Order %s has no reviewer for PO creation', order.rfq_number)
        return False

    client = build_bc_client_for_user(user)
    if not client:
        return False

    companies = client.get_companies()
    if not companies:
        logger.error('No companies found in BC for PO')
        return False

    company_id = companies[0].get('id')
    po_data: Dict[str, Any] = {
        'vendorNumber': order.company_name,
        'documentDate': order.created_at.strftime('%Y-%m-%d'),
        'dueDate': (
            order.delivery_date.strftime('%Y-%m-%d')
            if order.delivery_date else ''
        ),
    }
    po = client.create_purchase_order(company_id, po_data)
    if not po:
        logger.error('Failed to create purchase order for order %s', order.rfq_number)
        return False

    po_id = po.get('id')
    for item in order.items.all():
        client.create_purchase_order_line(company_id, po_id, {
            'lineType': 'Item',
            'itemNumber': item.item_code or item.item_name,
            'quantity': item.quantity,
            'unitCost': float(item.unit_price) if item.unit_price else 0,
        })

    logger.info('Created BC purchase order for order %s', order.rfq_number)
    return True
