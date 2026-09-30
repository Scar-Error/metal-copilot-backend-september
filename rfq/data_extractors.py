from __future__ import annotations

import json
import logging
from typing import List, Optional

from django.conf import settings

from rfq.ai_providers import AIProviderUnavailable, get_ai_provider
from rfq.interfaces import DataExtractor, ExtractedRfqData

logger = logging.getLogger(__name__)

# Round 2: pull every visible detail out of the attached images (nameplate/label
# specs, physical part identity, logo/company, tags, handwritten notes, ...).
_IMAGE_DETAILS_PROMPT = """Carefully examine ALL attached images. They are all part of the same request and each contributes context about the SAME item(s).

Your task is SOLELY to extract every NUMBER, CODE and ALPHANUMERIC character string visible on the images - they are the most important data. Transcribe them EXACTLY as written, character for character.

Extract and list every alphanumeric value you can read, including:
- Manufacturer / brand codes and names
- Model / type numbers (e.g., "2200 AR")
- Serial numbers
- Sizes and dimensions (e.g., "1½ in", "DN25", "25 mm")
- Material designations (e.g., "L1.0619", "316 Stainless Steel / 316 STE", "B30")
- Ratings and ranges (e.g., "6 to 18 PSI", "Pin: 46", "10 bar", "230V", "50Hz", "2.2 kW")
- Barcodes and their numeric values
- Dates (e.g., "23/10/2023")
- Any other codes printed on labels, nameplates, tags, or handwritten notes

Format the output as a list of exactly what is written, preserving the label name and its exact value, e.g.:
Manufacturer: CONFLOW
Type: 2200 AR
Serial No.: 093664
Fluid: Air
Size: 1½ in
Body Material: L1.0619
Spring Range: 6 to 18 PSI
Pin: 46
Date: 23/10/2023

Do NOT describe the appearance of the object, its shape, color, bolts, or surroundings. Do NOT invent values. Only output the exact alphanumeric values you can see. If the same value appears in multiple images, list it once. Never repeat the same value more than once. If you see grid-like repeated characters, printed rows, or repeated decoration, output it once with the total count (e.g., "column header repeated ~100 times") instead of repeating it. Focus especially on any small nameplate or label text - read it carefully and transcribe every code exactly.

HALLUCINATION RULE (CRITICAL): You must NEVER guess, estimate, or invent a number, serial, code, or value. If a value is not clearly and legibly readable in the image, write exactly "NOT READABLE" instead of making one up. An honest "NOT READABLE" is always better than a fabricated value. Only transcribe a value when you are confident it matches what is printed."""

# Round 3: turn the email text + extracted image details into structured JSON.
def _build_structured_prompt(text: str, image_details: Optional[str]) -> str:
    details_section = ''
    if image_details:
        details_section = (
            '\n\nDetails extracted from the attached images (combine with the text above):\n'
            + image_details
        )
    return f"""Extract RFQ / Purchase Order / Quotation data from the email text and the extracted image details.

Return the data in JSON format with these fields:
- company_name: Name of the company sending the RFQ/PO/Quotation (from logo/letterhead in the image details or the text)
- description: Overall description of what is being requested
- notes: Any additional information that does not fit into the line items (delivery instructions, payment terms, packaging, remarks, special conditions). This is saved into the RFQ's notes field. If there is nothing extra, omit it.
- delivery_date: Required delivery date (if available, use YYYY-MM-DD format)
- items: Array of individual line items with:
  - item_number: The numeric value from the Item No. / Item # column (e.g., 1, 2, 3)
  - name: The actual item description. This is shown in the 'Description 2' column. Include the item's technical identity (e.g., "Valve - Control 2200 AR"). This is the item description, NOT the part number.
  - part_number: The part number / manufacturer code / model / type of the item when visible on a nameplate or in the text (e.g., "2200 AR", "IS-100"). This is shown in the 'Description' column. This is the part number, NOT the description. If none, null.
  - quantity: The numeric quantity value from the Qty column (e.g., 1, 2, 10). If quantity is not specified but item exists, assume 1.
  - unit: One of "pc", "pcs", "kg", "ltr" (lowercase). Read the Unit column and map it to exactly one of those: "PC"/"PCS": "pc" or "pcs", "KG" → "kg", "LTR"/"L"/"LITER" → "ltr". If unit is not specified but item exists, assume "pc".
  - unit_price: The unit price if present in the text (e.g., 120.00). Extract as a number. If not present, set to null.
  - total_price: The total price for the line item if present (e.g., 1200.00). Extract as a number. If not present, set to null.

CRITICAL RULES:
- Use the extracted image details as the source of truth for the item's identity and specifications.
- Do NOT create separate items just because the same part appears in a photo and on a nameplate - merge them into ONE item.
- Extract ALL items from the table - count the number of rows and ensure every single row is extracted
- DO NOT stop after extracting the first 3-4 items - extract EVERY item in the table
- Extract the ACTUAL VALUES from table rows, NOT the column headers
- Do NOT extract "Item No.", "Description", "Qty", "Unit Price", "Total" as values
- Extract real data like "Industrial Sensor Model IS-100", "Control Module CM-250", "10", "120.00", etc.
- Pay SPECIAL attention to quantity values - extract the EXACT numeric value from the Qty column (e.g., if it says "10", extract 10, not 1)
- Pay SPECIAL attention to unit values - extract a unit from exactly: pc, pcs, kg, ltr
- CRITICAL: 'name' holds the item description ('Description 2' column) and 'part_number' holds the part number ('Description' column). NEVER put the description into part_number, and NEVER put the part number into name.
- CRITICAL: 'name' and 'part_number' must each be at most 99 characters long.
- If 'name' (the item description) is longer than 99 characters, split it into chunks of at most 99 characters: keep the first 99 characters in 'name' of the main item, then add ONE extra item per remaining chunk with part_number set to exactly "comment" and name set to that remaining chunk. A 'comment' item is a continuation line, NOT a real part: set its quantity to 0, unit to null, unit_price and total_price to null.
- For pricing: Extract unit_price and total_price ONLY if they are present in the table. If not present, set them to null.
- If quantity or unit is empty/null for a real item that exists in the table, use 1 for quantity and "pc" for unit as default
- The items array MUST contain all rows from the table - if there are 3 rows, return 3 items
- For tables with | separators (markdown format), each row represents one item - extract all rows
- If the email body text contains no line items but the image details do, extract the items from the details and leave description/delivery_date derived from the text when available.

Text content:
{text[:50000]}{details_section}"""


class OpenAiExtractor:
    """Extract structured RFQ data via the configured AI provider.

    Extraction runs in focused rounds:
    - Round 1 (type) is performed upstream by ``AiEmailClassifier``.
    - Round 2 extracts every visible detail from attached images (vision).
    - Round 3 builds the structured JSON from email text + image details.
    """

    def __init__(self, provider=None) -> None:
        self._provider = provider
        # Why extraction is off, when it is. Reported to the UI rather than
        # swallowed, so "no items extracted" is distinguishable from "no AI".
        self.unavailable_reason = ''
        if self._provider is not None:
            return
        try:
            self._provider = get_ai_provider()
        except AIProviderUnavailable as exc:
            logger.warning('AI provider unavailable; extraction disabled: %s', exc)
            self.unavailable_reason = str(exc) or 'no reason given'
            self._provider = None

    def extract(
        self,
        text: str,
        source_label: str = '',
        is_quotation: bool = False,
        images: Optional[List[dict]] = None,
        order_id: Optional[int] = None,
    ) -> Optional[ExtractedRfqData]:
        if self._provider is None:
            logger.warning('AI provider unavailable: %s', self.unavailable_reason)
            return None

        if not text.strip():
            return None

        if is_quotation:
            logger.info('=== QUOTATION EMAIL PROCESSING ===')
        else:
            logger.info('=== RFQ EMAIL PROCESSING ===')
        logger.info(
            'Starting 3-round AI extraction from %s (text length: %d chars, images: %d, provider: %s)',
            source_label, len(text), len(images or []), self._provider.name,
        )

        # Round 2: extract details from images (only when images present).
        image_details = None
        if images:
            logger.info('Round 2/3: extracting details from %d attached image(s)', len(images))
            image_details = self._extract_image_details(images, order_id=order_id)

        # Round 3: structured extraction from email text + image details.
        logger.info(
            'Round 3/3: structured extraction (text length: %d chars, image details: %s)',
            len(text), 'present' if image_details else 'none',
        )
        raw = self._extract_structured(text, image_details, order_id=order_id)

        try:
            # Strip markdown code fences if present
            cleaned = raw.strip()
            if cleaned.startswith('```'):
                # Remove opening fence (```json or ```)
                first_newline = cleaned.index('\n')
                cleaned = cleaned[first_newline + 1:]
            if cleaned.endswith('```'):
                cleaned = cleaned[:-3]
            cleaned = cleaned.strip()

            # Extract just the JSON object (ignore trailing notes/text)
            # Find the matching closing brace for the first opening brace
            brace_depth = 0
            json_end = 0
            in_json = False
            for i, ch in enumerate(cleaned):
                if ch == '{':
                    if not in_json:
                        in_json = True
                    brace_depth += 1
                elif ch == '}':
                    brace_depth -= 1
                    if brace_depth == 0:
                        json_end = i + 1
                        break
            if json_end > 0:
                cleaned = cleaned[:json_end]

            data: dict = json.loads(cleaned)

            logger.info('AI Extraction Results:')
            logger.info('  - Company Name: %s', data.get('company_name', 'N/A'))
            logger.info('  - Description: %s', data.get('description', 'N/A'))
            logger.info('  - Delivery Date: %s', data.get('delivery_date', 'N/A'))
            logger.info('  - Number of Items Extracted: %d', len(data.get('items', [])))

            for idx, item in enumerate(data.get('items', []), 1):
                item_name = (
                    item.get('name') or item.get('description')
                    or item.get('item_name') or item.get('item_description') or 'N/A'
                )
                unit_price = item.get('unit_price')
                if unit_price:
                    logger.info(
                        '  - Item %d: part_number=%s, name=%s, quantity=%s, unit=%s, unit_price=%s',
                        idx, item.get('part_number', 'N/A'),
                        item_name[:50] if item_name and item_name != 'N/A' else 'N/A',
                        item.get('quantity', 'N/A'),
                        item.get('unit', 'N/A'),
                        unit_price,
                    )
                else:
                    logger.info(
                        '  - Item %d: part_number=%s, name=%s, quantity=%s, unit=%s',
                        idx, item.get('part_number', 'N/A'),
                        item_name[:50] if item_name and item_name != 'N/A' else 'N/A',
                        item.get('quantity', 'N/A'),
                        item.get('unit', 'N/A'),
                    )
                logger.debug('  - Item %d all fields: %s', idx, item)

            data['confidence_score'] = 0.85
            logger.info('AI extraction completed successfully with confidence score: 0.85')
            return ExtractedRfqData(**data)

        except json.JSONDecodeError as exc:
            logger.error('AI response was not valid JSON: %s', exc)
            logger.error('Raw response that failed to parse: %s', raw[:1000] if raw else 'N/A')
            return None
        except Exception as exc:
            logger.error('AI extraction error: %s', exc)
            return None

    def _extract_image_details(self, images: List[dict], order_id: Optional[int] = None) -> Optional[str]:
        """Round 2: vision pass over all images producing a details blob.

        The provider routes image requests to the vision model automatically;
        text-only rounds keep the default model.
        """
        try:
            details = self._provider.complete(
                _IMAGE_DETAILS_PROMPT,
                images=images,
                max_tokens=int(getattr(settings, 'OPENAI_IMAGE_DETAILS_MAX_TOKENS', 1500)),
                temperature=0,
                use='image_details',
                order_id=order_id,
            )
            logger.info('Round 2 image details extracted (%d chars): %s', len(details), details[:3000])
            return details
        except Exception as exc:
            logger.error('Round 2 image details extraction failed: %s', exc)
            return None

    def _extract_structured(self, text: str, image_details: Optional[str], order_id: Optional[int] = None) -> Optional[str]:
        """Round 3: structured JSON extraction from text + image details."""
        prompt = _build_structured_prompt(text, image_details)
        try:
            raw = self._provider.complete(
                prompt,
                images=None,
                max_tokens=int(getattr(settings, 'OPENAI_MAX_TOKENS', 4000)),
                temperature=float(getattr(settings, 'OPENAI_TEMPERATURE', 0.3)),
                use='extraction',
                order_id=order_id,
            )
            logger.info('Round 3 raw response (first 3000 chars): %s', raw[:3000])
            if raw.startswith('```'):
                raw = raw.strip('`')
                if raw.startswith('json'):
                    raw = raw[4:].lstrip()
            return raw
        except Exception as exc:
            logger.error('Round 3 structured extraction failed: %s', exc)
            raise
