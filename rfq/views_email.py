import logging

from celery import current_app
from celery.result import AsyncResult
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from microsoft_auth.graph_api import GraphEmailProvider

logger = logging.getLogger(__name__)


def _build_provider(user) -> GraphEmailProvider:
    token = user.microsoft_token
    token.refresh_if_expired()
    return GraphEmailProvider(
        access_token=token.access_token,
        refresh_token=token.refresh_token,
        token_expires_at=token.token_expires_at,
        user=user,
    )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def trigger_email_monitoring(request):
    from rfq.tasks import monitor_emails_for_rfqs
    task = monitor_emails_for_rfqs.delay()
    return Response({
        'success': True,
        'task_id': task.id,
        'message': 'Email monitoring task started',
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def trigger_ai_processing(request, order_id):
    from rfq.tasks import process_rfq_with_ai
    task = process_rfq_with_ai.delay(order_id)
    return Response({
        'success': True,
        'task_id': task.id,
        'message': f'AI processing started for order {order_id}',
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def trigger_business_central_sync(request, order_id):
    from rfq.tasks import sync_with_business_central
    task = sync_with_business_central.delay(order_id)
    return Response({
        'success': True,
        'task_id': task.id,
        'message': f'Business Central sync started for order {order_id}',
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_task_status(request, task_id):
    task = AsyncResult(task_id, app=current_app)
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


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_microsoft_emails(request):
    try:
        provider = _build_provider(request.user)
    except Exception:
        return Response(
            {'success': False, 'error': 'No valid Microsoft token'},
            status=status.HTTP_401_UNAUTHORIZED,
        )

    emails = provider.fetch_emails(limit=20)
    return Response({'success': True, 'emails': emails})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_rfq_emails(request):
    try:
        provider = _build_provider(request.user)
    except Exception:
        return Response(
            {'success': False, 'error': 'No valid Microsoft token'},
            status=status.HTTP_401_UNAUTHORIZED,
        )

    from rfq.orchestrator import RfqDetector
    emails = provider.fetch_emails(days_back=7)
    detector = RfqDetector()
    rfq_emails = [e for e in emails if detector.is_rfq(e)]

    return Response({
        'success': True,
        'rfq_emails': rfq_emails,
        'count': len(rfq_emails),
    })
