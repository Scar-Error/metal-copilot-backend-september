import logging

from celery import shared_task

logger = logging.getLogger('rfq.tasks')


@shared_task(bind=True)
def pull_emails_task(self, user_id, start_iso, end_iso):
    """
    Pull Outlook emails into email threads for a given user in the background.

    Dispatched by `pull_emails` so the HTTP request returns immediately.
    """
    from django.contrib.auth import get_user_model

    from rfq.email_pull_service import pull_emails_for_user

    user = get_user_model().objects.get(pk=user_id)
    return pull_emails_for_user(user, start_iso, end_iso)