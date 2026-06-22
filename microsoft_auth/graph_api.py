from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

import requests
from django.conf import settings
from django.utils import timezone

from rfq.interfaces import EmailMessage, AttachmentData

logger = logging.getLogger(__name__)


class GraphEmailProvider:
    """
    Microsoft Graph API client conforming to the EmailProvider interface.

    1.  Tokens are accepted via constructor (no DB side-effects).
    2.  If a ``user`` is provided, tokens are persisted to the DB after
        a successful refresh.
    """

    def __init__(
        self,
        access_token: str,
        refresh_token: str = '',
        token_expires_at: Optional[datetime] = None,
        user=None,
    ) -> None:
        self.base_url = settings.MICROSOFT_GRAPH_API_URL.rstrip('/')
        self._access_token = access_token
        self._refresh_token = refresh_token
        self._token_expires_at = token_expires_at
        self._user = user

    # ------------------------------------------------------------------
    # Public API – EmailProvider interface
    # ------------------------------------------------------------------

    def fetch_emails(
        self,
        folder: str = 'Inbox',
        limit: int = 50,
        days_back: int = 7,
    ) -> List[EmailMessage]:
        result = self._get(
            'me/mailFolders',
            params={'$top': 50},
        )
        if not result:
            return []

        folder_id: Optional[str] = None
        for f in result.get('value', []):
            if f.get('displayName') == folder:
                folder_id = f.get('id')
                break

        if not folder_id:
            logger.error('Folder %s not found', folder)
            return []

        since = (datetime.now() - timedelta(days=days_back)).isoformat() + 'Z'
        emails = self._get(
            f'me/mailFolders/{folder_id}/messages',
            params={
                '$top': limit,
                '$orderby': 'receivedDateTime desc',
                '$select': 'id,subject,from,receivedDateTime,body,hasAttachments,attachments',
                '$filter': f'receivedDateTime ge {since}',
            },
        )
        return self._normalize_emails(emails.get('value', []) if emails else [])

    def get_email_by_id(self, email_id: str) -> Optional[EmailMessage]:
        result = self._get(
            f'me/messages/{email_id}',
            params={
                '$select': (
                    'id,subject,from,toRecipients,ccRecipients,'
                    'receivedDateTime,body,bodyPreview,hasAttachments,'
                    'attachments,internetMessageHeaders'
                ),
            },
        )
        if not result:
            return None
        emails = self._normalize_emails([result])
        return emails[0] if emails else None

    def download_attachment(
        self,
        email_id: str,
        attachment_id: str,
    ) -> Optional[bytes]:
        url = (
            f'{self.base_url}/me/messages/{email_id}'
            f'/attachments/{attachment_id}/$value'
        )
        headers = {'Authorization': f'Bearer {self._access_token}'}
        try:
            resp = requests.get(url, headers=headers, timeout=30)
            resp.raise_for_status()
            return resp.content
        except requests.RequestException as exc:
            logger.error('Attachment download failed: %s', exc)
            return None

    def get_attachments(self, email_id: str) -> List[AttachmentData]:
        result = self._get(f'me/messages/{email_id}/attachments')
        if not result:
            return []
        return [
            AttachmentData(
                id=a['id'],
                name=a.get('name', 'unnamed'),
                size=a.get('size', 0),
                content_type=a.get('contentType', ''),
            )
            for a in result.get('value', [])
        ]

    def send_email(
        self,
        to: str,
        subject: str,
        body: str,
        content_type: str = 'HTML',
    ) -> bool:
        payload: Dict[str, Any] = {
            'message': {
                'subject': subject,
                'body': {
                    'contentType': content_type,
                    'content': body,
                },
                'toRecipients': [
                    {'emailAddress': {'address': to}},
                ],
            },
            'saveToSentItems': 'true',
        }
        result = self._post('me/sendMail', data=payload)
        return result is not None

    def mark_as_processed(self, email_id: str) -> bool:
        result = self._patch(
            f'me/messages/{email_id}',
            data={'categories': ['RFQ Processed']},
        )
        return result is not None

    def get_user_email(self) -> str:
        info = self._get('me', params={'$select': 'mail,userPrincipalName'})
        if info:
            return info.get('mail') or info.get('userPrincipalName', '')
        return ''

    # ------------------------------------------------------------------
    # Token helpers
    # ------------------------------------------------------------------

    def is_token_expired(self) -> bool:
        if not self._token_expires_at:
            return True
        return timezone.now() >= self._token_expires_at

    def refresh_token_if_needed(self) -> bool:
        """Attempt OAuth2 refresh. Returns True if token is now valid."""
        if not self.is_token_expired():
            return True
        if not self._refresh_token:
            logger.warning('No refresh token available')
            return False
        try:
            import msal
            app = msal.ConfidentialClientApplication(
                client_id=settings.MICROSOFT_CLIENT_ID,
                client_credential=settings.MICROSOFT_CLIENT_SECRET,
                authority=(
                    f'https://login.microsoftonline.com/'
                    f'{settings.MICROSOFT_TENANT_ID}'
                ),
            )
            result = app.acquire_token_by_refresh_token(
                self._refresh_token,
                scopes=['https://graph.microsoft.com/.default'],
            )
            if 'access_token' in result:
                self._access_token = result['access_token']
                if 'refresh_token' in result:
                    self._refresh_token = result['refresh_token']
                expires_in = result.get('expires_in', 3600)
                self._token_expires_at = timezone.now() + timedelta(
                    seconds=expires_in,
                )
                self._persist_tokens()
                logger.info('Token refreshed successfully')
                return True
            logger.error('Token refresh failed: %s', result.get('error'))
            return False
        except Exception as exc:
            logger.error('Token refresh error: %s', exc)
            return False

    # ------------------------------------------------------------------
    # Token persistence
    # ------------------------------------------------------------------

    def _persist_tokens(self) -> None:
        """Save refreshed tokens to the database if a user was provided."""
        if self._user is None:
            return
        try:
            token = self._user.microsoft_token
            token.access_token = self._access_token
            token.refresh_token = self._refresh_token
            token.token_expires_at = self._token_expires_at
            token.save(update_fields=[
                'access_token', 'refresh_token', 'token_expires_at',
            ])
        except Exception as exc:
            logger.error('Failed to persist refreshed token: %s', exc)

    # ------------------------------------------------------------------
    # Internal HTTP helpers
    # ------------------------------------------------------------------

    def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        url = urljoin(f'{self.base_url}/', endpoint.lstrip('/'))
        headers = {
            'Authorization': f'Bearer {self._access_token}',
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        }

        max_attempts = 2
        for attempt in range(1, max_attempts + 1):
            try:
                resp = requests.request(
                    method=method,
                    url=url,
                    headers=headers,
                    params=params,
                    json=data,
                    timeout=30,
                )
                resp.raise_for_status()
                if resp.status_code == 204:
                    return {}
                return resp.json()
            except requests.HTTPError as exc:
                status = exc.response.status_code if exc.response is not None else 0
                body = exc.response.text[:500] if exc.response is not None else ''

                # 401 = token expired or revoked → refresh and retry once
                if status == 401 and attempt < max_attempts:
                    logger.info('Graph API 401 on %s — refreshing token and retrying', endpoint)
                    if self.refresh_token_if_needed():
                        headers['Authorization'] = f'Bearer {self._access_token}'
                        continue
                    logger.error('Token refresh failed, giving up on %s', endpoint)
                    return None

                logger.error(
                    'Graph API %s %s failed [%d]: %s',
                    method, endpoint, status, body,
                )
                return None
            except requests.RequestException as exc:
                logger.error('Graph API %s %s error: %s', method, endpoint, exc)
                return None

        return None

    def _get(
        self,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        return self._request('GET', endpoint, params=params)

    def _post(
        self,
        endpoint: str,
        data: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        return self._request('POST', endpoint, data=data)

    def _patch(
        self,
        endpoint: str,
        data: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        return self._request('PATCH', endpoint, data=data)

    # ------------------------------------------------------------------
    # Normalisation
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_emails(
        raw: List[Dict[str, Any]],
    ) -> List[EmailMessage]:
        result: List[EmailMessage] = []
        for item in raw:
            sender = item.get('from', {}) or {}
            email_addr = sender.get('emailAddress', {}) or {}
            body_container = item.get('body', {}) or {}
            attachments_raw = item.get('attachments', []) or []

            attachments = [
                AttachmentData(
                    id=a.get('id', ''),
                    name=a.get('name', 'unnamed'),
                    size=a.get('size', 0),
                    content_type=a.get('contentType', ''),
                )
                for a in attachments_raw
            ]

            result.append(EmailMessage(
                id=item.get('id', ''),
                subject=item.get('subject', ''),
                sender_name=email_addr.get('name', ''),
                sender_email=email_addr.get('address', ''),
                received_at=item.get('receivedDateTime', ''),
                body=body_container.get('content', ''),
                has_attachments=item.get('hasAttachments', False),
                attachments=attachments,
            ))
        return result
