from __future__ import annotations

from datetime import timedelta
from typing import Optional
import uuid

from django.contrib.auth.models import AbstractUser
from django.db import models


class CustomUser(AbstractUser):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    class Meta:
        db_table = 'auth_user'
        verbose_name = 'User'
        verbose_name_plural = 'Users'

    def __str__(self) -> str:
        return self.username


class MicrosoftToken(models.Model):
    user = models.OneToOneField(
        CustomUser, on_delete=models.CASCADE,
        related_name='microsoft_token',
    )
    access_token = models.TextField()
    refresh_token = models.TextField(blank=True)
    token_expires_at = models.DateTimeField()
    microsoft_id = models.CharField(max_length=255, unique=True)
    microsoft_email = models.EmailField()
    microsoft_name = models.CharField(max_length=255)
    scopes = models.TextField(blank=True)
    token_type = models.CharField(max_length=50, default='Bearer')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Microsoft Token'
        verbose_name_plural = 'Microsoft Tokens'

    def __str__(self) -> str:
        return f'{self.user.username} - {self.microsoft_email}'

    def is_expired(self, buffer_minutes: int = 5) -> bool:
        """
        Check if the token is expired (or expires within *buffer_minutes*).
        Using a buffer avoids 401 errors due to clock skew or server-side
        revocation near the expiry boundary.
        """
        from django.utils import timezone
        return timezone.now() >= self.token_expires_at - timedelta(minutes=buffer_minutes)

    def refresh_if_expired(self, force: bool = False) -> bool:
        """
        Try to refresh the token via MSAL if it's expired (or if *force* is True).
        Returns True if now valid.
        """
        if not force and not self.is_expired():
            return True
        if not self.refresh_token:
            return False
        try:
            import msal
            from django.conf import settings
            app = msal.ConfidentialClientApplication(
                settings.MICROSOFT_CLIENT_ID,
                authority=(
                    f'https://login.microsoftonline.com/{settings.MICROSOFT_TENANT_ID}'
                ),
                client_credential=settings.MICROSOFT_CLIENT_SECRET,
            )
            result = app.acquire_token_by_refresh_token(
                self.refresh_token,
                scopes=['User.Read', 'Mail.Read', 'Mail.Send'],
            )
            if 'access_token' in result:
                self.access_token = result['access_token']
                if 'refresh_token' in result:
                    self.refresh_token = result['refresh_token']
                from django.utils import timezone
                self.token_expires_at = timezone.now() + timedelta(
                    seconds=result.get('expires_in', 3600),
                )
                self.save()
                return True
            return False
        except Exception:
            return False
