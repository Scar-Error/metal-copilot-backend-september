import logging

from django.utils.dateparse import parse_datetime


class EmailPullError(Exception):
    pass


logger = logging.getLogger('rfq')


def pull_emails_for_user(user, start_iso, end_iso):
    """
    Pull emails from Microsoft Graph within a date/time range.

    Groups by conversationId and creates EmailThread + EmailMessage objects.
    Only unique conversation IDs are processed. Returns a summary dict suitable
    for a Celery task result / API response.
    """
    from datetime import timezone as dt_timezone

    from django.utils import timezone

    from microsoft_auth.graph_api import GraphEmailProvider
    from rfq.models import EmailThread, EmailMessage

    start_time = parse_datetime(start_iso)
    end_time = parse_datetime(end_iso)

    if not start_time or not end_time:
        raise EmailPullError('Invalid date format. Use ISO 8601 (e.g. 2026-08-01T00:00:00Z)')

    # Ensure timezone-aware
    if timezone.is_naive(start_time):
        start_time = timezone.make_aware(start_time, dt_timezone.utc)
    if timezone.is_naive(end_time):
        end_time = timezone.make_aware(end_time, dt_timezone.utc)

    # Convert to UTC for Graph API
    start_utc = start_time.astimezone(dt_timezone.utc)
    end_utc = end_time.astimezone(dt_timezone.utc)

    # Format for Graph API — use 'Z' suffix for UTC
    start_iso = start_utc.strftime('%Y-%m-%dT%H:%M:%SZ')
    end_iso = end_utc.strftime('%Y-%m-%dT%H:%M:%SZ')

    try:
        token = user.microsoft_token
        token.refresh_if_expired()
        provider = GraphEmailProvider(
            access_token=token.access_token,
            refresh_token=token.refresh_token,
        )
    except Exception:
        raise EmailPullError('No valid Microsoft token')

    # Fetch emails — NO $orderby (Graph API InefficientFilter on inbox/messages)
    all_emails = []
    params = {
        '$top': 100,
        '$select': 'id,subject,from,receivedDateTime,body,conversationId,hasAttachments,bodyPreview',
        '$filter': f"receivedDateTime ge {start_iso} and receivedDateTime le {end_iso}",
    }

    emails_data = provider._get('me/mailFolders/inbox/messages', params=params)
    if emails_data:
        all_emails.extend(emails_data.get('value', []))

        # Follow @odata.nextLink for pagination
        while emails_data.get('@odata.nextLink'):
            emails_data = provider._get_url(emails_data['@odata.nextLink'])
            if emails_data:
                all_emails.extend(emails_data.get('value', []))

    # Normalize the raw Graph API response and sort by date (no $orderby on Graph)
    normalized = GraphEmailProvider._normalize_emails(all_emails, provider.base_url)
    normalized.sort(key=lambda e: e.get('received_at', ''), reverse=True)

    logger.info('Pull emails: fetched %d emails in date range', len(normalized))

    # Extract unique conversation IDs from the date range
    conversation_ids = set()
    for email in normalized:
        conv_id = email.get('conversation_id', '')
        if conv_id:
            conversation_ids.add(conv_id)

    logger.info('Pull emails: found %d unique conversation IDs', len(conversation_ids))
    logger.debug('Pull emails: conversation IDs: %s', list(conversation_ids)[:5])

    # Also include any emails that had no conversation_id (standalone)
    for email in normalized:
        conv_id = email.get('conversation_id', '')
        if not conv_id:
            msg_id = email.get('id', '')
            if msg_id:
                conversation_ids.add(msg_id)

    logger.info('Pull emails: processing %d conversations', len(conversation_ids))

    threads_created = 0
    threads_updated = 0
    messages_created = 0
    threads_data = []

    for conv_id in conversation_ids:
        logger.debug('Pull emails: processing conversation %s', conv_id)
        # Check if thread already exists in DB
        existing_thread = EmailThread.objects.filter(conversation_id=conv_id).first()
        thread_exists = existing_thread is not None

        if thread_exists:
            thread = existing_thread
            logger.info('Pull emails: found existing thread %s for conversation %s (thread_db_id=%s)', existing_thread.conversation_id[-16:], conv_id[-16:], existing_thread.id)
            # Thread exists — get all messages from Outlook, sync only new ones
            full_messages = provider.fetch_messages_by_conversation(conv_id)
            if not full_messages:
                # Fallback: use date-range emails
                full_messages = [e for e in normalized if e.get('conversation_id') == conv_id]

            thread = existing_thread
            existing_msg_ids = set(
                EmailMessage.objects.filter(thread=thread).values_list('message_id', flat=True)
            )

            for email in full_messages:
                msg_id = email.get('id', '')
                if not msg_id or msg_id in existing_msg_ids:
                    continue

                EmailMessage.objects.create(
                    thread=thread,
                    message_id=msg_id,
                    subject=email.get('subject', ''),
                    sender_name=email.get('sender_name', ''),
                    sender_email=email.get('sender_email', ''),
                    received_at=email.get('received_at', ''),
                    body=email.get('body', ''),
                    body_preview=email.get('body_preview', ''),
                    has_attachments=email.get('has_attachments', False),
                )
                messages_created += 1

            threads_updated += 1
            logger.info('Pull emails: updated thread %s (%d new messages)', conv_id[-16:], messages_created)

        else:
            # New thread — fetch all messages from Outlook and create everything
            full_messages = provider.fetch_messages_by_conversation(conv_id)
            if not full_messages:
                # Fallback: use date-range emails
                full_messages = [e for e in normalized if e.get('conversation_id') == conv_id]

            if not full_messages:
                continue

            thread = EmailThread.objects.create(
                conversation_id=conv_id,
                subject=full_messages[0].get('subject', ''),
                user=user,
            )
            threads_created += 1
            logger.info('Pull emails: created new thread %s (thread_db_id=%s)', conv_id[-16:], thread.id)

            for email in full_messages:
                msg_id = email.get('id', '')
                if not msg_id:
                    continue

                EmailMessage.objects.create(
                    thread=thread,
                    message_id=msg_id,
                    subject=email.get('subject', ''),
                    sender_name=email.get('sender_name', ''),
                    sender_email=email.get('sender_email', ''),
                    received_at=email.get('received_at', ''),
                    body=email.get('body', ''),
                    body_preview=email.get('body_preview', ''),
                    has_attachments=email.get('has_attachments', False),
                )
                messages_created += 1

            logger.info('Pull emails: created thread %s with %d messages', conv_id[-16:], len(full_messages))

        # Update thread metadata from DB
        thread.message_count = thread.messages.count()
        latest = thread.messages.order_by('-received_at').first()
        if latest:
            thread.last_message_at = latest.received_at
        thread.save(update_fields=['message_count', 'last_message_at', 'updated_at'])

        threads_data.append({
            'id': thread.id,
            'conversation_id': thread.conversation_id,
            'subject': thread.subject,
            'message_count': thread.message_count,
            'last_message_at': (
                thread.last_message_at.isoformat() if thread.last_message_at else None
            ),
        })

    logger.info('Pull emails: done — created=%d updated=%d messages_added=%d', threads_created, threads_updated, messages_created)

    return {
        'success': True,
        'threads_created': threads_created,
        'threads_updated': threads_updated,
        'messages_created': messages_created,
        'total_fetched': len(normalized),
        'threads': threads_data,
    }