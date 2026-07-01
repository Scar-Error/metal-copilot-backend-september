from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, Protocol, TypedDict, runtime_checkable


# ---------------------------------------------------------------------------
# Typed dicts for standard data shapes
# ---------------------------------------------------------------------------

EmailClassification = Literal['rfq', 'po', 'quotation', 'other']

class EmailMessage(TypedDict, total=False):
    id: str
    subject: str
    sender_name: str
    sender_email: str
    received_at: str
    body: str
    has_attachments: bool
    attachments: List[Dict[str, Any]]


class AttachmentData(TypedDict, total=False):
    id: str
    name: str
    size: int
    content_type: str
    content: bytes


class ExtractedItem(TypedDict, total=False):
    item_name: str
    item_code: str
    description: str
    quantity: int
    unit: str
    unit_price: Optional[float]
    total_price: Optional[float]
    part_number: str


class ExtractedRfqData(TypedDict, total=False):
    company_name: str
    items_description: str
    quantity: Optional[int]
    specifications: str
    delivery_date: Optional[str]
    budget: Optional[float]
    items: List[ExtractedItem]
    confidence_score: float
    description: str


class ExtractionResult(TypedDict, total=False):
    success: bool
    data: Optional[ExtractedRfqData]
    confidence_score: float
    errors: Optional[str]


# ---------------------------------------------------------------------------
# Email Provider (abstraction over Microsoft Graph / IMAP / etc.)
# ---------------------------------------------------------------------------

@runtime_checkable
class EmailProvider(Protocol):
    """Fetch, send, and manage emails through a provider."""

    def fetch_emails(
        self,
        folder: str = 'Inbox',
        limit: int = 50,
        days_back: int = 7,
    ) -> List[EmailMessage]:
        """Return recent emails from the given folder."""
        ...

    def get_email_by_id(self, email_id: str) -> Optional[EmailMessage]:
        """Fetch a single email with full details."""
        ...

    def download_attachment(
        self,
        email_id: str,
        attachment_id: str,
    ) -> Optional[bytes]:
        """Download raw bytes of an attachment."""
        ...

    def get_attachments(
        self,
        email_id: str,
    ) -> List[AttachmentData]:
        """List metadata for all attachments on an email."""
        ...

    def send_email(
        self,
        to: str,
        subject: str,
        body: str,
        content_type: str = 'HTML',
    ) -> bool:
        """Send an email on behalf of the authenticated user."""
        ...

    def mark_as_processed(self, email_id: str) -> bool:
        """Tag the email as processed (e.g. add a category)."""
        ...

    def get_user_email(self) -> str:
        """Return the authenticated user's email address."""
        ...


# ---------------------------------------------------------------------------
# Email Classifier (categorise incoming emails)
# ---------------------------------------------------------------------------


@runtime_checkable
class EmailClassifier(Protocol):
    """Classify an incoming email as RFQ/PO, Quotation, or Other."""

    def classify(self, email: EmailMessage) -> EmailClassification:
        """
        Return one of ``'rfq_po'``, ``'quotation'``, or ``'other'``.
        """
        ...


# ---------------------------------------------------------------------------
# Document Parser (extract text from PDF / DOCX / XLSX)
# ---------------------------------------------------------------------------

@runtime_checkable
class DocumentParser(Protocol):
    """Extract plain text from a document file."""

    def supported_extensions(self) -> List[str]:
        """List of file extensions this parser handles (e.g. ['.pdf'])."""
        ...

    def extract_text(self, file_path: str) -> str:
        """Return the full text content of the document."""
        ...


# ---------------------------------------------------------------------------
# Data Extractor (AI / fallback)
# ---------------------------------------------------------------------------

@runtime_checkable
class DataExtractor(Protocol):
    """Extract structured RFQ data from text content."""

    def extract(self, text: str, source_label: str = '') -> Optional[ExtractedRfqData]:
        """
        Parse text and return structured RFQ data.
        Returns None if extraction is not possible.
        """
        ...


# ---------------------------------------------------------------------------
# File Storage (local filesystem / S3 / Azure Blob)
# ---------------------------------------------------------------------------

@runtime_checkable
class FileStorage(Protocol):
    """Persist and retrieve files."""

    def save(self, filename: str, content: bytes, subdir: str = '') -> str:
        """Save a file and return its full path."""
        ...

    def delete(self, path: str) -> bool:
        """Remove a file. Return True on success."""
        ...

    def exists(self, path: str) -> bool:
        """Check whether a file exists."""
        ...


# ---------------------------------------------------------------------------
# Business Central Client
# ---------------------------------------------------------------------------

@runtime_checkable
class BusinessCentralClient(Protocol):
    """Integration with Microsoft Dynamics 365 Business Central."""

    def get_companies(self) -> List[Dict[str, Any]]:
        """Return list of available company records."""
        ...

    def get_products(self, company_id: str) -> List[Dict[str, Any]]:
        """Return product/item master data for a company."""
        ...

    def create_sales_quote(
        self,
        company_id: str,
        quote_data: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Create a sales quote and return the created record."""
        ...

    def add_quote_line(
        self,
        company_id: str,
        quote_id: str,
        line_data: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Add a line item to an existing sales quote."""
        ...

    def create_purchase_order(
        self,
        company_id: str,
        po_data: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Create a purchase order and return the created record."""
        ...
