"""
Bulk update Customer Posting Groups for all customers in Business Central.

This script:
1. Fetches all customers from Business Central
2. Updates customers without posting groups to use a default posting group
3. Logs all changes made

Usage:
    python scripts/bulk_update_customer_posting_groups.py

Requirements:
    - Django settings must be configured
    - BC credentials must be set in environment variables
"""

import os
import sys
import django

# Setup Django
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

import logging
from rfq.business_central import BusinessCentralClient, build_bc_client_for_user
from django.conf import settings
from django.contrib.auth import get_user_model

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def bulk_update_customer_posting_groups(default_posting_group='FOREIGN'):
    """Bulk update customer posting groups for all customers in BC."""

    logger.info('='*80)
    logger.info('Starting bulk update of Customer Posting Groups')
    logger.info(f'Default posting group: {default_posting_group}')
    logger.info('='*80)

    # Get admin user for BC client
    User = get_user_model()
    admin_user = User.objects.filter(is_superuser=True).first()
    if not admin_user:
        logger.error('No admin user found. Cannot build BC client.')
        return False

    # Build BC client
    client = build_bc_client_for_user(admin_user)
    if not client:
        logger.error('Failed to build BC client.')
        return False

    # Get company ID
    company_name = settings.BC_COMPANY_NAME
    if not company_name:
        logger.error('BC_COMPANY_NAME not configured in settings.')
        return False

    company_id = client.get_company_by_name(company_name)
    if not company_id:
        logger.error(f'Failed to find company "{company_name}"')
        return False

    logger.info(f'Company ID: {company_id}')

    # Fetch all customers
    logger.info('Fetching all customers from BC...')
    customers = client.get_customers(company_id)
    if not customers:
        logger.error('No customers found in BC.')
        return False

    logger.info(f'Found {len(customers)} customers')

    # Counters
    updated_count = 0
    skipped_count = 0
    error_count = 0

    # Process each customer
    for customer in customers:
        customer_number = customer.get('number', 'Unknown')
        customer_name = customer.get('displayName', 'Unknown')
        customer_id = customer.get('id')

        # Check if customer already has a posting group
        posting_group = customer.get('customerPostingGroup') or customer.get('customerPostingGroupCode')

        if posting_group and posting_group != '' and posting_group != '0':
            logger.info(f'Skipping {customer_number} ({customer_name}) - already has posting group: {posting_group}')
            skipped_count += 1
            continue

        # Update customer with default posting group
        logger.info(f'Updating {customer_number} ({customer_name}) - setting posting group to: {default_posting_group}')

        try:
            # Try to update via API (note: this may fail if BC API doesn't support it)
            result = client._patch(
                f'companies({company_id})/customers({customer_id})',
                {'customerPostingGroup': default_posting_group}
            )

            if result:
                logger.info(f'✓ Successfully updated {customer_number}')
                updated_count += 1
            else:
                logger.warning(f'✗ PATCH returned None for {customer_number} - API may not support this field')
                error_count += 1

        except Exception as exc:
            error_msg = str(exc)
            if '400' in error_msg or 'BadRequest' in error_msg:
                logger.warning(f'✗ PATCH failed for {customer_number} - API does not support posting group field')
                logger.warning(f'  Error: {error_msg}')
            else:
                logger.error(f'✗ Error updating {customer_number}: {exc}')
            error_count += 1

    # Summary
    logger.info('='*80)
    logger.info('Bulk Update Summary')
    logger.info(f'Total customers processed: {len(customers)}')
    logger.info(f'Updated: {updated_count}')
    logger.info(f'Skipped (already had posting group): {skipped_count}')
    logger.info(f'Errors/Unsupported: {error_count}')
    logger.info('='*80)

    if error_count > 0:
        logger.warning('')
        logger.warning('NOTE: If PATCH failed due to API limitations, you need to:')
        logger.warning('1. Manually set posting groups in Business Central UI')
        logger.warning('2. Or configure default posting group in Sales & Receivables Setup')
        logger.warning('3. New customers will need manual posting group assignment')

    return updated_count > 0


if __name__ == '__main__':
    # You can change the default posting group here
    DEFAULT_POSTING_GROUP = 'FOREIGN'  # Options: FOREIGN, DOMESTIC, EU

    success = bulk_update_customer_posting_groups(DEFAULT_POSTING_GROUP)
    sys.exit(0 if success else 1)
