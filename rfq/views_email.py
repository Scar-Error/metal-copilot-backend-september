import logging

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

logger = logging.getLogger(__name__)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def pull_emails(request):
    """
    Start a background email pull from Microsoft Graph within a date/time range.

    Dispatches a Celery task and returns immediately with a task_id; poll
    `GET /api/rfq/monitor/task/<task_id>/` for the result.
    """
    from datetime import timezone as dt_timezone

    from django.utils import timezone
    from django.utils.dateparse import parse_datetime

    from rfq.tasks import pull_emails_task

    start_str = request.data.get('start_time')
    end_str = request.data.get('end_time')

    if not start_str or not end_str:
        return Response(
            {'success': False, 'error': 'start_time and end_time are required'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    start_time = parse_datetime(start_str)
    end_time = parse_datetime(end_str)

    if not start_time or not end_time:
        return Response(
            {'success': False, 'error': 'Invalid date format. Use ISO 8601 (e.g. 2026-08-01T00:00:00Z)'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Ensure timezone-aware — frontend sends UTC via toISOString()
    if timezone.is_naive(start_time):
        start_time = timezone.make_aware(start_time, dt_timezone.utc)
    if timezone.is_naive(end_time):
        end_time = timezone.make_aware(end_time, dt_timezone.utc)

    # Fast-fail if the user has no Microsoft token — the task would just fail.
    try:
        request.user.microsoft_token
    except Exception:
        return Response(
            {'success': False, 'error': 'No valid Microsoft token'},
            status=status.HTTP_401_UNAUTHORIZED,
        )

    start_iso = start_time.astimezone(dt_timezone.utc).isoformat()
    end_iso = end_time.astimezone(dt_timezone.utc).isoformat()

    task = pull_emails_task.delay(request.user.id, start_iso, end_iso)

    return Response({
        'success': True,
        'task_id': task.id,
        'status': 'PENDING',
        'message': 'Email pull started in the background',
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_task_status(request, task_id):
    from celery.result import AsyncResult

    from config.celery import app as celery_app

    task = AsyncResult(task_id, app=celery_app)
    data = {
        'task_id': task_id,
        'status': task.status,
        'result': task.result if task.ready() else None,
    }
    if task.failed():
        data['error'] = str(task.result)
    return Response(data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def sync_products_from_bc(request):
    from rfq.business_central import sync_products_from_bc as _sync
    count = _sync(request.user)
    return Response({
        'success': True,
        'synced_count': count,
        'message': f'Synced {count} products from Business Central',
    })