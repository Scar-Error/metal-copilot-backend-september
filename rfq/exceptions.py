"""Structured exception types for the RFQ domain."""


class RfqError(Exception):
    """Base exception for all RFQ-domain errors."""


class EmailProviderError(RfqError):
    """Communication failure with the email provider (e.g. Graph API)."""


class AuthExpiredError(EmailProviderError):
    """The OAuth2 token has expired and could not be refreshed."""


class RateLimitError(EmailProviderError):
    """API rate limit exceeded; caller should back off."""


class ExtractionError(RfqError):
    """Failed to extract structured data from an RFQ source."""


class InvalidTransitionError(RfqError):
    """An RFQ status change is not allowed by the state machine."""


class BusinessCentralError(RfqError):
    """Error communicating with Dynamics 365 Business Central."""


class ConfigurationError(RfqError):
    """Missing or invalid configuration."""
