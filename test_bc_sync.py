import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from rfq.models import Order
from rfq.business_central import create_quotation_in_bc

# Test the BC sync fix for order 35
order = Order.objects.get(id=35)
print(f"Testing BC sync for order {order.rfq_number}")
print(f"Company name: {order.company_name}")
print(f"Email sender: {order.email_sender}")

result = create_quotation_in_bc(order)
print(f"BC sync result: {result}")
