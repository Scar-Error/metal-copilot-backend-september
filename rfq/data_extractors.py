from __future__ import annotations

import json
import logging
import re
from typing import Optional

import anthropic
from django.conf import settings

from rfq.interfaces import DataExtractor, ExtractedRfqData

logger = logging.getLogger(__name__)


class OpenAiExtractor:
    """Extract structured RFQ data via Claude (Anthropic)."""

    def __init__(self) -> None:
        self._client: Optional[anthropic.Anthropic] = None
        if settings.ANTHROPIC_API_KEY:
            try:
                self._client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
            except Exception as exc:
                logger.warning('Anthropic client init failed: %s', exc)

    def extract(self, text: str, source_label: str = '') -> Optional[ExtractedRfqData]:
        if not self._client:
            logger.warning('Anthropic client unavailable')
            return None

        if not text.strip():
            return None

        prompt = f"""Extract RFQ / Purchase Order / Quotation data from the following text.
Return the data in JSON format with these fields:
- company_name: Name of the company sending the RFQ/PO/Quotation
- description: Overall description of what is being requested
- delivery_date: Required delivery date (if available, use YYYY-MM-DD format)
- items: Array of individual line items with:
  - item_number: The numeric value from the Item No. / Item # column (e.g., 1, 2, 3)
  - name: The actual item description from the Description column (NOT the header text)
  - part_number: The part number if available (e.g., "IS-100", "CM-250")
  - quantity: The numeric quantity value from the Qty column (e.g., 1, 2, 10). If quantity is not specified but item exists, assume 1.
  - unit: The exact unit text from the Unit column (e.g., "PC", "PCS", "pcs", "kg"). If unit is not specified but item exists, assume "PC".
  - unit_price: The unit price if present in the text (e.g., 120.00). Extract as a number. If not present, set to null.
  - total_price: The total price for the line item if present (e.g., 1200.00). Extract as a number. If not present, set to null.

CRITICAL RULES:
- Extract ALL items from the table - count the number of rows and ensure every single row is extracted
- DO NOT stop after extracting the first 3-4 items - extract EVERY item in the table
- Extract the ACTUAL VALUES from table rows, NOT the column headers
- Do NOT extract "Item No.", "Description", "Qty", "Unit Price", "Total" as values
- Extract real data like "Industrial Sensor Model IS-100", "Control Module CM-250", "10", "120.00", etc.
- Pay SPECIAL attention to quantity values - extract the EXACT numeric value from the Qty column (e.g., if it says "10", extract 10, not 1)
- Pay SPECIAL attention to unit values - extract the exact values from their respective columns (e.g., "PCS")
- For pricing: Extract unit_price and total_price ONLY if they are present in the table. If not present, set them to null.
- If quantity or unit is empty/null for an item that exists in the table, use 1 for quantity and "PC" for unit as default
- The items array MUST contain all rows from the table - if there are 3 rows, return 3 items
- For tables with | separators (markdown format), each row represents one item - extract all rows

Text content:
{text[:50000]}"""

        try:
            logger.info('Starting AI extraction from %s (text length: %d chars)', source_label, len(text))
            
            response = self._client.messages.create(
                model=getattr(settings, 'ANTHROPIC_MODEL', 'claude-sonnet-4-6'),
                max_tokens=int(getattr(settings, 'OPENAI_MAX_TOKENS', 4000)),
                temperature=float(getattr(settings, 'OPENAI_TEMPERATURE', 0.3)),
                messages=[
                    {
                        'role': 'user',
                        'content': (
                            'You are a data extraction assistant for RFQ documents. '
                            'Extract structured data and return it in JSON format.\n\n'
                            f'{prompt}'
                        ),
                    },
                ],
            )

            raw = response.content[0].text
            logger.info('Anthropic raw response (first 3000 chars): %s', raw[:3000])
            # Strip markdown code fences if present (e.g. ```json ... ```)
            if raw.startswith('```'):
                raw = raw.strip('`')
                if raw.startswith('json'):
                    raw = raw[4:].lstrip()
            data: dict = json.loads(raw)
            
            # Log extracted data details
            logger.info('AI Extraction Results:')
            logger.info('  - Company Name: %s', data.get('company_name', 'N/A'))
            logger.info('  - Description: %s', data.get('description', 'N/A'))
            logger.info('  - Delivery Date: %s', data.get('delivery_date', 'N/A'))
            logger.info('  - Number of Items Extracted: %d', len(data.get('items', [])))
            
            # Log each item extracted
            for idx, item in enumerate(data.get('items', []), 1):
                logger.info('  - Item %d: part_number=%s, description=%s, quantity=%s, unit=%s',
                           idx, item.get('part_number', 'N/A'),
                           item.get('description', 'N/A')[:50] if item.get('description') else 'N/A',
                           item.get('quantity', 'N/A'),
                           item.get('unit', 'N/A'))
            
            data['confidence_score'] = 0.85
            logger.info('AI extraction completed successfully with confidence score: 0.85')
            return ExtractedRfqData(**data)

        except json.JSONDecodeError as exc:
            logger.error('Anthropic response was not valid JSON: %s', exc)
            logger.error('Raw response that failed to parse: %s', raw[:1000] if 'raw' in locals() else 'N/A')
            return None
        except Exception as exc:
            logger.error('Anthropic extraction error: %s', exc)
            return None


class KeywordExtractor:
    """Fallback keyword-based extraction when AI is unavailable."""

    def extract(self, text: str, source_label: str = '') -> Optional[ExtractedRfqData]:
        if not text.strip():
            logger.warning('Keyword extraction: Empty text provided for %s', source_label)
            return None

        logger.info('Starting keyword extraction from %s (text length: %d chars)', source_label, len(text))

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

        # Log keyword extraction results
        logger.info('Keyword Extraction Results:')
        logger.info('  - Company Name: %s', company or 'N/A')
        logger.info('  - Description: %s', description or 'N/A')
        logger.info('  - Part Number: %s', part_number or 'N/A')
        logger.info('  - Quantity: %s', quantity or 'N/A')
        logger.info('  - Delivery Date: %s', delivery_date or 'N/A')
        logger.info('  - Number of Items Extracted: %d', len(items))
        
        for idx, item in enumerate(items, 1):
            logger.info('  - Item %d: part_number=%s, description=%s, quantity=%s, unit=%s',
                       idx, item.get('part_number', 'N/A'),
                       item.get('description', 'N/A')[:50] if item.get('description') else 'N/A',
                       item.get('quantity', 'N/A'),
                       item.get('unit', 'N/A'))
        
        logger.info('Keyword extraction completed with confidence score: 0.5')

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
