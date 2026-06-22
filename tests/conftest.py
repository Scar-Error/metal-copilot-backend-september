from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model

User = get_user_model()


@pytest.fixture
def user(db) -> User:
    return User.objects.create_user(
        username='testuser',
        email='test@example.com',
        password='testpass123',
    )
