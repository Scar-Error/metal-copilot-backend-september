from __future__ import annotations

import base64
import logging
from typing import List, Optional

from django.conf import settings

logger = logging.getLogger(__name__)

# Canonical models for each provider switch value.
AI_PROVIDER_MODELS = {
    'anthropic': 'claude-haiku-4-5',
    'openai': 'gpt-5.4-nano',
}

# Values used in .env templates that should be treated as "not configured".
_PLACEHOLDER = {'', '***'}


class AIProviderUnavailable(Exception):
    """Raised when the configured AI provider cannot be initialised."""


def _resolved_model(env_value: str, provider_name: str) -> str:
    """Pick a model, ignoring empty/placeholder env values."""
    if env_value not in _PLACEHOLDER:
        return env_value
    return AI_PROVIDER_MODELS.get(provider_name, AI_PROVIDER_MODELS['anthropic'])


def _log_subject(subject: Optional[str]) -> None:
    if subject:
        logger.info('Email subject -> %s', subject[:500])


class AnthropicProvider:
    """Claude (Anthropic) provider."""

    name = 'anthropic'

    def __init__(self, client=None) -> None:
        self.model = _resolved_model(
            getattr(settings, 'ANTHROPIC_MODEL', ''), self.name,
        )
        self._client = client
        if self._client is not None:
            return
        if not settings.ANTHROPIC_API_KEY:
            logger.error('ANTHROPIC_API_KEY is not configured; AI unavailable')
            raise AIProviderUnavailable('ANTHROPIC_API_KEY is not configured')
        try:
            import anthropic
            self._client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        except Exception as exc:
            logger.error('Anthropic client init failed: %s', exc)
            raise AIProviderUnavailable(str(exc)) from exc

    @property
    def vision_model(self) -> str:
        """Model used when the request contains images; falls back to the text model."""
        configured = getattr(settings, 'ANTHROPIC_VISION_MODEL', '')
        return configured if configured not in _PLACEHOLDER else self.model

    def complete(
        self,
        prompt: str,
        images: Optional[List[dict]] = None,
        max_tokens: int = 1000,
        temperature: float = 0,
        model: Optional[str] = None,
        use: str = 'general',
        order_id: Optional[int] = None,
        subject: Optional[str] = None,
    ) -> str:
        # Only image requests are routed to the vision model; all text requests
        # use the default model. An explicit `model=` always wins.
        model = model or (self.vision_model if images else self.model)
        image_count = len(images or [])
        content: object = prompt
        if images:
            blocks: List[dict] = []
            for i, img in enumerate(images):
                encoded = base64.b64encode(img['data']).decode('ascii')
                media_type = img.get('media_type') or 'image/png'
                blocks.append({
                    'type': 'image',
                    'source': {
                        'type': 'base64',
                        'media_type': media_type,
                        'data': encoded,
                    },
                })
                logger.info(
                    'Anthropic: [img %d/%d] name=%s media_type=%s raw_bytes=%d base64_chars=%d',
                    i + 1, len(images), img.get('name', '?'), media_type,
                    len(img['data']), len(encoded),
                )
            blocks.append({'type': 'text', 'text': prompt})
            content = blocks
            logger.info(
                'Anthropic: request content has %d blocks (%d image + 1 text), model=%s',
                len(blocks), len(images), model,
            )
        else:
            logger.info('Anthropic: sending text-only request (1 text block), model=%s', model)
            _log_subject(subject)

        response = self._client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=[{'role': 'user', 'content': content}],
        )
        usage = getattr(response, 'usage', None)
        if usage is not None:
            logger.info(
                'Anthropic: response usage -> input_tokens=%s output_tokens=%s',
                getattr(usage, 'input_tokens', '?'), getattr(usage, 'output_tokens', '?'),
            )
        logger.info('Anthropic: raw response text -> %s', response.content[0].text[:3000])
        self._record_usage(model, use, usage, image_count, order_id)
        return response.content[0].text

    def _record_usage(self, model, use, usage, image_count, order_id) -> None:
        if usage is None:
            return
        input_tokens = getattr(usage, 'input_tokens', None)
        output_tokens = getattr(usage, 'output_tokens', None)
        if not isinstance(input_tokens, int) or not isinstance(output_tokens, int):
            return
        try:
            from rfq.ai_usage import record_usage
            record_usage(
                provider=self.name,
                model=model,
                use=use,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                image_count=image_count,
                order_id=order_id,
            )
        except Exception as exc:
            logger.error('Failed to record AI usage for %s/%s: %s', self.name, model, exc)


class OpenAIProvider:
    """GPT (OpenAI) provider."""

    name = 'openai'

    def __init__(self, client=None) -> None:
        self.model = _resolved_model(
            getattr(settings, 'OPENAI_MODEL', ''), self.name,
        )
        self._client = client
        if self._client is not None:
            return
        if not settings.OPENAI_API_KEY:
            logger.error('OPENAI_API_KEY is not configured; AI unavailable')
            raise AIProviderUnavailable('OPENAI_API_KEY is not configured')
        try:
            from openai import OpenAI
            self._client = OpenAI(api_key=settings.OPENAI_API_KEY)
        except Exception as exc:
            logger.error('OpenAI client init failed: %s', exc)
            raise AIProviderUnavailable(str(exc)) from exc

    @property
    def vision_model(self) -> str:
        """Model used when the request contains images; falls back to the text model."""
        configured = getattr(settings, 'OPENAI_VISION_MODEL', '')
        return configured if configured not in _PLACEHOLDER else self.model

    def complete(
        self,
        prompt: str,
        images: Optional[List[dict]] = None,
        max_tokens: int = 1000,
        temperature: float = 0,
        model: Optional[str] = None,
        use: str = 'general',
        order_id: Optional[int] = None,
        subject: Optional[str] = None,
    ) -> str:
        # Only image requests are routed to the vision model; all text requests
        # use the default model. An explicit `model=` always wins.
        model = model or (self.vision_model if images else self.model)
        image_count = len(images or [])
        content: List[dict] = [{'type': 'text', 'text': prompt}]
        if images:
            for i, img in enumerate(images):
                encoded = base64.b64encode(img['data']).decode('ascii')
                media_type = img.get('media_type') or 'image/png'
                uri = f'data:{media_type};base64,{encoded}'
                content.append({
                    'type': 'image_url',
                    'image_url': {
                        'url': uri,
                        'detail': 'high',
                    },
                })
                logger.info(
                    'OpenAI: [img %d/%d] name=%s media_type=%s raw_bytes=%d base64_chars=%d data_uri=%s...',
                    i + 1, len(images), img.get('name', '?'), media_type,
                    len(img['data']), len(encoded), uri[:64],
                )
            logger.info(
                'OpenAI: request message content has %d parts (%d text + %d image_url), model=%s',
                len(content), 1, len(images), model,
            )
        else:
            logger.info('OpenAI: sending text-only request (1 text part), model=%s', model)

        logger.info(
            'OpenAI: payload part types -> %s',
            [p['type'] for p in content],
        )
        _log_subject(subject)

        kwargs = {
            'model': model,
            'temperature': temperature,
            'messages': [{'role': 'user', 'content': content}],
        }
        # gpt-5 / o-series models use max_completion_tokens; older models use max_tokens.
        if model.lower().startswith(('gpt-5', 'o')):
            kwargs['max_completion_tokens'] = max_tokens
        else:
            kwargs['max_tokens'] = max_tokens

        response = self._client.chat.completions.create(**kwargs)
        usage = getattr(response, 'usage', None)
        if usage is not None:
            logger.info(
                'OpenAI: response usage -> prompt_tokens=%s completion_tokens=%s total_tokens=%s',
                getattr(usage, 'prompt_tokens', '?'),
                getattr(usage, 'completion_tokens', '?'),
                getattr(usage, 'total_tokens', '?'),
            )
        logger.info('OpenAI: raw response text -> %s', response.choices[0].message.content[:3000])
        self._record_usage(model, use, usage, image_count, order_id)
        return response.choices[0].message.content

    def _record_usage(self, model, use, usage, image_count, order_id) -> None:
        if usage is None:
            return
        input_tokens = getattr(usage, 'prompt_tokens', None)
        output_tokens = getattr(usage, 'completion_tokens', None)
        if not isinstance(input_tokens, int) or not isinstance(output_tokens, int):
            return
        try:
            from rfq.ai_usage import record_usage
            record_usage(
                provider=self.name,
                model=model,
                use=use,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                image_count=image_count,
                order_id=order_id,
            )
        except Exception as exc:
            logger.error('Failed to record AI usage for %s/%s: %s', self.name, model, exc)


def get_ai_provider():
    """Build the AI provider selected by ``settings.AI_PROVIDER``.

    Returns ``AnthropicProvider`` or ``OpenAIProvider`` and raises
    ``AIProviderUnavailable`` if the required API key is missing.
    """
    provider_name = getattr(settings, 'AI_PROVIDER', 'anthropic')
    if provider_name == 'openai':
        return OpenAIProvider()
    return AnthropicProvider()
