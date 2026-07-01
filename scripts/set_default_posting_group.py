"""
Set Default Customer Posting Group in Business Central Sales & Receivables Setup.

This script attempts to set the default customer posting group via API.
If successful, all new customers created in BC will automatically have this posting group.

Usage:
    python scripts/set_default_posting_group.py

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


def set_default_posting_group(default_posting_group='FOREIGN'):
    """Set default customer posting group in Sales & Receivables Setup."""

    logger.info('='*80)
    logger.info('Setting Default Customer Posting Group in BC')
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

    # Try to update Sales & Receivables Setup
    logger.info('Attempting to update Sales & Receivables Setup...')
    success = client.update_sales_receivables_setup(company_id, default_posting_group)

    if success:
        logger.info('='*80)
        logger.info('SUCCESS: Default Customer Posting Group set successfully!')
        logger.info('All new customers created in BC will now have this posting group.')
        logger.info('='*80)
        return True
    else:
        logger.error('='*80)
        logger.error('FAILED: Could not set default posting group via API.')
        logger.error('Possible reasons:')
        logger.error('1. BC API does not support this field')
        logger.error('2. Field name is different in your BC version')
        logger.error('3. Insufficient permissions')
        logger.error('')
        logger.error('Alternative: Manually set in BC UI:')
        logger.error('- Go to Sales & Receivables Setup')
        logger.error('- Look for "Default Customer Posting Group" field')
        logger.error('- Set it to: ' + default_posting_group)
        logger.error('='*80)
        return False


if __name__ == '__main__':
    # You can change the default posting group here
    DEFAULT_POSTING_GROUP = 'FOREIGN'  # Options: FOREIGN, DOMESTIC, EU

    success = set_default_posting_group(DEFAULT_POSTING_GROUP)
    sys.exit(0 if success else 1)
