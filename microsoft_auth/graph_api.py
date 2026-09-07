from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

import requests
from django.conf import settings
from django.utils import timezone

from rfq.interfaces import AttachmentData, EmailMessage

logger = logging.getLogger(__name__)

# Invisible marker (MAPI named property) used to identify already-processed
# emails without touching user-visible Outlook categories.
PROCESSED_PROPERTY_ID = 'String {00020329-0000-0000-C000-000000000046} Name RFQProcessed'


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
        # TEMPORARY: only process emails received after 31 July. Remove when live.
        since = datetime(2026, 8, 1).isoformat() + 'Z'
        params = {
            '$top': limit,
            '$orderby': 'receivedDateTime desc',
            '$select': 'id,subject,from,receivedDateTime,body,conversationId,hasAttachments',
            '$expand': 'attachments($select=id,name,size,contentType)',
            '$filter': (
                f'receivedDateTime ge {since} and not '
                f"(singleValueExtendedProperties/any(ep:ep/id eq '{PROCESSED_PROPERTY_ID}' "
                f"and ep/value eq 'true'))"
            ),
        }

        # Prefer Graph's well-known folder name (e.g. 'inbox'), which resolves
        # to the Inbox folder regardless of its localized display name.
        well_known = folder.strip().lower()
        emails = self._get(
            f'me/mailFolders/{well_known}/messages',
            params=params,
        )

        # Fallback: resolve a custom folder by its display name.
        if emails is None:
            folder_id = self._resolve_folder_id_by_name(folder)
            if folder_id:
                emails = self._get(
                    f'me/mailFolders/{folder_id}/messages',
                    params=params,
                )

        if emails is None:
            logger.error('Folder %s not found', folder)
            return []
        return self._normalize_emails(emails.get('value', []) if emails else [], self.base_url)

    def fetch_messages_by_conversation(
        self,
        conversation_id: str,
        limit: int = 100,
    ) -> List[EmailMessage]:
        """Fetch ALL messages in a conversation by conversationId from Inbox and Sent Items."""
        params = {
            '$top': limit,
            '$select': 'id,subject,from,receivedDateTime,body,conversationId,hasAttachments,bodyPreview',
            '$expand': 'attachments($select=id,name,size,contentType)',
            '$filter': f"conversationId eq '{conversation_id}'",
        }

        all_messages = []
        for folder in ('inbox', 'sentitems'):
            data = self._get(f'me/mailFolders/{folder}/messages', params=params)
            if data and 'value' in data:
                all_messages.extend(data.get('value', []))
                while data.get('@odata.nextLink'):
                    data = self._get_url(data['@odata.nextLink'])
                    if data and 'value' in data:
                        all_messages.extend(data.get('value', []))

        seen_ids = set()
        unique_messages = []
        for msg in all_messages:
            msg_id = msg.get('id', '')
            if msg_id and msg_id not in seen_ids:
                seen_ids.add(msg_id)
                unique_messages.append(msg)

        normalized = self._normalize_emails(unique_messages, self.base_url)
        normalized.sort(key=lambda e: e.get('received_at', ''))
        return normalized

    def fetch_emails_by_date_range(
        self,
        start_time: str,
        end_time: str,
        limit: int = 100,
    ) -> List[EmailMessage]:
        """Fetch all emails within a specific date/time range from Inbox and Sent Items."""
        params = {
            '$top': limit,
            '$select': 'id,subject,from,receivedDateTime,body,conversationId,hasAttachments,bodyPreview',
            '$expand': 'attachments($select=id,name,size,contentType)',
            '$filter': (
                f"receivedDateTime ge {start_time} and receivedDateTime le {end_time}"
            ),
        }

        all_emails = []
        for folder in ('inbox', 'sentitems'):
            data = self._get(f'me/mailFolders/{folder}/messages', params=params)
            if data and 'value' in data:
                all_emails.extend(data.get('value', []))
                while data.get('@odata.nextLink'):
                    data = self._get_url(data['@odata.nextLink'])
                    if data and 'value' in data:
                        all_emails.extend(data.get('value', []))

        if not all_emails:
            logger.error('Failed to fetch emails by date range')
            return []

        seen_ids = set()
        unique_emails = []
        for email in all_emails:
            eid = email.get('id', '')
            if eid and eid not in seen_ids:
                seen_ids.add(eid)
                unique_emails.append(email)

        return self._normalize_emails(unique_emails, self.base_url)

    def _resolve_folder_id_by_name(self, folder: str) -> Optional[str]:
        """Resolve a mail folder ID from its display name."""
        result = self._get(
            'me/mailFolders',
            params={'$top': 200, '$select': 'id,displayName'},
        )
        if not result:
            return None
        for f in result.get('value', []):
            if f.get('displayName') == folder:
                return f.get('id')
        return None

    def get_email_by_id(self, email_id: str) -> Optional[EmailMessage]:
        result = self._get(
            f'me/messages/{email_id}',
            params={
                '$select': (
                    'id,subject,from,toRecipients,ccRecipients,'
                    'receivedDateTime,body,bodyPreview,hasAttachments,'
                    'internetMessageHeaders'
                ),
                '$expand': 'attachments($select=id,name,size,contentType)',
            },
        )
        if not result:
            return None
        emails = self._normalize_emails([result], self.base_url)
        return emails[0] if emails else None

    def get_attachments(self, email_id: str) -> List[AttachmentData]:
        result = self._get(f'me/messages/{email_id}/attachments')
        if not result:
            return []
        return [
            AttachmentData(
                id=a.get('id', ''),
                name=a.get('name', 'unnamed'),
                size=a.get('size', 0),
                content_type=a.get('contentType', ''),
            )
            for a in result.get('value', [])
        ]

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
            logger.info('Downloaded attachment %s for email %s (%d bytes)', attachment_id, email_id, len(resp.content))
            return resp.content
        except requests.RequestException as exc:
            logger.error('Attachment download failed for %s/%s: %s (status=%s)', email_id, attachment_id, exc, getattr(exc.response, 'status_code', 'N/A'))
            return None

    def get_attachments_with_content(self, email_id: str) -> List[Dict[str, Any]]:
        """Fetch all attachments for a message, downloading content for images and documents."""
        import mimetypes

        logger.info('Fetching attachments for email %s', email_id)
        result = self._get(f'me/messages/{email_id}/attachments')
        if not result:
            logger.warning('Graph API returned no result for attachments on email %s', email_id)
            return []

        raw_atts = result.get('value', [])
        logger.info('Graph API returned %d raw attachment(s) for email %s', len(raw_atts), email_id)

        IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp', '.tiff'}
        DOCUMENT_EXTENSIONS = {'.pdf', '.doc', '.docx', '.xls', '.xlsx', '.txt', '.csv'}

        attachments = []
        for att in raw_atts:
            att_id = att.get('id', '')
            att_name = att.get('name', 'unnamed')
            content_type = (att.get('contentType') or '').lower()
            _, ext = os.path.splitext(att_name)
            ext = ext.lower()

            content = None
            if att_id:
                content = self.download_attachment(email_id, att_id)
            else:
                logger.warning('Attachment %s has no ID, skipping download', att_name)

            if not content:
                logger.warning('Attachment %s: no content downloaded (id=%s)', att_name, att_id)
                continue

            is_image = ext in IMAGE_EXTENSIONS or content_type.startswith('image/')
            is_doc = ext in DOCUMENT_EXTENSIONS or content_type.startswith(('application/pdf', 'text/'))

            ext_mime = mimetypes.guess_type(att_name)[0]
            if content_type in ('application/octet-stream', '', None) and ext_mime:
                media_type = ext_mime
            else:
                media_type = content_type or ext_mime or 'application/octet-stream'

            attachments.append({
                'id': att_id,
                'name': att_name,
                'size': att.get('size', 0),
                'content_type': content_type,
                'content': content,
                'media_type': media_type,
                'is_image': is_image,
                'is_document': is_doc,
            })

        logger.info('Processed %d attachments for email %s (%d with content)', len(attachments), email_id, len(attachments))
        return attachments

    def mark_as_processed(self, email_id: str) -> bool:
        result = self._patch(
            f'me/messages/{email_id}',
            data={'singleValueExtendedProperties': [
                {'id': PROCESSED_PROPERTY_ID, 'value': 'true'},
            ]},
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
                # Handle empty response body
                if not resp.text or resp.text.strip() == '':
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

    def _get_url(
        self,
        url: str,
    ) -> Optional[Dict[str, Any]]:
        """GET a full URL (e.g. @odata.nextLink) without appending to base."""
        headers = {
            'Authorization': f'Bearer {self._access_token}',
            'Accept': 'application/json',
        }
        try:
            resp = requests.get(url, headers=headers, timeout=30)
            resp.raise_for_status()
            if not resp.text or resp.text.strip() == '':
                return {}
            return resp.json()
        except requests.RequestException as exc:
            logger.error('Graph API GET %s error: %s', url[:200], exc)
            return None

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
        base_url: str = '',
    ) -> List[EmailMessage]:
        result: List[EmailMessage] = []
        for item in raw:
            sender = item.get('from', {}) or {}
            email_addr = sender.get('emailAddress', {}) or {}
            body_container = item.get('body', {}) or {}
            email_id = item.get('id', '')
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
                id=email_id,
                subject=item.get('subject', ''),
                sender_name=email_addr.get('name', ''),
                sender_email=email_addr.get('address', ''),
                received_at=item.get('receivedDateTime', ''),
                body=body_container.get('content', ''),
                body_preview=item.get('bodyPreview', ''),
                conversation_id=item.get('conversationId', ''),
                has_attachments=item.get('hasAttachments', False),
                attachments=attachments,
            ))
        return result
