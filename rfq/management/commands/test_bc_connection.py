from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from rfq.business_central import BusinessCentralClient

User = get_user_model()


class Command(BaseCommand):
    help = 'Test Business Central connection - READ ONLY (no data modification)'

    def handle(self, *args, **options):
        self.stdout.write(self.style.WARNING('=== BC Connection Test (READ ONLY) ==='))
        self.stdout.write('This script only uses GET requests - no data will be modified\n')

        # Get a user with Microsoft token
        user = User.objects.filter(microsoft_token__isnull=False).first()
        if not user:
            self.stdout.write(self.style.ERROR('No user with Microsoft token found'))
            return

        self.stdout.write(f'Testing with user: {user.username}')

        # Build BC client
        try:
            token = user.microsoft_token
            if not token or not token.access_token:
                self.stdout.write(self.style.ERROR('No valid access token'))
                return

            client = BusinessCentralClient(access_token=token.access_token)
            self.stdout.write(self.style.SUCCESS('BC Client created successfully\n'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Failed to create BC client: {e}'))
            return

        # List all companies
        self.stdout.write('--- Available Companies ---')
        companies = client.get_companies()
        if not companies:
            self.stdout.write(self.style.ERROR('No companies found'))
            return

        for idx, company in enumerate(companies, 1):
            company_name = company.get('name', 'Unknown')
            company_id = company.get('id', 'Unknown')
            self.stdout.write(f'{idx}. {company_name} (ID: {company_id})')

        self.stdout.write('')

        # Try to retrieve test customer from each company
        test_customer_number = '3.31.110.2482'
        self.stdout.write(f'--- Searching for test customer: {test_customer_number} ---')

        found_in_company = None
        for company in companies:
            company_id = company.get('id')
            company_name = company.get('name')

            try:
                # GET request to retrieve customer (read-only)
                result = client._get(f'companies({company_id})/customers({test_customer_number})')
                if result:
                    self.stdout.write(
                        self.style.SUCCESS(
                            f'✓ Found in company: {company_name}'
                        )
                    )
                    self.stdout.write(f'  Customer Name: {result.get("displayName", "N/A")}')
                    self.stdout.write(f'  Email: {result.get("email", "N/A")}')
                    found_in_company = company_name
                else:
                    self.stdout.write(
                        self.style.WARNING(
                            f'✗ Not found in company: {company_name}'
                        )
                    )
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(
                        f'✗ Error checking company {company_name}: {e}'
                    )
                )

        self.stdout.write('')
        if found_in_company:
            self.stdout.write(
                self.style.SUCCESS(
                    f'Test customer found in: {found_in_company}'
                )
            )
            self.stdout.write('API connection is working correctly.')
        else:
            self.stdout.write(
                self.style.ERROR(
                    'Test customer not found in any company'
                )
            )
            self.stdout.write('Please verify the customer number and company access.')

        self.stdout.write('')
        self.stdout.write(self.style.WARNING('=== Test Complete (No Data Modified) ==='))
