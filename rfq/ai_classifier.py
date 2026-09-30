from __future__ import annotations

import logging
from typing import Optional

from rfq.ai_providers import AIProviderUnavailable, get_ai_provider
from rfq.interfaces import EmailClassification, EmailMessage

logger = logging.getLogger(__name__)


class ClassificationUnavailable(Exception):
    """Raised when an email cannot be classified (missing key / API / parse error)."""


class AiEmailClassifier:
    """
    Classify an incoming email as ``rfq`` | ``po`` | ``quotation`` | ``other``
    using the configured AI provider (Anthropic or OpenAI). No keyword heuristics.
    """

    _TYPE_MAP = {
        'RFQ': 'rfq',
        'PURCHASE_ORDER': 'po',
        'QUOTATION': 'quotation',
        'OTHER': 'other',
    }

    def __init__(self, provider=None) -> None:
        self._provider = provider
        # Kept, not just logged. It is the only thing that says *which* key is
        # missing, and it is what the pipeline reports back to the UI; a bare
        # "AI provider unavailable" left a 401 and a missing key looking alike.
        self.unavailable_reason = ''
        if self._provider is not None:
            return
        try:
            self._provider = get_ai_provider()
        except AIProviderUnavailable as exc:
            logger.error('AI provider unavailable; classification disabled: %s', exc)
            self.unavailable_reason = str(exc) or 'no reason given'
            self._provider = None

    def classify(self, email: EmailMessage) -> EmailClassification:
        if self._provider is None:
            raise ClassificationUnavailable(
                f'AI provider unavailable: {self.unavailable_reason or "unknown reason"}'
            )

        subject = email.get('subject') or ''
        body = email.get('body') or ''
        text = f'Subject: {subject}\n\nBody: {body[:5000]}'

        prompt = (
            'You are an expert procurement document classifier.\n\n'
            'Your task is to classify an email into exactly ONE of these document types:\n\n'
            '1. RFQ (Request for Quotation)\n'
            '2. QUOTATION (Supplier Quote / Proposal)\n'
            '3. PURCHASE_ORDER (PO)\n'
            '4. OTHER\n\n'
            'Classification Rules:\n'
            '- RFQ: A customer is requesting prices, availability, lead times, or quotations.\n'
            '- QUOTATION: A supplier is responding with prices (contains pricing, validity, payment terms).\n'
            '- PURCHASE_ORDER: A buyer is confirming a purchase and instructing supply of goods (PO number, order confirmation).\n'
            '- OTHER: Anything that is not one of the above (newsletters, bounces, meeting invites, etc.).\n\n'
            'Reply with ONLY ONE word: RFQ, PURCHASE_ORDER, QUOTATION, or OTHER.\n\n'
            f'Email content:\n{text}'
        )

        try:
            raw = self._provider.complete(
                prompt,
                max_tokens=10,
                temperature=0,
                use='classification',
                subject=subject,
            )
        except Exception as exc:
            logger.error('AI classification failed: %s', exc)
            raise ClassificationUnavailable(str(exc)) from exc

        answer = self._normalize(raw)
        classification = self._TYPE_MAP.get(answer, 'other')
        logger.info('AI email classification result: %s', classification)
        return classification

    @staticmethod
    def _normalize(raw: str) -> str:
        answer = raw.strip()
        if answer.startswith('```'):
            answer = answer.strip('`').strip()
            if answer.lower().startswith('json'):
                answer = answer[4:].lstrip()
        return answer.upper()
