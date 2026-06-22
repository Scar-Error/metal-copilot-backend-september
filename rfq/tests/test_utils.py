from __future__ import annotations

import re

import pytest

from rfq.utils import generate_rfq_number


class TestGenerateRfqNumber:
    def test_format(self) -> None:
        num = generate_rfq_number()
        assert re.match(r'^RFQ-\d{8}-[A-F0-9]{8}$', num), (
            f'Unexpected format: {num}'
        )

    def test_uniqueness(self) -> None:
        nums = {generate_rfq_number() for _ in range(100)}
        assert len(nums) == 100
