from __future__ import annotations

from decimal import Decimal

import pytest
from django.db.models import Sum
from django.utils import timezone

from rfq.ai_usage import MODEL_PRICING, ai_usage_stats, record_usage
from rfq.models import AiUsageRecord, Order


@pytest.mark.django_db
class TestRecordUsage:
    def test_records_cost_from_pricing_table(self) -> None:
        order = Order.objects.create(
            company_name='ACME',
            rfq_number='RFQ-TEST-1',
        )
        record = record_usage(
            provider='openai',
            model='gpt-5.4-nano',
            use='extraction',
            input_tokens=1_000_000,
            output_tokens=100_000,
            image_count=2,
            order_id=order.id,
        )

        assert record is not None
        assert record.input_tokens == 1_000_000
        assert record.output_tokens == 100_000
        assert record.image_count == 2
        assert record.order_id == order.id
        assert record.input_cost == Decimal('0.20')
        assert record.output_cost == Decimal('0.125')
        assert record.total_cost == Decimal('0.325')

    def test_noop_when_no_tokens(self) -> None:
        assert record_usage('openai', 'gpt-5.4-nano', input_tokens=0, output_tokens=0) is None
        assert AiUsageRecord.objects.count() == 0

    def test_unknown_model_falls_back_to_defaults(self) -> None:
        record = record_usage(
            provider='openai',
            model='future-model-x',
            input_tokens=1_000_000,
            output_tokens=1_000_000,
        )
        assert record.total_cost == Decimal('5.00')


@pytest.mark.django_db
class TestAiUsageStats:
    def test_aggregates_by_model_use_and_day(self) -> None:
        record_usage(
            provider='openai', model='gpt-5.4-nano', use='classification',
            input_tokens=1_000_000, output_tokens=0,
        )
        record_usage(
            provider='openai', model='gpt-5.4-mini', use='image_details',
            input_tokens=0, output_tokens=1_000_000, image_count=2,
        )
        record_usage(
            provider='openai', model='gpt-5.4-nano', use='extraction',
            input_tokens=500_000, output_tokens=100_000,
        )

        stats = ai_usage_stats(days=30)

        assert stats['totals']['requests'] == 3
        assert Decimal(stats['totals']['total_cost']) == Decimal('4.925')

        by_model = {m['model']: m for m in stats['cost_by_model']}
        assert by_model['gpt-5.4-nano']['requests'] == 2
        assert by_model['gpt-5.4-mini']['requests'] == 1

        by_use = {u['use']: u for u in stats['cost_by_use']}
        assert by_use['classification']['requests'] == 1
        assert by_use['image_details']['requests'] == 1
        assert by_use['extraction']['requests'] == 1

        today = stats['cost_by_day'][-1]
        assert today['requests'] == 3
        assert Decimal(today['cost']) > 0

        assert len(stats['recent']) == 3

    def test_empty_stats_are_zero(self) -> None:
        stats = ai_usage_stats(days=7)
        assert stats['totals']['requests'] == 0
        assert Decimal(stats['totals']['total_cost']) == 0
        assert len(stats['cost_by_day']) == 8
        assert all(Decimal(d['cost']) == 0 for d in stats['cost_by_day'])


@pytest.mark.django_db
class TestProviderUsageCapture:
    def test_real_provider_records_usage(self) -> None:
        from unittest.mock import MagicMock

        from rfq.ai_providers import OpenAIProvider

        provider = OpenAIProvider.__new__(OpenAIProvider)
        provider.name = 'openai'
        provider.model = 'gpt-5.4-nano'
        provider._client = MagicMock()

        response = MagicMock()
        response.usage.prompt_tokens = 1000
        response.usage.completion_tokens = 200
        response.choices[0].message.content = 'ok'
        provider._client.chat.completions.create.return_value = response

        provider.complete('hello', use='classification')

        record = AiUsageRecord.objects.get(use='classification')
        assert record.provider == 'openai'
        assert record.model == 'gpt-5.4-nano'
        assert record.input_tokens == 1000
        assert record.output_tokens == 200
        assert record.total_cost > 0
