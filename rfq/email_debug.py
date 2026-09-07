"""Debug/mailbox captures of every email the ingestion pipeline touches.

Temporary development aid: each email pulled from Outlook and classified is
snapshotted into ``ProcessedEmail`` so it can be browsed as a mailbox in the
frontend (with its thread + classification tag) regardless of whether an
``Order`` was created from it.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Optional

from django.utils import timezone

from rfq.models import ProcessedEmail

logger = logging.getLogger(__name__)

_TAG_RE = re.compile(r'<[^>]+>')


def _guess_plain_text(body: str) -> str:
    """Collapse HTML email bodies into a short, readable text preview."""
    if not body:
        return ''
    # Replace common block tags with separators first.
    text = re.sub(r'<br\s*/?>', '\n', body, flags=re.IGNORECASE)
    text = re.sub(r'</p>|</div>|</tr>', '\n', text, flags=re.IGNORECASE)
    text = _TAG_RE.sub('', text)
    text = text.replace('&nbsp;', ' ')
    text = text.replace('&amp;', '&')
    text = text.replace('&lt;', '<')
    text = text.replace('&gt;', '>')
    lines = [line.strip() for line in text.split('\n') if line.strip()]
    return '\n'.join(lines)


def record_processed_email(
    email,
    classification: str,
    order=None,
    user=None,
) -> Optional[ProcessedEmail]:
    """Upsert a snapshot of a processed email for the debug mailbox."""
    message_id = (email.get('id') or '').strip()
    if not message_id:
        return None

    received_at = email.get('received_at')
    if received_at:
        if isinstance(received_at, str):
            try:
                parsed = datetime.fromisoformat(received_at.replace('Z', '+00:00'))
                if parsed.tzinfo is None:
                    parsed = timezone.make_aware(parsed)
                received_at = parsed
            except (ValueError, TypeError):
                received_at = None
        elif received_at.tzinfo is None:
            received_at = timezone.make_aware(received_at)

    body = email.get('body') or ''

    defaults = {
        'conversation_id': (email.get('conversation_id') or '').strip(),
        'subject': (email.get('subject') or '')[:500],
        'sender_name': (email.get('sender_name') or '')[:255],
        'sender_email': email.get('sender_email') or '',
        'received_at': received_at,
        'body': body,
        'body_preview': _guess_plain_text(body)[:500],
        'classification': classification,
        'order': order,
        'user': user,
    }

    try:
        obj, _created = ProcessedEmail.objects.update_or_create(
            email_message_id=message_id,
            defaults=defaults,
        )
        return obj
    except Exception as exc:
        logger.error('Failed to record processed email %s: %s', message_id, exc)
        return None