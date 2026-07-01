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
            logger.info('BC GET Request: %s', url)
            response = requests.get(url, headers=self.headers, timeout=30)
            response.raise_for_status()
            result = response.json()
            logger.info('BC GET Response (first 500 chars): %s', str(result)[:500])
            return result
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
            logger.info('BC POST Request: %s', url)
            logger.info('BC POST Data being sent: %s', str(data)[:1000])
            response = requests.post(url, headers=self.headers, json=data, timeout=30)
            response.raise_for_status()
            result = response.json()
            logger.info('BC POST Response (first 500 chars): %s', str(result)[:500])
            return result
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
            logger.info('BC PATCH Request: %s', url)
            logger.info('BC PATCH Data being sent: %s', str(data)[:1000])
            response = requests.patch(url, headers=self.headers, json=data, timeout=30)
            response.raise_for_status()
            result = response.json()
            logger.info('BC PATCH Response (first 500 chars): %s', str(result)[:500])
            return result
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
        logger.info(
            'Partial match search for "%s" in company %s: found %d customers',
            company_hint, company_id, len(customers) if customers else 0
        )
        hint_lower = company_hint.lower()
        for customer in customers:
            display_name = customer.get('displayName', '').lower()
            name = customer.get('name', '').lower()
            if hint_lower in display_name or hint_lower in name:
                logger.info(
                    'Partial match found: "%s" matches customer "%s"',
                    company_hint, customer.get('displayName', customer.get('name', 'Unknown'))
                )
                return customer
        logger.info('No partial match found for "%s"', company_hint)
        return None

    def create_customer(self, company_id: str, customer_name: str, email: str = '', template_id: str = '', default_posting_group: str = 'FOREIGN') -> Optional[Dict]:
        """Create a new customer in BC. Returns created customer or None.

        Args:
            company_id: BC company ID
            customer_name: Customer display name
            email: Customer email (optional)
            template_id: BC configuration template ID for auto-assignment of posting groups (optional)
            default_posting_group: Default posting group to assign (optional, defaults to 'FOREIGN')

        Returns:
            Created customer dict or None if creation fails
        """
        customer_data = {
            'displayName': customer_name,
            'type': 'Company',
        }
        if email:
            customer_data['email'] = email
        if template_id:
            customer_data['templateId'] = template_id

        logger.info('Creating customer with default posting group: %s. Data: %s', default_posting_group, customer_data)

        try:
            result = self._post(f'companies({company_id})/customers', customer_data)
            if result:
                logger.info(
                    'Created new BC customer "%s" in company %s (number: %s)',
                    customer_name, company_id, result.get('number', 'N/A')
                )
                return result
            logger.error(
                'BC POST returned None for customer creation "%s" in company %s',
                customer_name, company_id
            )
            return None
        except Exception as exc:
            error_msg = str(exc)
            if '400' in error_msg or 'BadRequest' in error_msg:
                logger.error(
                    'BC POST failed with HTTP 400 for customer creation "%s": %s',
                    customer_name, error_msg
                )
            else:
                logger.error(
                    'Failed to create BC customer "%s" in company %s: %s',
                    customer_name, company_id, exc
                )
            return None

    def verify_customer_posting_group(self, company_id: str, customer_id: str, customer_number: str) -> bool:
        """Verify that a customer has a valid Customer Posting Group assigned.

        Args:
            company_id: BC company ID
            customer_id: Customer ID (GUID)
            customer_number: Customer number for logging

        Returns:
            True if customer has valid posting group, False otherwise
        """
        try:
            customer = self._get(f'companies({company_id})/customers({customer_id})')
            if not customer:
                logger.error('Failed to fetch customer %s for posting group verification', customer_number)
                return False

            # Check for posting group in various possible field names
            posting_group = customer.get('customerPostingGroup') or customer.get('customerPostingGroupCode')
            if posting_group and posting_group != '' and posting_group != '0':
                logger.info('Customer %s has valid posting group: %s', customer_number, posting_group)
                return True

            logger.error(
                'Customer %s has invalid or missing posting group (value: %s). '
                'Cannot create sales quote without valid posting group.',
                customer_number, posting_group
            )
            return False
        except Exception as exc:
            error_msg = str(exc)
            if '400' in error_msg or 'BadRequest' in error_msg:
                logger.error(
                    'BC GET failed with HTTP 400 when verifying posting group for customer %s: %s',
                    customer_number, error_msg
                )
            else:
                logger.error(
                    'Failed to verify posting group for customer %s: %s',
                    customer_number, exc
                )
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
        """Update Sales & Receivables Setup to set default customer posting group.

        Args:
            company_id: BC company ID
            default_customer_posting_group: Default posting group code (e.g., 'FOREIGN')

        Returns:
            True if successful, False otherwise
        """
        try:
            result = self._patch(
                f'companies({company_id})/salesReceivablesSetup',
                {'defaultCustomerPostingGroup': default_customer_posting_group}
            )
            if result:
                logger.info(
                    'Successfully set default Customer Posting Group to "%s" in Sales & Receivables Setup',
                    default_customer_posting_group
                )
                return True
            logger.warning('Failed to update Sales & Receivables Setup - PATCH returned None')
            return False
        except Exception as exc:
            error_msg = str(exc)
            if '400' in error_msg or 'BadRequest' in error_msg:
                logger.warning(
                    'BC PATCH failed for Sales & Receivables Setup - field may not be supported: %s',
                    error_msg
                )
            else:
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
    logger.info('='*80)
    logger.info('Starting BC quotation creation for order %s', order.rfq_number)
    logger.info('Order Details:')
    logger.info('  - RFQ Number: %s', order.rfq_number)
    logger.info('  - Company Name: %s', order.company_name)
    logger.info('  - Email Sender: %s', order.email_sender)
    logger.info('  - Items Description: %s', order.items_description)
    logger.info('  - Quantity: %s', order.quantity)
    logger.info('  - Delivery Date: %s', order.delivery_date)
    logger.info('  - Budget: %s', order.budget)
    logger.info('  - Number of Order Items: %d', order.items.count())
    
    for idx, item in enumerate(order.items.all(), 1):
        logger.info('  - Order Item %d: name=%s, code=%s, quantity=%s, unit=%s, unit_price=%s',
                   idx, item.item_name, item.item_code, item.quantity, item.unit, item.unit_price)
    
    logger.info('='*80)
    
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
        logger.error('Failed to build BC client for order %s', order.rfq_number)
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
    
    logger.info('BC Company ID found: %s for company "%s"', company_id, company_name)

    # Priority-based customer matching:
    # 1. Try exact match with AI-extracted company_name
    # 2. Try partial match with company name keywords
    # 3. Try email domain extraction
    # 4. Create customer from email domain (Option 3)
    # 5. Create customer from company name (Option 1)
    # 6. Use generic/default customer (last resort)
    PLACEHOLDER_COMPANIES = ['not specified', 'unknown company', 'various items', '']

    bc_customer = None
    company_name_used = order.company_name

    # Priority 1: Try exact match with AI-extracted company_name
    if order.company_name.lower() not in PLACEHOLDER_COMPANIES:
        bc_customer = client.get_customer_by_name(company_id, order.company_name)
        if bc_customer:
            # Check if customer has a valid posting group
            posting_group = bc_customer.get('customerPostingGroup') or bc_customer.get('customerPostingGroupCode')
            if not posting_group or posting_group == '' or posting_group == '0':
                logger.warning(
                    'Customer %s (%s) has no valid Customer Posting Group (value: %s), will try other matching methods',
                    bc_customer.get('displayName', 'Unknown'), bc_customer.get('number', 'Unknown'), posting_group
                )
                # Set bc_customer to None to try other matching methods
                bc_customer = None
            else:
                company_name_used = order.company_name
                logger.info(
                    'Matched BC customer using exact company name "%s" for order %s with posting group: %s',
                    order.company_name, order.rfq_number, posting_group
                )

    # Priority 2: Try partial match with company name keywords
    if not bc_customer and order.company_name.lower() not in PLACEHOLDER_COMPANIES:
        # Extract keywords from company name (split by space, take first 2-3 words)
        company_keywords = order.company_name.split()[:3]
        logger.info(
            'Trying partial BC customer match for order %s using keywords: %s',
            order.rfq_number, company_keywords
        )
        for keyword in company_keywords:
            if len(keyword) > 3:  # Skip very short words
                bc_customer = client.get_customer_by_partial_match(company_id, keyword)
                if bc_customer:
                    # Check if customer has a valid posting group
                    posting_group = bc_customer.get('customerPostingGroup') or bc_customer.get('customerPostingGroupCode')
                    if not posting_group or posting_group == '' or posting_group == '0':
                        logger.warning(
                            'Customer %s (%s) has no valid Customer Posting Group (value: %s), will try other matching methods',
                            bc_customer.get('displayName', 'Unknown'), bc_customer.get('number', 'Unknown'), posting_group
                        )
                        # Set bc_customer to None to try other matching methods
                        bc_customer = None
                        continue
                    else:
                        company_name_used = f"partial match ({keyword})"
                        logger.info(
                            'Matched BC customer using partial company name "%s" for order %s with posting group: %s',
                            keyword, order.rfq_number, posting_group
                        )
                        break

    # Priority 3: Try email domain extraction
    if not bc_customer and order.email_sender:
        try:
            email_domain = order.email_sender.split('@')[1].split('.')[0]
            bc_customer = client.get_customer_by_partial_match(company_id, email_domain)
            if bc_customer:
                # Check if customer has a valid posting group
                posting_group = bc_customer.get('customerPostingGroup') or bc_customer.get('customerPostingGroupCode')
                if not posting_group or posting_group == '' or posting_group == '0':
                    logger.warning(
                        'Customer %s (%s) has no valid Customer Posting Group (value: %s), will create new customer instead',
                        bc_customer.get('displayName', 'Unknown'), bc_customer.get('number', 'Unknown'), posting_group
                    )
                    # Set bc_customer to None to trigger new customer creation
                    bc_customer = None
                else:
                    company_name_used = f"email domain ({email_domain})"
                    logger.info(
                        'Matched BC customer using email domain "%s" for order %s with posting group: %s',
                        email_domain, order.rfq_number, posting_group
                    )
        except (IndexError, AttributeError):
            pass

    # Priority 4: Create customer from email domain - DISABLED
    # BC API does not support setting posting groups programmatically
    # All API-created customers will lack posting groups and cannot be used for sales quotes
    if not bc_customer and order.email_sender:
        logger.warning(
            'Customer "%s" not found in BC. '
            'Please manually create this customer in Business Central with a valid Customer Posting Group (FOREIGN, DOMESTIC, or EU). '
            'Using fallback customer for order %s.',
            order.company_name, order.rfq_number
        )

    # Priority 5: Create customer from company name - DISABLED
    # BC API does not support setting posting groups programmatically
    # All API-created customers will lack posting groups and cannot be used for sales quotes
    if not bc_customer and order.company_name.lower() not in PLACEHOLDER_COMPANIES:
        logger.warning(
            'Customer "%s" not found in BC. '
            'Please manually create this customer in Business Central with a valid Customer Posting Group (FOREIGN, DOMESTIC, or EU). '
            'Using fallback customer for order %s.',
            order.company_name, order.rfq_number
        )

    # Priority 6: Use generic/default customer (last resort)
    if not bc_customer:
        customers = client.get_customers(company_id)
        if customers:
            # Find first customer with valid posting group
            for customer in customers:
                posting_group = customer.get('customerPostingGroup') or customer.get('customerPostingGroupCode')
                if posting_group and posting_group != '' and posting_group != '0':
                    bc_customer = customer
                    company_name_used = f"generic customer ({customer.get('displayName', customer.get('name', 'Unknown'))})"
                    logger.warning(
                        'Using generic BC customer "%s" for order %s (no match found for "%s") with posting group: %s',
                        customer.get('displayName', customer.get('name', 'Unknown')),
                        order.rfq_number,
                        order.company_name,
                        posting_group
                    )
                    break
            
            # If no customer with valid posting group found, use fallback customer
            # BC API does not support setting posting groups programmatically
            # For millions of customers, we use a generic fallback customer with valid posting group
            # This ensures BC sync works automatically without manual customer creation
            if not bc_customer:
                logger.warning(
                    'No BC customer with valid posting group found for "%s". '
                    'Using generic fallback customer for order %s. '
                    'Note: All orders will use this generic customer in BC. '
                    'For proper customer tracking, manually create customers in BC with posting groups.',
                    order.company_name, order.rfq_number
                )
                # Use the first customer with valid posting group as generic fallback
                for customer in customers:
                    posting_group = customer.get('customerPostingGroup') or customer.get('customerPostingGroupCode')
                    if posting_group and posting_group != '' and posting_group != '0':
                        bc_customer = customer
                        company_name_used = f"generic fallback ({customer.get('displayName', 'Unknown')})"
                        logger.info(
                            'Using generic fallback customer "%s" with posting group %s for order %s',
                            customer.get('displayName', 'Unknown'), posting_group, order.rfq_number
                        )
                        break
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
    
    logger.info('BC Quote Data being sent:')
    logger.info('  - Customer Number: %s', bc_customer.get('number'))
    logger.info('  - Customer Display Name: %s', bc_customer.get('displayName'))
    logger.info('  - Document Date: %s', quote_data['documentDate'])
    logger.info('  - Customer Match Method: %s', company_name_used)

    try:
        result = client.create_sales_quote(company_id, quote_data)
        if result:
            logger.info('='*80)
            logger.info('BC Sales Quote Created Successfully for order %s', order.rfq_number)
            logger.info('BC Response Data:')
            logger.info('  - Quote ID: %s', result.get('id', 'N/A'))
            logger.info('  - Quote Number: %s', result.get('number', 'N/A'))
            logger.info('  - Customer Number: %s', result.get('customerNumber', 'N/A'))
            logger.info('  - Document Date: %s', result.get('documentDate', 'N/A'))
            logger.info('  - Status: %s', result.get('status', 'N/A'))
            logger.info('='*80)
            order.bc_quote_id = result.get('id')
            order.bc_synced_at = timezone.now()
            order.save(update_fields=['bc_quote_id', 'bc_synced_at'])
            return True
        else:
            logger.error('Failed to create BC sales quote for order %s - no result returned', order.rfq_number)
            return False
    except Exception as exc:
        error_msg = str(exc)
        if '400' in error_msg or 'BadRequest' in error_msg or 'FieldValidationException' in error_msg:
            # Extract BC error message if available
            logger.error(
                'BC POST failed with HTTP 400 when creating sales quote for order %s: %s',
                order.rfq_number, error_msg
            )
            logger.error(
                'This is likely due to missing Customer Posting Group on customer %s. '
                'Please configure Customer Posting Groups in Business Central.',
                bc_customer.get('number')
            )
        else:
            logger.error('Error creating BC quotation for order %s: %s', order.rfq_number, exc)
        return False


def convert_quote_to_sales_order(order) -> bool:
    """Convert a Sales Quote to a Sales Order in BC from an Order record."""
    logger.info('='*80)
    logger.info('Starting BC Sales Order conversion for order %s', order.rfq_number)
    logger.info('Order Details:')
    logger.info('  - RFQ Number: %s', order.rfq_number)
    logger.info('  - Company Name: %s', order.company_name)
    logger.info('  - BC Quote ID: %s', order.bc_quote_id)
    logger.info('='*80)

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
        logger.error(
            'Failed to find company "%s" for order %s',
            company_name, order.rfq_number
        )
        return False

    logger.info('BC Company ID found: %s for company "%s"', company_id, company_name)

    # Convert quote to sales order using BC API
    try:
        # BC API endpoint to convert quote to sales order
        result = client._post(
            f'companies({company_id})/salesQuotes({order.bc_quote_id})/makeSalesOrder',
            {}
        )
        if result:
            logger.info('='*80)
            logger.info('BC Sales Order Created Successfully for order %s', order.rfq_number)
            logger.info('BC Response Data:')
            logger.info('  - Sales Order ID: %s', result.get('id', 'N/A'))
            logger.info('  - Sales Order Number: %s', result.get('number', 'N/A'))
            logger.info('='*80)
            order.bc_sales_order_id = result.get('id')
            order.bc_sales_order_number = result.get('number')
            order.save(update_fields=['bc_sales_order_id', 'bc_sales_order_number'])
            return True
        else:
            logger.error('Failed to convert BC quote to Sales Order for order %s - no result returned', order.rfq_number)
            return False
    except Exception as exc:
        logger.error('Error converting BC quotation to Sales Order for order %s: %s', order.rfq_number, exc)
        return False


def create_purchase_order_in_bc(order) -> bool:
    """Create a purchase order in BC from an Order record."""
    logger.info('='*80)
    logger.info('Starting BC purchase order creation for order %s', order.rfq_number)
    logger.info('Order Details:')
    logger.info('  - RFQ Number: %s', order.rfq_number)
    logger.info('  - Supplier: %s', order.supplier.company_name if order.supplier else 'N/A')
    logger.info('  - Created At: %s', order.created_at)
    logger.info('  - Delivery Date: %s', order.delivery_date)
    logger.info('='*80)
    
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
        logger.error('Failed to build BC client for order %s', order.rfq_number)
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
    
    logger.info('BC Company ID found: %s for company "%s"', company_id, company_name)

    po_data: Dict[str, Any] = {
        'buyFromVendorNumber': order.supplier.company_name if order.supplier else '',
        'documentDate': order.created_at.strftime('%Y-%m-%d'),
        'currencyCode': 'EUR',
    }
    if order.delivery_date:
        po_data['dueDate'] = order.delivery_date.strftime('%Y-%m-%d')
    
    logger.info('BC PO Data being sent:')
    logger.info('  - Vendor Number: %s', po_data['buyFromVendorNumber'])
    logger.info('  - Document Date: %s', po_data['documentDate'])
    logger.info('  - Currency Code: %s', po_data['currencyCode'])
    logger.info('  - Due Date: %s', po_data.get('dueDate', 'N/A'))

    try:
        result = client.create_purchase_order(company_id, po_data)
        if result:
            logger.info('='*80)
            logger.info('BC Purchase Order Created Successfully for order %s', order.rfq_number)
            logger.info('BC Response Data:')
            logger.info('  - PO ID: %s', result.get('id', 'N/A'))
            logger.info('  - PO Number: %s', result.get('number', 'N/A'))
            logger.info('  - Vendor Number: %s', result.get('buyFromVendorNumber', 'N/A'))
            logger.info('  - Document Date: %s', result.get('documentDate', 'N/A'))
            logger.info('  - Status: %s', result.get('status', 'N/A'))
            logger.info('='*80)
            return True
        else:
            logger.error('Failed to create BC purchase order for order %s - no result returned', order.rfq_number)
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
