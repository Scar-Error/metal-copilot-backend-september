from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any, Dict, Optional

from django.db.models import Count, Sum
from django.utils import timezone

from rfq.models import AiUsageRecord

# Price per 1M tokens: {provider: {model: (input_price, output_price)}} in USD.
# Tokens are read from the actual API response (usage); costs are derived here.
# Update the table when provider pricing changes; unknown models fall back to
# the DEFAULT_* prices below.
MODEL_PRICING: Dict[str, Dict[str, tuple]] = {
    'openai': {
        'gpt-5.4-nano': (Decimal('0.20'), Decimal('1.25')),
        'gpt-5.4-mini': (Decimal('0.75'), Decimal('4.50')),
        'gpt-5.4': (Decimal('2.50'), Decimal('15.00')),
        'gpt-5-nano': (Decimal('0.25'), Decimal('2.00')),
        'gpt-5-mini': (Decimal('0.25'), Decimal('2.00')),
        'gpt-4.1-nano': (Decimal('0.10'), Decimal('0.40')),
        'gpt-4.1-mini': (Decimal('0.40'), Decimal('1.60')),
        'gpt-4.1': (Decimal('2.00'), Decimal('8.00')),
        'gpt-4o': (Decimal('2.50'), Decimal('10.00')),
        'gpt-4o-mini': (Decimal('0.15'), Decimal('0.60')),
    },
    'anthropic': {
        'claude-haiku-4-5': (Decimal('1.00'), Decimal('5.00')),
        'claude-sonnet-4-6': (Decimal('3.00'), Decimal('15.00')),
        'claude-opus-4-6': (Decimal('15.00'), Decimal('75.00')),
    },
}

DEFAULT_INPUT_PRICE = Decimal('1.00')
DEFAULT_OUTPUT_PRICE = Decimal('4.00')

MILLION = Decimal('1_000_000')


def _prices_for(provider: str, model: str) -> tuple:
    provider_prices = MODEL_PRICING.get(provider, {})
    return provider_prices.get(model, (DEFAULT_INPUT_PRICE, DEFAULT_OUTPUT_PRICE))


def record_usage(
    provider: str,
    model: str,
    use: str = 'general',
    input_tokens: int = 0,
    output_tokens: int = 0,
    image_count: int = 0,
    order_id: Optional[int] = None,
) -> Optional[AiUsageRecord]:
    """Persist one AI API call with the computed cost. No-op if no tokens."""
    input_tokens = input_tokens or 0
    output_tokens = output_tokens or 0
    if input_tokens <= 0 and output_tokens <= 0:
        return None

    input_price, output_price = _prices_for(provider, model)
    input_cost = Decimal(input_tokens) * input_price / MILLION
    output_cost = Decimal(output_tokens) * output_price / MILLION
    total_cost = input_cost + output_cost

    return AiUsageRecord.objects.create(
        provider=provider,
        model=model,
        use=use,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        image_count=image_count,
        input_cost=input_cost,
        output_cost=output_cost,
        total_cost=total_cost,
        order_id=order_id,
    )


def ai_usage_stats(days: int = 30) -> Dict[str, Any]:
    """Aggregated AI cost analytics for the dashboard."""
    since = timezone.now() - timedelta(days=days)

    qs = AiUsageRecord.objects.filter(created_at__gte=since)
    totals = qs.aggregate(
        requests=Count('id'),
        input_tokens=Sum('input_tokens'),
        output_tokens=Sum('output_tokens'),
        total_cost=Sum('total_cost'),
    )

    cost_by_model = list(
        qs.values('provider', 'model')
        .annotate(
            requests=Count('id'),
            input_tokens=Sum('input_tokens'),
            output_tokens=Sum('output_tokens'),
            cost=Sum('total_cost'),
        )
        .order_by('-cost')
    )

    cost_by_use = list(
        qs.values('use')
        .annotate(
            requests=Count('id'),
            input_tokens=Sum('input_tokens'),
            output_tokens=Sum('output_tokens'),
            cost=Sum('total_cost'),
        )
        .order_by('-cost')
    )

    # Per-day totals (including empty days as zero).
    day_map: Dict[str, Dict[str, Any]] = {}
    for i in range(days, -1, -1):
        d = (timezone.now() - timedelta(days=i)).date()
        day_map[d.isoformat()] = {
            'date': d.isoformat(),
            'cost': '0',
            'requests': 0,
            'input_tokens': 0,
            'output_tokens': 0,
        }

    rows = (
        qs.extra(select={'day': 'date(created_at)'})
        .values('day')
        .annotate(
            requests=Count('id'),
            input_tokens=Sum('input_tokens'),
            output_tokens=Sum('output_tokens'),
            cost=Sum('total_cost'),
        )
        .order_by('day')
    )
    for row in rows:
        key = row['day'].isoformat() if hasattr(row['day'], 'isoformat') else str(row['day'])
        if key in day_map:
            day_map[key].update({
                'cost': str(row['cost']),
                'requests': row['requests'],
                'input_tokens': row['input_tokens'],
                'output_tokens': row['output_tokens'],
            })

    recent = list(
        AiUsageRecord.objects.order_by('-created_at')[:50].values(
            'provider', 'model', 'use', 'input_tokens', 'output_tokens',
            'image_count', 'total_cost', 'created_at', 'order_id',
        )
    )
    for r in recent:
        r['total_cost'] = str(r['total_cost'])
        r['created_at'] = r['created_at'].isoformat()

    return {
        'days': days,
        'totals': {
            'requests': totals['requests'] or 0,
            'input_tokens': totals['input_tokens'] or 0,
            'output_tokens': totals['output_tokens'] or 0,
            'total_cost': str(totals['total_cost'] or Decimal('0')),
        },
        'cost_by_model': cost_by_model,
        'cost_by_use': cost_by_use,
        'cost_by_day': list(day_map.values()),
        'recent': recent,
    }
