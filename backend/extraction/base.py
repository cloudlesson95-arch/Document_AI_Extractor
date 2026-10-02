import abc
from .schema import ExtractedReceipt

# File types every VisionExtractor accepts, so an upload behaves the same on every provider
SUPPORTED_MIME_TYPES = frozenset({"image/jpeg", "image/png", "image/webp", "application/pdf"})


class ExtractionError(Exception):
    """The model call failed, or its output didn't match ExtractedReceipt."""


class VisionExtractor(abc.ABC):
    """Abstract base class for vision model implementations that extract receipt fields."""

    @abc.abstractmethod
    def extract(self, content: bytes, mime_type: str) -> ExtractedReceipt:
        """Extract structured fields from one receipt or invoice.

        Args:
            content: Raw file bytes (an image or a PDF).
            mime_type: The file's type; must be one of SUPPORTED_MIME_TYPES.

        Returns:
            ExtractedReceipt: Validated fields; anything unreadable is None.

        Raises:
            ValueError: If mime_type is not in SUPPORTED_MIME_TYPES.
            ExtractionError: If the model call fails or its output is invalid.
        """
        pass
