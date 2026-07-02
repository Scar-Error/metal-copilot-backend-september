import json
import logging
from typing import Dict, List, Optional, Any
from django.conf import settings
from django.utils import timezone
import requests

logger = logging.getLogger(__name__)
bc_sync_logger = logging.getLogger('bc_sync')


class BusinessCentralClient:
    """Client for interacting with Business Central API."""

    def __init__(self, access_token: str, odata_url: str = ''):
        self.access_token = access_token
        self.base_url = settings.BC_API_URL
        self.odata_url = odata_url or settings.BC_ODATA_URL or self.base_url.rstrip('/').rsplit('/api', 1)[0] + '/ODataV4'
        self.headers = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json',
        }

    def _log_request(self, method: str, endpoint: str, req_data: Any = None, resp_data: Any = None):
        msg = f'{method.upper()} {endpoint}'
        if req_data is not None:
            msg += f'\nRequest body:\n{json.dumps(req_data, indent=2)}'
        if resp_data is not None:
            msg += f'\nResponse body:\n{json.dumps(resp_data, indent=2)}'
        bc_sync_logger.info(msg)

    def _get(self, endpoint: str) -> Optional[Dict]:
        """Make a GET request to BC API."""
        try:
            url = f"{self.base_url}/{endpoint}"
            response = requests.get(url, headers=self.headers, timeout=30)
            response.raise_for_status()
            data = response.json()
            self._log_request('GET', endpoint, resp_data=data)
            return data
        except requests.exceptions.HTTPError as exc:
            self._log_request('GET', endpoint, resp_data={'error': exc.response.status_code, 'message': exc.response.text})
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
            result = response.json()
            self._log_request('POST', endpoint, req_data=data, resp_data=result)
            return result
        except requests.exceptions.HTTPError as exc:
            self._log_request('POST', endpoint, req_data=data, resp_data={'error': exc.response.status_code, 'message': exc.response.text})
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
            result = response.json()
            self._log_request('PATCH', endpoint, req_data=data, resp_data=result)
            return result
        except requests.exceptions.HTTPError as exc:
            self._log_request('PATCH', endpoint, req_data=data, resp_data={'error': exc.response.status_code, 'message': exc.response.text})
            logger.error(
                'BC PATCH request failed: HTTP %s - %s',
                exc.response.status_code,
                exc.response.text,
            )
            return None
        except Exception as exc:
            logger.error('BC PATCH request failed: %s', exc)
            return None

    def _get_odata(self, endpoint: str) -> Optional[Dict]:
        """Make a GET request to BC ODataV4 endpoint."""
        try:
            url = f"{self.odata_url}/{endpoint}"
            response = requests.get(url, headers=self.headers, timeout=30)
            response.raise_for_status()
            data = response.json()
            self._log_request('GET', endpoint, resp_data=data)
            return data
        except requests.exceptions.HTTPError as exc:
            self._log_request('GET', endpoint, resp_data={'error': exc.response.status_code, 'message': exc.response.text})
            logger.error(
                'BC OData GET request failed: HTTP %s - %s',
                exc.response.status_code,
                exc.response.text,
            )
            return None
        except Exception as exc:
            logger.error('BC OData GET request failed: %s', exc)
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

    def create_customer(self, company_id: str, customer_name: str, email: str = '', template_id: str = '', default_posting_group: str = 'FOREIGN') -> Optional[Dict]:
        """Create a new customer in BC. Returns created customer or None."""
        customer_data = {
            'displayName': customer_name,
            'type': 'Company',
        }
        if email:
            customer_data['email'] = email
        if template_id:
            customer_data['templateId'] = template_id

        try:
            result = self._post(f'companies({company_id})/customers', customer_data)
            if result:
                return result
            return None
        except Exception as exc:
            logger.error('Failed to create BC customer "%s": %s', customer_name, exc)
            return None

    def verify_customer_posting_group(self, company_id: str, customer_id: str, customer_number: str, company_name: str = '') -> bool:
        """Verify that a customer has a valid Customer Posting Group assigned.

        Uses the ODataV4 CustomerCard (Page 21) endpoint because the standard
        v2.0 /customers API does not expose customerPostingGroup.
        """
        try:
            from urllib.parse import quote

            if company_name:
                safe_name = company_name.replace("'", "''")
                filter_str = f"$filter=No eq '{customer_number}'"
                endpoint = f"Company('{quote(safe_name)}')/CustomerCard?{filter_str}"
                result = self._get_odata(endpoint)
                if result and 'value' in result and result['value']:
                    customer = result['value'][0]
                else:
                    bc_sync_logger.info('verify_customer_posting_group for %s: CustomerCard query returned no results; falling back to v2.0 API', customer_number)
                    customer = self._get(f'companies({company_id})/customers({customer_id})')
                if not customer:
                    bc_sync_logger.info('verify_customer_posting_group for %s: no customer returned from API', customer_number)
                    return False
            else:
                customer = self._get(f'companies({company_id})/customers({customer_id})')
                if not customer:
                    bc_sync_logger.info('verify_customer_posting_group for %s: no customer returned from API', customer_number)
                    return False

            posting_group = (
                customer.get('Customer_Posting_Group')
                or customer.get('customerPostingGroup')
                or customer.get('customerPostingGroupCode')
            )
            bc_sync_logger.info('verify_customer_posting_group for customer "%s" (%s): customerPostingGroup = "%s"', customer.get('displayName', customer_number), customer_number, posting_group)
            if posting_group and posting_group != '' and posting_group != '0':
                return True

            return False
        except Exception as exc:
            logger.error('Failed to verify posting group for customer %s: %s', customer_number, exc)
            return False

    def get_items(self, company_id: str) -> List[Dict]:
        """Get items for a specific company."""
        result = self._get(f'companies({company_id})/items')
        if result and 'value' in result:
            return result['value']
        return []

    def get_customer_posting_groups(self, company_id: str) -> List[Dict]:
        """Get available customer posting groups for a company."""
        result = self._get(f'companies({company_id})/customerPostingGroups')
        if result and 'value' in result:
            return result['value']
        return []

    def get_configuration_templates(self, company_id: str) -> List[Dict]:
        """Get available configuration templates for customers in a company."""
        result = self._get(f'companies({company_id})/configurationTemplates')
        if result and 'value' in result:
            return result['value']
        return []

    def update_sales_receivables_setup(self, company_id: str, default_customer_posting_group: str) -> bool:
        """Update Sales & Receivables Setup to set default customer posting group."""
        try:
            result = self._patch(
                f'companies({company_id})/salesReceivablesSetup',
                {'defaultCustomerPostingGroup': default_customer_posting_group}
            )
            if result:
                return True
            return False
        except Exception as exc:
            logger.error('Failed to update Sales & Receivables Setup: %s', exc)
            return False

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
            return None
        
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
            return None
        
        return BusinessCentralClient(access_token=access_token)
    except Exception as exc:
        logger.error('Failed to build BC client: %s', exc)
        return None


def create_quotation_in_bc(order) -> bool:
    """Create a sales quotation in BC from an Order record."""
    user = order.reviewed_by
    if not user:
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
        logger.error('Failed to build BC client for order %s', order.rfq_number)
        return False

    from django.conf import settings
    company_name = settings.BC_COMPANY_NAME
    if not company_name:
        logger.error('BC_COMPANY_NAME not configured in settings')
        return False

    company_id = client.get_company_by_name(company_name)
    if not company_id:
        logger.error('Failed to find company "%s" for order %s', company_name, order.rfq_number)
        return False

    PLACEHOLDER_COMPANIES = ['not specified', 'unknown company', 'various items', '']
    bc_customer = None

    if order.company_name.lower() not in PLACEHOLDER_COMPANIES:
        bc_sync_logger.info('Searching customer: "%s" | Basis: exact name match', order.company_name)
        bc_customer = client.get_customer_by_name(company_id, order.company_name)
        if bc_customer:
            bc_sync_logger.info('Found customer by exact name match: "%s" (%s)', bc_customer.get('displayName', ''), bc_customer.get('number', ''))
            if not client.verify_customer_posting_group(company_id, bc_customer['id'], bc_customer['number'], company_name):
                bc_sync_logger.info('Rejected customer "%s": missing or invalid customerPostingGroup', bc_customer.get('displayName', ''))
                bc_customer = None
            else:
                bc_sync_logger.info('Accepted customer "%s": valid customerPostingGroup', bc_customer.get('displayName', ''))

    if not bc_customer and order.company_name.lower() not in PLACEHOLDER_COMPANIES:
        company_keywords = order.company_name.split()[:3]
        for keyword in company_keywords:
            if len(keyword) > 3:
                bc_sync_logger.info('Searching customer: "%s" | Basis: partial keyword "%s"', order.company_name, keyword)
                bc_customer = client.get_customer_by_partial_match(company_id, keyword)
                if bc_customer:
                    bc_sync_logger.info('Found customer by partial keyword "%s": "%s" (%s)', keyword, bc_customer.get('displayName', ''), bc_customer.get('number', ''))
                    if not client.verify_customer_posting_group(company_id, bc_customer['id'], bc_customer['number'], company_name):
                        bc_sync_logger.info('Rejected customer "%s": missing or invalid customerPostingGroup', bc_customer.get('displayName', ''))
                        bc_customer = None
                        continue
                    bc_sync_logger.info('Accepted customer "%s": valid customerPostingGroup', bc_customer.get('displayName', ''))
                    break

    if not bc_customer and order.email_sender:
        try:
            email_domain = order.email_sender.split('@')[1].split('.')[0]
            bc_sync_logger.info('Searching customer: "%s" | Basis: email domain "%s"', order.company_name, email_domain)
            bc_customer = client.get_customer_by_partial_match(company_id, email_domain)
            if bc_customer:
                bc_sync_logger.info('Found customer by email domain "%s": "%s" (%s)', email_domain, bc_customer.get('displayName', ''), bc_customer.get('number', ''))
                if not client.verify_customer_posting_group(company_id, bc_customer['id'], bc_customer['number'], company_name):
                    bc_sync_logger.info('Rejected customer "%s": missing or invalid customerPostingGroup', bc_customer.get('displayName', ''))
                    bc_customer = None
                else:
                    bc_sync_logger.info('Accepted customer "%s": valid customerPostingGroup', bc_customer.get('displayName', ''))
        except (IndexError, AttributeError):
            pass

    if not bc_customer:
        bc_sync_logger.info('Searching customer: "%s" | Basis: fallback (any customer with posting group)', order.company_name)
        customers = client.get_customers(company_id)
        if customers:
            for customer in customers:
                posting_group = customer.get('customerPostingGroup') or customer.get('customerPostingGroupCode')
                if posting_group and posting_group != '' and posting_group != '0':
                    bc_customer = customer
                    break

            if not bc_customer:
                for customer in customers:
                    posting_group = customer.get('customerPostingGroup') or customer.get('customerPostingGroupCode')
                    if posting_group and posting_group != '' and posting_group != '0':
                        bc_customer = customer
                        break
        else:
            logger.error('No BC customers available for order %s', order.rfq_number)
            return False

    if bc_customer:
        bc_sync_logger.info('Extracted customer from BC response: "%s" (%s)', bc_customer.get('displayName', bc_customer.get('name')), bc_customer.get('number'))
    else:
        bc_sync_logger.info('No matching customer found in BC response')
        logger.error('No matching BC customer found for order %s', order.rfq_number)
        return False

    quote_data: Dict[str, Any] = {
        'customerNumber': bc_customer.get('number'),
        'documentDate': order.created_at.strftime('%Y-%m-%d'),
    }

    try:
        result = client.create_sales_quote(company_id, quote_data)
        if result:
            order.bc_quote_id = result.get('id')
            order.bc_synced_at = timezone.now()
            order.save(update_fields=['bc_quote_id', 'bc_synced_at'])
            return True
        else:
            logger.error('Failed to create BC sales quote for order %s', order.rfq_number)
            return False
    except Exception as exc:
        logger.error('Error creating BC quotation for order %s: %s', order.rfq_number, exc)
        return False


def convert_quote_to_sales_order(order) -> bool:
    """Convert a Sales Quote to a Sales Order in BC from an Order record."""
    if not order.bc_quote_id:
        logger.error('Order %s has no BC quote ID to convert', order.rfq_number)
        return False

    user = order.reviewed_by
    if not user:
        from django.contrib.auth import get_user_model
        User = get_user_model()
        try:
            user = User.objects.filter(is_superuser=True).first()
            if not user:
                logger.error('Order %s has no reviewer and no admin user found for Sales Order conversion', order.rfq_number)
                return False
        except Exception as exc:
            logger.error('Failed to get admin user for BC Sales Order conversion: %s', exc)
            return False

    client = build_bc_client_for_user(user)
    if not client:
        logger.error('Failed to build BC client for order %s', order.rfq_number)
        return False

    from django.conf import settings
    company_name = settings.BC_COMPANY_NAME
    if not company_name:
        logger.error('BC_COMPANY_NAME not configured in settings')
        return False

    company_id = client.get_company_by_name(company_name)
    if not company_id:
        logger.error('Failed to find company "%s" for order %s', company_name, order.rfq_number)
        return False

    try:
        result = client._post(
            f'companies({company_id})/salesQuotes({order.bc_quote_id})/makeSalesOrder',
            {}
        )
        if result:
            order.bc_sales_order_id = result.get('id')
            order.bc_sales_order_number = result.get('number')
            order.save(update_fields=['bc_sales_order_id', 'bc_sales_order_number'])
            return True
        else:
            logger.error('Failed to convert BC quote to Sales Order for order %s', order.rfq_number)
            return False
    except Exception as exc:
        logger.error('Error converting BC quotation to Sales Order for order %s: %s', order.rfq_number, exc)
        return False


def create_purchase_order_in_bc(order) -> bool:
    """Create a purchase order in BC from an Order record."""
    user = order.reviewed_by
    if not user:
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
        logger.error('Failed to build BC client for order %s', order.rfq_number)
        return False

    from django.conf import settings
    company_name = settings.BC_COMPANY_NAME
    if not company_name:
        logger.error('BC_COMPANY_NAME not configured in settings')
        return False

    company_id = client.get_company_by_name(company_name)
    if not company_id:
        logger.error('Failed to find company "%s" for order %s', company_name, order.rfq_number)
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
            from django.contrib.auth import get_user_model
            User = get_user_model()
            try:
                user = User.objects.filter(is_superuser=True).first()
                if not user:
                    return 0
            except Exception as exc:
                return 0
    
        client = build_bc_client_for_user(user)
        if not client:
            return 0
    
        from django.conf import settings
        company_name = settings.BC_COMPANY_NAME
        if not company_name:
            return 0
    
        company_id = client.get_company_by_name(company_name)
        if not company_id:
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
    
        return count
    
    
    def sync_products_from_bc(user) -> int:
        """Sync products from Business Central to local database."""
        client = build_bc_client_for_user(user)
        if not client:
            return 0
    
        from django.conf import settings
        company_name = settings.BC_COMPANY_NAME
        if not company_name:
            return 0
    
        company_id = client.get_company_by_name(company_name)
        if not company_id:
            return 0
    
        items = client.get_items(company_id)
        if not items:
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
    
        return count
