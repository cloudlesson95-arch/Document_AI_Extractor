import json
from unittest.mock import MagicMock

import httpx
import pytest
from google.genai import errors as genai_errors
from google.genai import types

from backend.extraction.base import ExtractionError
from backend.extraction.direct_api import GeminiVisionExtractor
from backend.extraction.schema import ExtractedReceipt

VALID_JSON = json.dumps({
    "vendor": "Cafe Uno",
    "date": "2026-09-14",
    "total_amount": 9.2,
    "currency": "EUR",
    "line_items": [{"description": "Latte", "quantity": 2, "unit_price": 3.75}],
})
PDF = b"%PDF-1.4 fake"


def gemini_response(text: str | None, finish_reason=types.FinishReason.STOP, block_reason=None):
    """Build a real SDK response object, shaped the way Gemini returns it."""
    candidates = None if text is None else [
        types.Candidate(content=types.Content(role="model", parts=[types.Part(text=text)]), finish_reason=finish_reason)
    ]
    feedback = types.GenerateContentResponsePromptFeedback(block_reason=block_reason) if block_reason else None
    return types.GenerateContentResponse(candidates=candidates, prompt_feedback=feedback)


def make_extractor(response=None, error=None):
    """An extractor with a fake Gemini client, so no network call or API key is needed."""
    client = MagicMock()
    client.models.generate_content.return_value = response
    client.models.generate_content.side_effect = error
    return GeminiVisionExtractor(client=client, model="test-model"), client


def test_valid_output_becomes_extracted_receipt():
    extractor, client = make_extractor(gemini_response(VALID_JSON))

    receipt = extractor.extract(PDF, "application/pdf")

    assert receipt.vendor == "Cafe Uno"
    call = client.models.generate_content.call_args.kwargs
    assert call["model"] == "test-model"
    assert call["contents"][0].inline_data.mime_type == "application/pdf"
    assert call["config"].response_mime_type == "application/json"
    assert call["config"].response_json_schema == ExtractedReceipt.model_json_schema()
    assert call["config"].temperature == 0


def test_unsupported_type_is_rejected_before_calling_gemini():
    extractor, client = make_extractor(gemini_response(VALID_JSON))

    with pytest.raises(ValueError, match="Unsupported file type"):
        extractor.extract(b"GIF89a", "image/gif")
    client.models.generate_content.assert_not_called()


@pytest.mark.parametrize("response, message", [
    (gemini_response(VALID_JSON.replace('"EUR"', '"\\u20ac"')), "failed validation"),
    (gemini_response('{"vendor": "Cafe', finish_reason=types.FinishReason.MAX_TOKENS), "MAX_TOKENS"),
    (gemini_response(None, block_reason=types.BlockedReason.PROHIBITED_CONTENT), "blocked: PROHIBITED_CONTENT"),
])
def test_bad_output_raises_extraction_error(response, message):
    extractor, _ = make_extractor(response)

    with pytest.raises(ExtractionError, match=message):
        extractor.extract(PDF, "application/pdf")


@pytest.mark.parametrize("error", [
    genai_errors.ServerError(503, {"error": {"code": 503, "message": "The model is overloaded.", "status": "UNAVAILABLE"}}),
    httpx.ConnectTimeout("timed out"),
])
def test_failed_call_raises_extraction_error(error):
    extractor, _ = make_extractor(error=error)

    with pytest.raises(ExtractionError, match="Gemini call failed"):
        extractor.extract(PDF, "application/pdf")


def test_missing_api_key_fails_at_startup(monkeypatch):
    monkeypatch.setattr("backend.extraction.direct_api.get_secret", lambda name: None)

    with pytest.raises(RuntimeError, match="GOOGLE_API_KEY"):
        GeminiVisionExtractor(model="test-model")
