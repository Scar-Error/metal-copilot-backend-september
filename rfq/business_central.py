import logging
from typing import Dict, List, Optional, Any
from django.conf import settings
from django.utils import timezone
import requests

logger = logging.getLogger(__name__)


class BusinessCentralClient:
    """Client for interacting with Business Central API."""

    def __init__(self, access_token: str):
        self.access_token = access_token
        self.base_url = settings.BC_API_URL
        self.headers = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json',
        }

    def _get(self, endpoint: str) -> Optional[Dict]:
        """Make a GET request to BC API."""
        try:
            url = f"{self.base_url}/{endpoint}"
            response = requests.get(url, headers=self.headers, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.HTTPError as exc:
            logger.error(
                'BC GET request failed: HTTP %s - %s',
                exc.response.status_code,
                exc.response.text,
            )
            return None
        except Exception as exc:
            logger.error('BC GET request failed: %s', exc)
            return None

    def _post(self, endpoint: str, data: Dict) -> Optional[Dict]:
        """Make a POST request to BC API."""
        try:
            url = f"{self.base_url}/{endpoint}"
            response = requests.post(url, headers=self.headers, json=data, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.HTTPError as exc:
            logger.error(
                'BC POST request failed: HTTP %s - %s',
                exc.response.status_code,
                exc.response.text,
            )
            return None
        except Exception as exc:
            logger.error('BC POST request failed: %s', exc)
            return None

    def _patch(self, endpoint: str, data: Dict) -> Optional[Dict]:
        """Make a PATCH request to BC API."""
        try:
            url = f"{self.base_url}/{endpoint}"
            response = requests.patch(url, headers=self.headers, json=data, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.HTTPError as exc:
            logger.error(
                'BC PATCH request failed: HTTP %s - %s',
                exc.response.status_code,
                exc.response.text,
            )
            return None
        except Exception as exc:
            logger.error('BC PATCH request failed: %s', exc)
            return None

    def get_companies(self) -> List[Dict]:
        """Get list of all companies in BC."""
        result = self._get('companies')
        if result and 'value' in result:
            return result['value']
        return []

    def get_company_by_name(self, company_name: str) -> Optional[str]:
        """Get company ID by name. Returns company ID or None."""
        companies = self.get_companies()
        for company in companies:
            if company.get('name') == company_name:
                return company.get('id')
        return None

    def get_customers(self, company_id: str) -> List[Dict]:
        """Get customers for a specific company."""
        result = self._get(f'companies({company_id})/customers')
        if result and 'value' in result:
            return result['value']
        return []

    def get_customer_by_name(self, company_id: str, customer_name: str) -> Optional[Dict]:
        """Get customer by name. Returns customer or None."""
        customers = self.get_customers(company_id)
        for customer in customers:
            if customer.get('displayName', '').lower() == customer_name.lower():
                return customer
            if customer.get('name', '').lower() == customer_name.lower():
                return customer
        return None

    def get_customer_by_partial_match(self, company_id: str, company_hint: str) -> Optional[Dict]:
        """Get customer by partial name match (case-insensitive). Returns customer or None."""
        customers = self.get_customers(company_id)
        hint_lower = company_hint.lower()
        for customer in customers:
            display_name = customer.get('displayName', '').lower()
            name = customer.get('name', '').lower()
            if hint_lower in display_name or hint_lower in name:
                return customer
        return None

    def get_items(self, company_id: str) -> List[Dict]:
        """Get items for a specific company."""
        result = self._get(f'companies({company_id})/items')
        if result and 'value' in result:
            return result['value']
        return []

    def get_item_by_number(self, company_id: str, item_number: str) -> Optional[Dict]:
        """Get a specific item by number."""
        result = self._get(f'companies({company_id})/items({item_number})')
        return result

    def create_sales_quote(self, company_id: str, quote_data: Dict) -> Optional[Dict]:
        """Create a sales quote in BC."""
        result = self._post(f'companies({company_id})/salesQuotes', quote_data)
        return result

    def create_purchase_order(self, company_id: str, po_data: Dict) -> Optional[Dict]:
        """Create a purchase order in BC."""
        result = self._post(f'companies({company_id})/purchaseOrders', po_data)
        return result

    def update_item(self, company_id: str, item_number: str, data: Dict) -> Optional[Dict]:
        """Update an item in BC."""
        result = self._patch(f'companies({company_id})/items({item_number})', data)
        return result


def build_bc_client_for_user(user) -> Optional[BusinessCentralClient]:
    """Build a BC client using client credentials flow for Business Central API."""
    try:
        from django.conf import settings
        import requests
        
        client_id = settings.MICROSOFT_CLIENT_ID
        client_secret = settings.MICROSOFT_CLIENT_SECRET
        tenant_id = settings.MICROSOFT_TENANT_ID
        
        if not client_id or not client_secret or not tenant_id:
            logger.error('Missing Microsoft OAuth credentials for BC client')
            return None
        
        # Get BC-specific access token using client credentials flow
        token_url = f'https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token'
        token_data = {
            'client_id': client_id,
            'client_secret': client_secret,
            'scope': 'https://api.businesscentral.dynamics.com/.default',
            'grant_type': 'client_credentials',
        }
        
        token_response = requests.post(token_url, data=token_data, timeout=30)
        token_response.raise_for_status()
        access_token = token_response.json().get('access_token')
        
        if not access_token:
            logger.error('Failed to get BC access token from token response')
            return None
        
        return BusinessCentralClient(access_token=access_token)
    except Exception as exc:
        logger.error('Failed to build BC client: %s', exc)
        return None


def create_quotation_in_bc(order) -> bool:
    """Create a sales quotation in BC from an Order record."""
    user = order.reviewed_by
    if not user:
        # Fall back to admin user if no reviewer is set
        from django.contrib.auth import get_user_model
        User = get_user_model()
        try:
            user = User.objects.filter(is_superuser=True).first()
            if not user:
                logger.error('Order %s has no reviewer and no admin user found', order.rfq_number)
                return False
        except Exception as exc:
            logger.error('Failed to get admin user for BC sync: %s', exc)
            return False

    client = build_bc_client_for_user(user)
    if not client:
        return False

    from django.conf import settings
    company_name = settings.BC_COMPANY_NAME
    if not company_name:
        logger.error('BC_COMPANY_NAME not configured in settings')
        return False

    company_id = client.get_company_by_name(company_name)
    if not company_id:
        logger.error(
            'Failed to find company "%s" for order %s',
            company_name, order.rfq_number
        )
        return False

    # Priority-based customer matching:
    # 1. Try AI-extracted company_name
    # 2. If placeholder, try email domain extraction
    # 3. If still no match, use generic/default customer
    PLACEHOLDER_COMPANIES = ['not specified', 'unknown company', 'various items', '']
    
    bc_customer = None
    company_name_used = order.company_name
    
    # Priority 1: Try exact match with AI-extracted company_name
    if order.company_name.lower() not in PLACEHOLDER_COMPANIES:
        bc_customer = client.get_customer_by_name(company_id, order.company_name)
    
    # Priority 2: If AI extraction failed, try email domain extraction
    if not bc_customer and order.email_sender:
        try:
            email_domain = order.email_sender.split('@')[1].split('.')[0]
            bc_customer = client.get_customer_by_partial_match(company_id, email_domain)
            if bc_customer:
                company_name_used = f"email domain ({email_domain})"
                logger.info(
                    'Matched BC customer using email domain "%s" for order %s',
                    email_domain, order.rfq_number
                )
        except (IndexError, AttributeError):
            pass
    
    # Priority 3: Use generic/default customer (first available)
    if not bc_customer:
        customers = client.get_customers(company_id)
        if customers:
            bc_customer = customers[0]  # Use first customer as generic fallback
            company_name_used = f"generic customer ({bc_customer.get('displayName', bc_customer.get('name', 'Unknown'))})"
            logger.warning(
                'Using generic BC customer "%s" for order %s (no match found for "%s")',
                bc_customer.get('displayName', bc_customer.get('name', 'Unknown')),
                order.rfq_number,
                order.company_name
            )
        else:
            logger.error(
                'No BC customers available for order %s',
                order.rfq_number
            )
            return False

    # Minimal quote data to avoid triggering PayPal extension checks
    quote_data: Dict[str, Any] = {
        'customerNumber': bc_customer.get('number'),
        'documentDate': order.created_at.strftime('%Y-%m-%d'),
    }

    try:
        result = client.create_sales_quote(company_id, quote_data)
        if result:
            logger.info(
                'Created BC sales quote for order %s using customer: %s',
                order.rfq_number, company_name_used
            )
            order.bc_synced_at = timezone.now()
            order.save(update_fields=['bc_synced_at'])
            return True
        else:
            logger.error('Failed to create BC sales quote for order %s', order.rfq_number)
            return False
    except Exception as exc:
        logger.error('Error creating BC quotation for order %s: %s', order.rfq_number, exc)
        return False


def create_purchase_order_in_bc(order) -> bool:
    """Create a purchase order in BC from an Order record."""
    user = order.reviewed_by
    if not user:
        # Fall back to admin user if no reviewer is set
        from django.contrib.auth import get_user_model
        User = get_user_model()
        try:
            user = User.objects.filter(is_superuser=True).first()
            if not user:
                logger.error('Order %s has no reviewer and no admin user found for PO creation', order.rfq_number)
                return False
        except Exception as exc:
            logger.error('Failed to get admin user for BC PO sync: %s', exc)
            return False

    client = build_bc_client_for_user(user)
    if not client:
        return False

    from django.conf import settings
    company_name = settings.BC_COMPANY_NAME
    if not company_name:
        logger.error('BC_COMPANY_NAME not configured in settings')
        return False

    company_id = client.get_company_by_name(company_name)
    if not company_id:
        logger.error(
            'Failed to find company "%s" for order %s',
            company_name, order.rfq_number
        )
        return False

    po_data: Dict[str, Any] = {
        'buyFromVendorNumber': order.supplier.company_name if order.supplier else '',
        'documentDate': order.created_at.strftime('%Y-%m-%d'),
        'currencyCode': 'EUR',
    }
    if order.delivery_date:
        po_data['dueDate'] = order.delivery_date.strftime('%Y-%m-%d')

    try:
        result = client.create_purchase_order(company_id, po_data)
        if result:
            logger.info('Created BC purchase order for order %s', order.rfq_number)
            return True
        else:
            logger.error('Failed to create BC purchase order for order %s', order.rfq_number)
            return False
    except Exception as exc:
        logger.error('Error creating BC PO for order %s: %s', order.rfq_number, exc)
        return False


def update_item_in_bc(company_id: str, item_number: str, data: Dict, client: BusinessCentralClient) -> bool:
    """Update an item in Business Central."""
    try:
        result = client.update_item(company_id, item_number, data)
        if result:
            logger.info('Updated BC item %s', item_number)
            return True
        else:
            logger.error('Failed to update BC item %s', item_number)
            return False
    except Exception as exc:
        logger.error('Error updating BC item %s: %s', item_number, exc)
        return False


def update_item_prices_from_quotation(order) -> int:
    """
    Update item prices in Business Central from supplier quotation.
    Returns count of successfully updated items.
    """
    user = order.reviewed_by
    if not user:
        # Fall back to admin user if no reviewer is set
        from django.contrib.auth import get_user_model
        User = get_user_model()
        try:
            user = User.objects.filter(is_superuser=True).first()
            if not user:
                logger.error('Order %s has no reviewer and no admin user found for price update', order.rfq_number)
                return 0
        except Exception as exc:
            logger.error('Failed to get admin user for BC price update: %s', exc)
            return 0

    client = build_bc_client_for_user(user)
    if not client:
        return 0

    from django.conf import settings
    company_name = settings.BC_COMPANY_NAME
    if not company_name:
        logger.error('BC_COMPANY_NAME not configured in settings')
        return 0

    company_id = client.get_company_by_name(company_name)
    if not company_id:
        logger.error(
            'Failed to find company "%s" for order %s',
            company_name, order.rfq_number
        )
        return 0

    count = 0
    from rfq.models import OrderItem
    order_items = OrderItem.objects.filter(order=order)
    
    for item in order_items:
        if item.supplier_price:
            update_data = {
                'unitPrice': item.supplier_price,
            }
            if update_item_in_bc(company_id, item.part_number, update_data, client):
                count += 1

    logger.info('Updated %d item prices in BC for order %s', count, order.rfq_number)
    return count


def sync_products_from_bc(user) -> int:
    """Sync products from Business Central to local database."""
    client = build_bc_client_for_user(user)
    if not client:
        return 0

    from django.conf import settings
    company_name = settings.BC_COMPANY_NAME
    if not company_name:
        logger.error('BC_COMPANY_NAME not configured in settings')
        return 0

    company_id = client.get_company_by_name(company_name)
    if not company_id:
        logger.error('Failed to find company "%s"', company_name)
        return 0

    items = client.get_items(company_id)
    if not items:
        logger.warning('No items found in BC company %s', company_name)
        return 0

    from contacts.models import Product
    count = 0
    
    for bc_item in items:
        item_number = bc_item.get('number', '')
        if not item_number:
            continue
        
        defaults = {
            'name': bc_item.get('displayName', ''),
            'description': bc_item.get('description', ''),
            'unit_price': bc_item.get('unitPrice', 0),
            'blocked': bc_item.get('blocked', False),
        }
        
        Product.objects.update_or_create(
            part_number=item_number,
            defaults=defaults,
        )
        count += 1

    logger.info('Synced %d products from BC', count)
    return count
