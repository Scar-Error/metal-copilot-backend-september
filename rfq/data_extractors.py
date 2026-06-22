from __future__ import annotations

import json
import logging
import re
from typing import Optional

import openai
from django.conf import settings

from rfq.interfaces import DataExtractor, ExtractedRfqData

logger = logging.getLogger(__name__)


class OpenAiExtractor:
    """Extract structured RFQ data via OpenAI GPT."""

    def __init__(self) -> None:
        self._client: Optional[openai.OpenAI] = None
        if settings.OPENAI_API_KEY:
            try:
                self._client = openai.OpenAI(api_key=settings.OPENAI_API_KEY)
            except Exception as exc:
                logger.warning('OpenAI client init failed: %s', exc)

    def extract(self, text: str, source_label: str = '') -> Optional[ExtractedRfqData]:
        if not self._client:
            logger.warning('OpenAI client unavailable')
            return None

        if not text.strip():
            return None

        prompt = f"""Extract RFQ / Purchase Order data from the following text.
Return the data in JSON format with these fields:
- company_name: Name of the company sending the RFQ/PO
- description: Overall description of what is being requested
- delivery_date: Required delivery date (if available, use YYYY-MM-DD format)
- items: Array of individual line items with:
  - description: Item description
  - part_number: Part number / SKU (if available)
  - quantity: Quantity requested
  - unit: Unit of measurement (pcs, kg, meters, etc.)

Extract only what is explicitly present. Do NOT extract pricing information.

Text content:
{text[:4000]}"""

        try:
            response = self._client.chat.completions.create(
                model=getattr(settings, 'OPENAI_MODEL', 'gpt-3.5-turbo'),
                messages=[
                    {
                        'role': 'system',
                        'content': (
                            'You are a data extraction assistant for RFQ documents. '
                            'Extract structured data and return it in JSON format.'
                        ),
                    },
                    {'role': 'user', 'content': prompt},
                ],
                temperature=float(getattr(settings, 'OPENAI_TEMPERATURE', 0.3)),
                max_tokens=int(getattr(settings, 'OPENAI_MAX_TOKENS', 1500)),
            )

            raw = response.choices[0].message.content
            # Strip markdown code fences if present (e.g. ```json ... ```)
            if raw.startswith('```'):
                raw = raw.strip('`')
                if raw.startswith('json'):
                    raw = raw[4:].lstrip()
            data: dict = json.loads(raw)
            data['confidence_score'] = 0.85
            return ExtractedRfqData(**data)

        except json.JSONDecodeError:
            logger.error('OpenAI response was not valid JSON')
            return None
        except Exception as exc:
            logger.error('OpenAI extraction error: %s', exc)
            return None


class KeywordExtractor:
    """Fallback keyword-based extraction when AI is unavailable."""

    def extract(self, text: str, source_label: str = '') -> Optional[ExtractedRfqData]:
        if not text.strip():
            return None

        company = self._first_match(text, [
            r'from\s*:\s*(.+)',
            r'company\s*:\s*(.+)',
            r'vendor\s*:\s*(.+)',
            r'supplier\s*:\s*(.+)',
        ])
        description = self._first_match(text, [
            r'items?\s*:\s*(.+)',
            r'products?\s*:\s*(.+)',
            r'materials?\s*:\s*(.+)',
            r'equipment\s*:\s*(.+)',
        ])
        part_number = self._first_match(text, [
            r'part\s*#?\s*:\s*(.+)',
            r'part\s*no[.:]?\s*(.+)',
            r'p/n\s*:\s*(.+)',
            r'item\s*#?\s*:\s*(.+)',
            r'sku\s*:\s*(.+)',
        ])

        quantity_match = re.search(r'quantity\s*:\s*(\d+)', text.lower())
        quantity = int(quantity_match.group(1)) if quantity_match else None

        delivery_match = re.search(
            r'(delivery|due|required)\s*(date)?\s*:\s*(\d{4}-\d{2}-\d{2})',
            text.lower(),
        )
        delivery_date = delivery_match.group(3) if delivery_match else None

        items = []
        if part_number:
            items.append({
                'description': description or 'Unknown item',
                'part_number': part_number,
                'quantity': quantity or 1,
                'unit': 'pcs',
            })
        elif description:
            items.append({
                'description': description,
                'part_number': '',
                'quantity': quantity or 1,
                'unit': 'pcs',
            })

        return ExtractedRfqData(
            company_name=company or 'Unknown Company',
            description=description or 'Various items',
            items_description=description or 'Various items',
            quantity=quantity,
            specifications='',
            delivery_date=delivery_date,
            budget=None,
            confidence_score=0.5,
            items=items,
        )

    @staticmethod
    def _first_match(text: str, patterns: list[str]) -> Optional[str]:
        lower = text.lower()
        for pattern in patterns:
            # Try the regex on the lower-case version, but keep original case for the result
            match = re.search(pattern, lower)
            if match:
                value = match.group(1).strip().split('\n')[0].strip()
                if len(value) > 2:
                    return value
        return None
