"""
Simple standalone script to test BC connection - READ ONLY
Does not require Django initialization to avoid URL conflicts.
"""
import os
import sys
import requests

# Add the project to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

MICROSOFT_CLIENT_ID = os.getenv('MICROSOFT_CLIENT_ID')
MICROSOFT_CLIENT_SECRET = os.getenv('MICROSOFT_CLIENT_SECRET')
MICROSOFT_TENANT_ID = os.getenv('MICROSOFT_TENANT_ID')

print('=== BC Connection Test (READ ONLY) ===')
print('This script only uses GET requests - no data will be modified\n')

# Step 1: Get access token
print('Step 1: Getting access token...')
token_url = f'https://login.microsoftonline.com/{MICROSOFT_TENANT_ID}/oauth2/v2.0/token'
token_data = {
    'client_id': MICROSOFT_CLIENT_ID,
    'client_secret': MICROSOFT_CLIENT_SECRET,
    'scope': 'https://api.businesscentral.dynamics.com/.default',
    'grant_type': 'client_credentials',
}

try:
    token_response = requests.post(token_url, data=token_data)
    token_response.raise_for_status()
    access_token = token_response.json().get('access_token')
    print('✓ Access token obtained\n')
except Exception as e:
    print(f'✗ Failed to get access token: {e}')
    sys.exit(1)

# Step 2: List all companies
print('Step 2: Listing all companies...')
base_url = f'https://api.businesscentral.dynamics.com/v2.0/{MICROSOFT_TENANT_ID}/Production/api/v2.0'
headers = {
    'Authorization': f'Bearer {access_token}',
    'Accept': 'application/json',
}

try:
    companies_response = requests.get(f'{base_url}/companies', headers=headers)
    companies_response.raise_for_status()
    companies = companies_response.json().get('value', [])
    
    print(f'Found {len(companies)} companies:')
    for idx, company in enumerate(companies, 1):
        company_name = company.get('name', 'Unknown')
        company_id = company.get('id', 'Unknown')
        print(f'  {idx}. {company_name} (ID: {company_id})')
    print()
except Exception as e:
    print(f'✗ Failed to list companies: {e}')
    sys.exit(1)

# Step 3: Search for test customer
test_customer_number = '3.31.110.2482'
print(f'Step 3: Searching for test customer: {test_customer_number}')

found_in_company = None
for company in companies:
    company_id = company.get('id')
    company_name = company.get('name')
    
    try:
        # GET request to retrieve customer (read-only)
        customer_url = f'{base_url}/companies({company_id})/customers({test_customer_number})'
        customer_response = requests.get(customer_url, headers=headers)
        
        if customer_response.status_code == 200:
            customer_data = customer_response.json()
            print(f'✓ Found in company: {company_name}')
            print(f'  Customer Name: {customer_data.get("displayName", "N/A")}')
            print(f'  Email: {customer_data.get("email", "N/A")}')
            found_in_company = company_name
        else:
            print(f'✗ Not found in company: {company_name}')
    except Exception as e:
        print(f'✗ Error checking company {company_name}: {e}')

print()
if found_in_company:
    print(f'✓ Test customer found in: {found_in_company}')
    print('API connection is working correctly.')
else:
    print('✗ Test customer not found in any company')
    print('Please verify the customer number and company access.')

print()
print('=== Test Complete (No Data Modified) ===')
