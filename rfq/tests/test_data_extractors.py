from __future__ import annotations

import base64
from unittest.mock import MagicMock

import pytest

from rfq.ai_providers import AnthropicProvider, OpenAIProvider
from rfq.data_extractors import OpenAiExtractor


def _make_provider(json_text: str, image_details: str = 'valve details blob') -> MagicMock:
    """Provider whose round 2 (images) returns ``image_details`` and round 3
    (no images) returns ``json_text``."""
    provider = MagicMock()
    provider.name = 'anthropic'

    def complete(prompt, images=None, max_tokens=1000, temperature=0, model=None,
                 use='general', order_id=None):
        if images:
            return image_details
        return json_text

    provider.complete.side_effect = complete
    return provider


class TestOpenAiExtractor:
    def test_extract_with_images_runs_two_rounds(self) -> None:
        provider = _make_provider('{"company_name": "X", "items": []}')
        extractor = OpenAiExtractor(provider=provider)

        png_bytes = b'fake-png-bytes'
        result = extractor.extract(
            'email body text',
            images=[{'data': png_bytes, 'media_type': 'image/png'}],
        )

        assert result is not None
        assert result.get('company_name') == 'X'

        # Two provider calls: round 2 (with images) then round 3 (no images).
        assert provider.complete.call_count == 2
        round2_kwargs = provider.complete.call_args_list[0].kwargs
        round3_kwargs = provider.complete.call_args_list[1].kwargs

        assert round2_kwargs['images'] == [{'data': png_bytes, 'media_type': 'image/png'}]
        # Vision model is resolved inside the provider, not the extractor.
        assert round2_kwargs.get('model') is None
        assert round2_kwargs['use'] == 'image_details'
        assert round3_kwargs['images'] is None
        assert round3_kwargs['use'] == 'extraction'
        round3_prompt = provider.complete.call_args_list[1].args[0]
        assert 'email body text' in round3_prompt
        assert 'valve details blob' in round3_prompt
    def test_extract_without_images_runs_single_round(self) -> None:
        provider = _make_provider('{"company_name": "X", "items": []}')
        extractor = OpenAiExtractor(provider=provider)

        result = extractor.extract('just text')

        assert result is not None
        assert provider.complete.call_count == 1
        round3_kwargs = provider.complete.call_args.kwargs
        assert round3_kwargs['images'] is None
        assert 'just text' in provider.complete.call_args.args[0]

    def test_extract_returns_none_on_bad_json(self) -> None:
        provider = _make_provider('not json at all')
        extractor = OpenAiExtractor(provider=provider)

        result = extractor.extract(
            'email body',
            images=[{'data': b'x', 'media_type': 'image/png'}],
        )
        assert result is None

    def test_round2_failure_falls_back_to_text_only(self) -> None:
        provider = MagicMock()
        provider.name = 'anthropic'

        def complete(prompt, images=None, max_tokens=1000, temperature=0, model=None,
                     use='general', order_id=None):
            if images:
                raise Exception('vision boom')
            return '{"company_name": "X", "items": []}'

        provider.complete.side_effect = complete
        extractor = OpenAiExtractor(provider=provider)

        result = extractor.extract(
            'email body',
            images=[{'data': b'x', 'media_type': 'image/png'}],
        )
        assert result is not None
        assert result.get('company_name') == 'X'
        assert provider.complete.call_count == 2


class TestAnthropicProvider:
    def _make_anthropic_client(self, text: str) -> MagicMock:
        client = MagicMock()
        response = MagicMock()
        block = MagicMock()
        block.text = text
        response.content = [block]
        client.messages.create.return_value = response
        return client

    def test_complete_with_images_builds_vision_content_blocks(self) -> None:
        client = self._make_anthropic_client('RESULT')
        provider = AnthropicProvider(client=client)

        png_bytes = b'fake-png-bytes'
        result = provider.complete('summarize', images=[{'data': png_bytes, 'media_type': 'image/png'}])

        assert result == 'RESULT'
        kwargs = client.messages.create.call_args.kwargs
        content = kwargs['messages'][0]['content']
        assert isinstance(content, list)
        assert content[0]['type'] == 'image'
        assert content[0]['source']['type'] == 'base64'
        assert content[0]['source']['media_type'] == 'image/png'
        assert content[0]['source']['data'] == base64.b64encode(png_bytes).decode('ascii')
        assert content[1]['type'] == 'text'
        assert content[1]['text'] == 'summarize'

    def test_complete_without_images_uses_plain_string(self) -> None:
        client = self._make_anthropic_client('RESULT')
        provider = AnthropicProvider(client=client)

        result = provider.complete('just text')

        assert result == 'RESULT'
        kwargs = client.messages.create.call_args.kwargs
        assert kwargs['messages'][0]['content'] == 'just text'

    def test_images_use_vision_model_text_uses_default(self) -> None:
        from django.test import override_settings

        client = self._make_anthropic_client('RESULT')
        with override_settings(
            ANTHROPIC_MODEL='claude-haiku-4-5',
            ANTHROPIC_VISION_MODEL='claude-sonnet-4-6',
        ):
            provider = AnthropicProvider(client=client)

            provider.complete('with image', images=[{'data': b'x', 'media_type': 'image/png'}])
            assert client.messages.create.call_args.kwargs['model'] == 'claude-sonnet-4-6'

            provider.complete('text only')
            assert client.messages.create.call_args.kwargs['model'] == 'claude-haiku-4-5'

    def test_explicit_model_overrides_vision_model(self) -> None:
        from django.test import override_settings

        client = self._make_anthropic_client('RESULT')
        with override_settings(
            ANTHROPIC_MODEL='claude-haiku-4-5',
            ANTHROPIC_VISION_MODEL='claude-sonnet-4-6',
        ):
            provider = AnthropicProvider(client=client)
            provider.complete(
                'with image', images=[{'data': b'x', 'media_type': 'image/png'}],
                model='claude-opus-4-6',
            )
            assert client.messages.create.call_args.kwargs['model'] == 'claude-opus-4-6'


class TestOpenAIProvider:
    def _make_openai_client(self, text: str) -> MagicMock:
        client = MagicMock()
        response = MagicMock()
        message = MagicMock()
        message.content = text
        response.choices = [MagicMock(message=message)]
        client.chat.completions.create.return_value = response
        return client

    def test_complete_with_images_uses_image_url(self) -> None:
        client = self._make_openai_client('RESULT')
        provider = OpenAIProvider(client=client)

        png_bytes = b'fake-png-bytes'
        result = provider.complete('summarize', images=[{'data': png_bytes, 'media_type': 'image/png'}])

        assert result == 'RESULT'
        kwargs = client.chat.completions.create.call_args.kwargs
        content = kwargs['messages'][0]['content']
        assert isinstance(content, list)
        assert content[0]['type'] == 'text'
        assert content[1]['type'] == 'image_url'
        expected = f'data:image/png;base64,{base64.b64encode(png_bytes).decode("ascii")}'
        assert content[1]['image_url']['url'] == expected

    def test_complete_without_images_uses_text_content(self) -> None:
        client = self._make_openai_client('RESULT')
        provider = OpenAIProvider(client=client)

        result = provider.complete('just text')

        assert result == 'RESULT'
        kwargs = client.chat.completions.create.call_args.kwargs
        content = kwargs['messages'][0]['content']
        assert isinstance(content, list)
        assert content[0]['type'] == 'text'
        assert content[0]['text'] == 'just text'

    def test_images_use_vision_model_text_uses_default(self) -> None:
        from django.test import override_settings

        client = self._make_openai_client('RESULT')
        with override_settings(
            OPENAI_MODEL='gpt-5.4-nano',
            OPENAI_VISION_MODEL='gpt-5.4-mini',
        ):
            provider = OpenAIProvider(client=client)

            provider.complete('with image', images=[{'data': b'x', 'media_type': 'image/png'}])
            assert client.chat.completions.create.call_args.kwargs['model'] == 'gpt-5.4-mini'

            provider.complete('text only')
            assert client.chat.completions.create.call_args.kwargs['model'] == 'gpt-5.4-nano'
