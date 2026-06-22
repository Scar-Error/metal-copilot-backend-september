from __future__ import annotations

import uuid
from datetime import datetime


def generate_rfq_number() -> str:
    """
    Generate a unique order number.

    Format: RFQ-YYYYMMDD-XXXXXXXX  (8 random hex digits)
    """
    date_part = datetime.now().strftime('%Y%m%d')
    random_part = str(uuid.uuid4())[:8].upper()
    return f'RFQ-{date_part}-{random_part}'
