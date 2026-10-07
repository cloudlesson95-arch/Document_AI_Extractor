import time

import httpx
from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from pydantic import ValidationError

from ..config import EXTRACTION_TIMEOUT_SECONDS
from ..logging_config import setup_logging
from ..secrets import get_secret
from ..utils.model_resolver import get_model
from .base import SUPPORTED_MIME_TYPES, ExtractionError, VisionExtractor
from .schema import ExtractedReceipt

logger = setup_logging(__name__)

# The schema's field descriptions are sent too; this prompt adds the rules a schema can't express
SYSTEM_PROMPT = """You extract data from one receipt or invoice (a photo, scan or PDF) and reply with JSON matching the given schema.

Rules:
- Use only what is printed on the document. If a value is missing, illegible or ambiguous, use null; never guess.
- date: the purchase or invoice date as YYYY-MM-DD. Read day/month order from the vendor's country or language; if it's still ambiguous, use null.
- Amounts are plain numbers with "." as the decimal point: no currency symbols or thousands separators.
- total_amount: the final amount paid, after discounts and including tax and tip.
- currency: the ISO 4217 code, inferred from the printed code, symbol or the vendor's country. A bare "$" with no other clue is null.
- line_items: one entry per purchased item, in printed order. Leave out subtotal, tax, tip, total, payment and change lines. A discount printed on its own line is an item with a negative unit_price. If only a line total is printed, quantity is 1 and unit_price is that total."""


class GeminiVisionExtractor(VisionExtractor):
    """Extracts receipt fields by calling the Gemini API directly (the `local` provider)."""

    def __init__(self, client: genai.Client | None = None, model: str | None = None):
        """Create the extractor.

        Args:
            client: Gemini client; built from GOOGLE_API_KEY if omitted (tests pass a fake).
            model: Model ID; resolved with get_model("gemini") if omitted.
        """
        self.model = model or get_model("gemini")
        self._client = client or self._create_client()
        self._config = types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_json_schema=ExtractedReceipt.model_json_schema(),
            temperature=0,
            # No tools are used; this also skips the SDK's function-calling wrapper and its warning
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )

    @staticmethod
    def _create_client() -> genai.Client:
        api_key = get_secret("GOOGLE_API_KEY")
        if not api_key:
            raise RuntimeError("[Extractor] GOOGLE_API_KEY not found in the secret backend or environment.")
        return genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(
                timeout=EXTRACTION_TIMEOUT_SECONDS * 1000,  # milliseconds
                retry_options=types.HttpRetryOptions(attempts=3),  # retries 408, 429, 5xx and network timeouts
            ),
        )

    def extract(self, content: bytes, mime_type: str) -> ExtractedReceipt:
        if mime_type not in SUPPORTED_MIME_TYPES:
            raise ValueError(f"Unsupported file type '{mime_type}'; expected one of {sorted(SUPPORTED_MIME_TYPES)}")

        started = time.perf_counter()
        try:
            response = self._client.models.generate_content(
                model=self.model,
                contents=[types.Part.from_bytes(data=content, mime_type=mime_type), "Extract the fields from this document."],
                config=self._config,
            )
        except (genai_errors.APIError, httpx.HTTPError) as e:
            raise ExtractionError(f"Gemini call failed: {e}") from e

        # Validate the text ourselves: the SDK's response.parsed turns validation errors into None
        text = response.text
        if not text:
            raise ExtractionError(f"Gemini returned no output ({_stop_reason(response)})")
        try:
            receipt = ExtractedReceipt.model_validate_json(text)
        except ValidationError as e:
            raise ExtractionError(f"Gemini output failed validation ({_stop_reason(response)}): {e}") from e

        logger.info(
            f"[Extractor] {self.model} extracted {len(receipt.line_items)} line items "
            f"from {mime_type} ({len(content) / 1024:.0f} KB) in {time.perf_counter() - started:.1f}s"
        )
        return receipt


def _stop_reason(response: types.GenerateContentResponse) -> str:
    """Describe why the model stopped, e.g. 'finish reason: MAX_TOKENS' or 'blocked: SAFETY'."""
    if response.prompt_feedback and response.prompt_feedback.block_reason:
        return f"blocked: {response.prompt_feedback.block_reason.name}"
    if response.candidates and response.candidates[0].finish_reason:
        return f"finish reason: {response.candidates[0].finish_reason.name}"
    return "no candidates"
