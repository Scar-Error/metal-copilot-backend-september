from __future__ import annotations

import pytest

from rfq.document_parsers import PdfParser, DocxParser, XlsxParser, get_parser


class TestGetParser:
    def test_pdf(self) -> None:
        parser = get_parser('doc.pdf')
        assert isinstance(parser, PdfParser)

    def test_docx(self) -> None:
        parser = get_parser('doc.docx')
        assert isinstance(parser, DocxParser)

    def test_doc(self) -> None:
        parser = get_parser('doc.doc')
        assert isinstance(parser, DocxParser)

    def test_xlsx(self) -> None:
        parser = get_parser('data.xlsx')
        assert isinstance(parser, XlsxParser)

    def test_xls(self) -> None:
        parser = get_parser('data.xls')
        assert isinstance(parser, XlsxParser)

    def test_unsupported(self) -> None:
        parser = get_parser('readme.txt')
        assert parser is None


class TestParsersEmptyFile:
    def test_pdf_empty(self, tmp_path) -> None:
        p = tmp_path / 'empty.pdf'
        p.write_text('')
        result = PdfParser.extract_text(str(p))
        assert result == ''

    def test_docx_empty(self, tmp_path) -> None:
        p = tmp_path / 'empty.docx'
        p.write_text('')
        result = DocxParser.extract_text(str(p))
        assert result == ''

    def test_xlsx_empty(self, tmp_path) -> None:
        p = tmp_path / 'empty.xlsx'
        p.write_text('')
        result = XlsxParser.extract_text(str(p))
        assert result == ''
