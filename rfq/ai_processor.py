from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from rfq.data_extractors import OpenAiExtractor, KeywordExtractor
from rfq.document_parsers import extract_text, get_parser
from rfq.interfaces import DataExtractor, ExtractedRfqData

logger = logging.getLogger(__name__)


class AIProcessor:
    """
    Process order attachments and extract structured data.

    Delegates to focused parsers and extractors.
    Kept for backward compatibility; prefer using
    ``document_parsers`` / ``data_extractors`` directly.
    """

    def __init__(self) -> None:
        self._ai_extractor: DataExtractor = OpenAiExtractor()
        self._fallback_extractor: DataExtractor = KeywordExtractor()

    def process_attachment(
        self,
        file_path: str,
        file_type: str,
    ) -> Dict[str, Any]:
        try:
            text = extract_text(file_path)
            if not text:
                logger.warning('No text extracted from %s', file_path)
                return self._build_fallback_result(file_path, file_type)

            extracted = self._ai_extractor.extract(text, file_type)
            if extracted is None:
                extracted = self._fallback_extractor.extract(text, file_type)

            if extracted is None:
                return self._build_fallback_result(file_path, file_type)

            return {
                'success': True,
                'data': dict(extracted),
                'confidence_score': extracted.get('confidence_score', 0.0),
                'processing_time': 2.5,
                'errors': None,
            }
        except Exception as exc:
            logger.error('Error processing attachment: %s', exc)
            return {
                'success': False,
                'data': None,
                'confidence_score': 0.0,
                'processing_time': 0,
                'errors': str(exc),
            }

    def extract_data_with_ai(
        self,
        text: str,
        source_type: str = '',
    ) -> Optional[Dict[str, Any]]:
        extracted = self._ai_extractor.extract(text, source_type)
        if extracted is None:
            extracted = self._fallback_extractor.extract(text, source_type)
        return dict(extracted) if extracted else None

    # ------------------------------------------------------------------
    # Deprecated / unused stubs kept for import safety
    # ------------------------------------------------------------------

    def extract_text_from_document(self, file_path: str, file_type: str) -> str:
        return extract_text(file_path)

    def _extract_from_pdf(self, file_path: str) -> str:
        parser = get_parser(file_path)
        return parser.extract_text(file_path) if parser else ''

    def _extract_from_docx(self, file_path: str) -> str:
        parser = get_parser(file_path)
        return parser.extract_text(file_path) if parser else ''

    def _extract_from_xlsx(self, file_path: str) -> str:
        parser = get_parser(file_path)
        return parser.extract_text(file_path) if parser else ''

    def _get_fallback_data(
        self,
        file_path: str,
        file_type: str,
    ) -> Dict[str, Any]:
        return self._build_fallback_result(file_path, file_type)

    def validate_extracted_data(self, data: Dict) -> bool:
        return bool(data.get('company_name'))

    def calculate_confidence_score(self, data: Dict) -> float:
        return data.get('confidence_score', 0.7)

    @staticmethod
    def _build_fallback_result(
        file_path: str,
        file_type: str,
    ) -> Dict[str, Any]:
        text = extract_text(file_path)
        extractor = KeywordExtractor()
        data = extractor.extract(text, file_type) or ExtractedRfqData(
            company_name='Unknown Company',
            items_description='Various items',
            quantity=None,
            specifications='',
            delivery_date=None,
            budget=None,
            confidence_score=0.5,
            items=[],
        )
        return {
            'success': True,
            'data': dict(data),
            'confidence_score': data.get('confidence_score', 0.5),
            'processing_time': 1.0,
            'errors': None,
        }
