from __future__ import annotations

from datetime import timedelta
from typing import Any, Dict

from django.db.models import Avg, Count, Q
from django.utils import timezone

from rfq.models import Order, OrderAnalytics


def compute_analytics() -> OrderAnalytics:
    """Compute and persist 30-day analytics. Returns the analytics record."""
    today = timezone.now().date()
    last_30_days = today - timedelta(days=30)

    analytics, _ = OrderAnalytics.objects.get_or_create(date=today)

    qs = Order.objects.filter(email_received_at__gte=last_30_days)
    analytics.total_orders_received = qs.count()
    analytics.total_orders_processed = qs.filter(ai_processed=True).count()
    analytics.total_orders_completed = qs.filter(status='completed').count()
    analytics.total_orders_rejected = qs.filter(status='rejected').count()
    analytics.unique_companies = (
        qs.values('company_name').distinct().count()
    )

    completed = qs.filter(status='completed', reviewed_at__isnull=False)
    if completed.exists():
        total_hours = sum(
            (r.reviewed_at - r.email_received_at).total_seconds() / 3600
            for r in completed
        )
        analytics.avg_processing_time_hours = total_hours / completed.count()

    processed = qs.filter(ai_processed=True, ai_confidence_score__isnull=False)
    if processed.exists():
        analytics.avg_ai_confidence_score = processed.aggregate(
            avg_score=Avg('ai_confidence_score'),
        )['avg_score']

    analytics.save()
    return analytics


def dashboard_stats() -> Dict[str, Any]:
    """Return aggregated dashboard statistics."""
    return {
        'total_rfqs': Order.objects.count(),
        'pending_rfqs': Order.objects.filter(status='pending').count(),
        'processing_rfqs': Order.objects.filter(status='processing').count(),
        'completed_rfqs': Order.objects.filter(status='completed').count(),
        'rejected_rfqs': Order.objects.filter(status='rejected').count(),
        'recent_rfqs': Order.objects.filter(
            email_received_at__gte=timezone.now() - timedelta(days=7),
        ).count(),
        'status_breakdown': list(
            Order.objects.values('status')
            .annotate(count=Count('id'))
            .order_by('-count')
        ),
        'priority_breakdown': list(
            Order.objects.values('priority')
            .annotate(count=Count('id'))
            .order_by('-count')
        ),
        'stage_breakdown': list(
            Order.objects.values('stage')
            .annotate(count=Count('id'))
            .order_by('-count')
        ),
    }
