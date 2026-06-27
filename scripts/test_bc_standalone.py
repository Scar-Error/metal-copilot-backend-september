"""
Standalone script to test BC connection - READ ONLY
Uses Django models but avoids URL routing conflicts.
"""
import os
import sys
import django

# Setup Django without URL routing
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Initialize Django
django.setup()

from django.contrib.auth import get_user_model
from rfq.business_central import BusinessCentralClient

User = get_user_model()

print('=== BC Connection Test (READ ONLY) ===')
print('This script only uses GET requests - no data will be modified\n')

# Get a user with Microsoft token
user = User.objects.filter(microsoft_token__isnull=False).first()
if not user:
    print('✗ No user with Microsoft token found')
    print('Please ensure a user has authenticated with Microsoft OAuth')
    sys.exit(1)

print(f'Testing with user: {user.username}')

# Build BC client
try:
    token = user.microsoft_token
    if not token or not token.access_token:
        print('✗ No valid access token')
        print('Please ensure the user has authenticated with Microsoft OAuth')
        sys.exit(1)

    client = BusinessCentralClient(access_token=token.access_token)
    print('✓ BC Client created successfully\n')
except Exception as e:
    print(f'✗ Failed to create BC client: {e}')
    sys.exit(1)

# List all companies
print('--- Available Companies ---')
companies = client.get_companies()
if not companies:
    print('✗ No companies found')
    sys.exit(1)

for idx, company in enumerate(companies, 1):
    company_name = company.get('name', 'Unknown')
    company_id = company.get('id', 'Unknown')
    print(f'{idx}. {company_name} (ID: {company_id})')

print('')

# Try to retrieve test customer from each company
test_customer_number = '3.31.110.2482'
print(f'--- Searching for test customer: {test_customer_number} ---')

found_in_company = None
for company in companies:
    company_id = company.get('id')
    company_name = company.get('name')

    try:
        # GET request to retrieve customer (read-only)
        result = client._get(f'companies({company_id})/customers({test_customer_number})')
        if result:
            print(f'✓ Found in company: {company_name}')
            print(f'  Customer Name: {result.get("displayName", "N/A")}')
            print(f'  Email: {result.get("email", "N/A")}')
            found_in_company = company_name
        else:
            print(f'✗ Not found in company: {company_name}')
    except Exception as e:
        print(f'✗ Error checking company {company_name}: {e}')

print('')
if found_in_company:
    print(f'✓ Test customer found in: {found_in_company}')
    print('API connection is working correctly.')
else:
    print('✗ Test customer not found in any company')
    print('Please verify the customer number and company access.')

print('')
print('=== Test Complete (No Data Modified) ===')
