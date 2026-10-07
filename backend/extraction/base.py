import abc
from .schema import ExtractedReceipt

# File types every VisionExtractor accepts, so an upload behaves the same on every provider
SUPPORTED_MIME_TYPES = frozenset({"image/jpeg", "image/png", "image/webp", "application/pdf"})


def detect_mime_type(content: bytes) -> str | None:
    """Identify a supported file type from its first bytes; file names and browser-sent types can lie.

    Args:
        content: Raw file bytes.

    Returns:
        str | None: One of SUPPORTED_MIME_TYPES, or None if the file isn't one of them.
    """
    if content.startswith(b"%PDF-"):
        return "application/pdf"
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "image/webp"
    return None


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
