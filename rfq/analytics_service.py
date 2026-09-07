from __future__ import annotations

from datetime import timedelta
from typing import Any, Dict

from django.db.models import Avg, Count, Q
from django.utils import timezone

from rfq.models import Order, OrderAnalytics, OrderAiMetadata


def compute_analytics() -> OrderAnalytics:
    """Compute and persist 30-day analytics. Returns the analytics record."""
    today = timezone.now().date()
    last_30_days = today - timedelta(days=30)

    analytics, _ = OrderAnalytics.objects.get_or_create(date=today)

    qs = Order.objects.filter(created_at__gte=last_30_days)
    analytics.total_orders_received = qs.count()
    analytics.total_orders_processed = OrderAiMetadata.objects.filter(
        order__in=qs, processed=True
    ).count()
    analytics.total_orders_completed = qs.filter(reviewed_at__isnull=False).count()
    analytics.unique_companies = (
        qs.values('company_name').distinct().count()
    )

    reviewed = qs.filter(reviewed_at__isnull=False)
    if reviewed.exists():
        total_hours = sum(
            (r.reviewed_at - r.created_at).total_seconds() / 3600
            for r in reviewed
        )
        analytics.avg_processing_time_hours = total_hours / reviewed.count()

    processed = OrderAiMetadata.objects.filter(
        order__in=qs, processed=True, confidence_score__isnull=False
    )
    if processed.exists():
        analytics.avg_ai_confidence_score = processed.aggregate(
            avg_score=Avg('confidence_score'),
        )['avg_score']

    analytics.save()
    return analytics


def dashboard_stats() -> Dict[str, Any]:
    """Return aggregated dashboard statistics."""
    return {
        'total_rfqs': Order.objects.count(),
        'processed_rfqs': OrderAiMetadata.objects.filter(processed=True).count(),
        'reviewed_rfqs': Order.objects.filter(reviewed_at__isnull=False).count(),
        'recent_rfqs': Order.objects.filter(
            created_at__gte=timezone.now() - timedelta(days=7),
        ).count(),
    }
