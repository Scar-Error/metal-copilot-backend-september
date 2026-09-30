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


@pytest.mark.django_db
class TestAnthropicRequestCompatibility:
    """Anthropic 1.8 dropped `temperature` from messages.create().

    Passing it anyway raises TypeError before the request is sent, so every
    Anthropic call died, no usage was ever recorded, and the dashboard graphs
    stayed frozen while the pipeline quietly tagged everything `other`. The
    provider has to send only what the installed SDK accepts, and still record
    the usage of a call that goes through.
    """

    @staticmethod
    def _client(accepts_temperature: bool):
        """A client whose create() mimics the two SDK generations."""
        from types import SimpleNamespace
        from unittest.mock import MagicMock

        sent: list[dict] = []
        response = MagicMock()
        block = MagicMock()
        block.text = 'OK'
        response.content = [block]
        response.usage.input_tokens = 100
        response.usage.output_tokens = 20

        if accepts_temperature:
            def create(model, max_tokens, messages, temperature=0):
                sent.append({
                    'model': model, 'max_tokens': max_tokens,
                    'messages': messages, 'temperature': temperature,
                })
                return response
        else:
            def create(model, max_tokens, messages, extra_body=None):
                sent.append({
                    'model': model, 'max_tokens': max_tokens,
                    'messages': messages, 'extra_body': extra_body,
                })
                return response

        return SimpleNamespace(messages=SimpleNamespace(create=create)), sent

    @staticmethod
    def _provider(client):
        from rfq.ai_providers import AnthropicProvider

        provider = AnthropicProvider.__new__(AnthropicProvider)
        provider.name = 'anthropic'
        provider.model = 'claude-haiku-4-5'
        provider._client = client
        return provider

    def test_modern_sdk_gets_no_temperature(self) -> None:
        client, sent = self._client(accepts_temperature=False)
        provider = self._provider(client)

        assert provider.complete('hello', use='classification') == 'OK'
        # 0 is the API default, so it is not sent at all.
        assert 'temperature' not in sent[0]
        assert sent[0]['extra_body'] is None

    def test_modern_sdk_gets_a_custom_temperature_via_extra_body(self) -> None:
        client, sent = self._client(accepts_temperature=False)
        provider = self._provider(client)

        provider.complete('hello', temperature=0.3, use='extraction')

        assert sent[0]['extra_body'] == {'temperature': 0.3}

    def test_older_sdk_still_gets_a_named_temperature(self) -> None:
        client, sent = self._client(accepts_temperature=True)
        provider = self._provider(client)

        provider.complete('hello', temperature=0.3, use='extraction')

        assert sent[0]['temperature'] == 0.3

    def test_usage_is_recorded_against_a_modern_sdk(self) -> None:
        client, _ = self._client(accepts_temperature=False)
        provider = self._provider(client)

        provider.complete('hello', use='classification')

        record = AiUsageRecord.objects.get(use='classification')
        assert record.provider == 'anthropic'
        assert record.input_tokens == 100
        assert record.output_tokens == 20
        assert record.total_cost > 0


class TestPlaceholderKeysAreNotConfigured:
    """A key copied from .env.example is `***`, which is truthy.

    Sending it produced a 401 per AI call, so nothing was recorded and nothing
    said why. It has to read as "not configured" instead.
    """

    @pytest.mark.parametrize('value', ['', '***', ' *** '])
    def test_anthropic_refuses_a_placeholder_key(self, value: str) -> None:
        from django.test import override_settings

        from rfq.ai_providers import AIProviderUnavailable, AnthropicProvider

        with override_settings(ANTHROPIC_API_KEY=value), pytest.raises(
            AIProviderUnavailable, match='ANTHROPIC_API_KEY is not configured',
        ):
            AnthropicProvider()

    @pytest.mark.parametrize('value', ['', '***', ' *** '])
    def test_openai_refuses_a_placeholder_key(self, value: str) -> None:
        from django.test import override_settings

        from rfq.ai_providers import AIProviderUnavailable, OpenAIProvider

        with override_settings(OPENAI_API_KEY=value), pytest.raises(
            AIProviderUnavailable, match='OPENAI_API_KEY is not configured',
        ):
            OpenAIProvider()

    def test_a_real_key_is_not_mistaken_for_a_placeholder(self) -> None:
        from django.test import override_settings

        from rfq.ai_providers import AnthropicProvider

        # Building the client makes no network call, so this is safe to assert:
        # a real-looking key has to get past the placeholder check.
        with override_settings(ANTHROPIC_API_KEY='sk-ant-real-looking-key'):
            provider = AnthropicProvider()

        assert provider.name == 'anthropic'
