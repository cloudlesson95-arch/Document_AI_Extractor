import datetime
import json
from decimal import Decimal

import pytest
from pydantic import ValidationError

from backend.extraction.schema import ExtractedReceipt

VALID = {
    "vendor": "Cafe Uno",
    "date": "2026-09-28",
    "total_amount": 7.4,
    "currency": "EUR",
    "line_items": [
        {"description": "Latte", "quantity": 2, "unit_price": 3.75},
        {"description": "Coupon", "quantity": 1, "unit_price": -0.10},
    ],
}

# JSON Schema keywords Gemini's response_json_schema supports (google-genai GenerateContentConfig docs)
GEMINI_SCHEMA_KEYWORDS = {
    "$id", "$defs", "$ref", "$anchor", "type", "format", "title", "description", "enum",
    "items", "prefixItems", "minItems", "maxItems", "minimum", "maximum", "anyOf", "oneOf",
    "properties", "additionalProperties", "required", "propertyOrdering",
}


def parse(data: dict) -> ExtractedReceipt:
    return ExtractedReceipt.model_validate_json(json.dumps(data))


def test_valid_receipt_parses_amounts_as_exact_decimals():
    receipt = parse(VALID)
    assert receipt.total_amount == Decimal("7.4")
    assert receipt.date == datetime.date(2026, 9, 28)
    assert receipt.line_items[0].quantity == Decimal("2")
    assert receipt.line_items[1].unit_price == Decimal("-0.1")  # discounts are negative


def test_unreadable_fields_can_be_null():
    receipt = parse({"vendor": None, "date": None, "total_amount": None, "currency": None, "line_items": []})
    assert receipt.vendor is None
    assert receipt.line_items == []


@pytest.mark.parametrize("field", list(VALID))
def test_every_field_is_required(field):
    # The model must output every key, even when the value is null
    with pytest.raises(ValidationError):
        parse({k: v for k, v in VALID.items() if k != field})


@pytest.mark.parametrize("currency", ["eur", "€", "EURO", "E"])
def test_currency_must_be_iso_4217(currency):
    with pytest.raises(ValidationError):
        parse({**VALID, "currency": currency})


@pytest.mark.parametrize("field, value", [
    ("total_amount", -1),
    ("total_amount", "7,40"),
    ("date", "28/09/2026"),
])
def test_impossible_values_are_rejected(field, value):
    with pytest.raises(ValidationError):
        parse({**VALID, field: value})


def test_line_item_quantity_must_be_positive():
    item = {"description": "Latte", "quantity": 0, "unit_price": 3.75}
    with pytest.raises(ValidationError):
        parse({**VALID, "line_items": [item]})


def test_json_schema_only_uses_keywords_gemini_supports():
    used = set()

    def collect(node, is_name_map=False):
        # Keys under "properties" and "$defs" are field/model names, not keywords
        if isinstance(node, dict):
            for key, value in node.items():
                if not is_name_map:
                    used.add(key)
                collect(value, is_name_map=key in ("properties", "$defs") and not is_name_map)
        elif isinstance(node, list):
            for item in node:
                collect(item)

    collect(ExtractedReceipt.model_json_schema())
    assert used <= GEMINI_SCHEMA_KEYWORDS, f"unsupported keywords: {used - GEMINI_SCHEMA_KEYWORDS}"
