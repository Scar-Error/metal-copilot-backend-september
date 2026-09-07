from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from rfq.models import Order, OrderItem
import random


class Command(BaseCommand):
    help = 'Create mock order data for testing'

    def handle(self, *args, **options):
        self.stdout.write('Creating mock order data...')

        companies = [
            'Acme Corporation',
            'Tech Solutions Inc',
            'Global Industries',
            'Smart Manufacturing',
            'Precision Engineering',
        ]

        subjects = [
            'RFQ for Industrial Equipment',
            'Request for Quotation - Machinery',
            'RFQ: Control Systems',
            'Quotation Request - Automation',
            'RFQ for Manufacturing Equipment',
        ]

        statuses = ['pending', 'processing', 'completed', 'rejected']
        stages = ['inquiry', 'quotation', 'negotiation', 'order', 'fulfilled', 'archived']

        for i in range(10):
            order = Order.objects.create(
                rfq_number=f'RFQ-2024-{1000 + i}',
                company_name=companies[i % len(companies)],
                type='rfq',
                items_description='Industrial equipment and machinery',
                quantity=random.randint(1, 20),
                specifications='Standard industrial grade',
                delivery_date=timezone.now().date() + timedelta(days=random.randint(30, 90)),
                budget=random.randint(10000, 100000),
            )

            num_items = random.randint(2, 5)
            for j in range(num_items):
                OrderItem.objects.create(
                    order=order,
                    item_name=f'Item {j+1}',
                    item_code=f'ITEM-{j+1:03d}',
                    description=f'Description for item {j+1}',
                    quantity=random.randint(1, 10),
                    unit='pcs',
                    unit_price=random.randint(1000, 10000),
                    total_price=random.randint(1000, 10000) * random.randint(1, 10),
                    extraction_confidence=random.uniform(0.7, 0.95),
                )

        self.stdout.write(self.style.SUCCESS(f'Successfully created 10 mock orders'))
