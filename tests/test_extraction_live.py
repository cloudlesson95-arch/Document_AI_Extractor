import datetime
import os
from decimal import Decimal

import pytest

from backend.extraction.direct_api import GeminiVisionExtractor

# Calls the real Gemini API (needs GOOGLE_API_KEY and uses quota), so it only runs when asked:
#   $env:RUN_LIVE_TESTS="1"; python -m pytest tests/test_extraction_live.py -v
pytestmark = pytest.mark.skipif(os.getenv("RUN_LIVE_TESTS") != "1", reason="set RUN_LIVE_TESTS=1 to call the real Gemini API")

# A synthetic receipt (no real business or personal data) with a comma decimal separator,
# a day-first date and a discount line -- the formats the prompt has to normalize
RECEIPT_LINES = [
    "CAFE UNO",
    "Rua do Porto 12, 1100-001 Lisboa",
    "NIF 500000000",
    "",
    "Data: 14/09/2026  10:42",
    "",
    "2 x Latte            3,75     7,50",
    "1 x Croissant        2,20     2,20",
    "Desconto cartao              -0,50",
    "",
    "TOTAL EUR                     9,20",
    "IVA 23% incluido              1,72",
    "Pago: Cartao",
]


def make_receipt_pdf(lines: list[str]) -> bytes:
    """Build a one-page PDF showing the given text lines in Courier. No dependencies."""
    assert not any(char in line for line in lines for char in "()\\"), "lines must not contain ( ) or \\"
    stream = ("BT /F1 11 Tf 14 TL 60 740 Td " + " ".join(f"({line}) Tj T*" for line in lines) + " ET").encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 420 800] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>",
        b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream),
    ]
    pdf = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf += b"%d 0 obj\n%s\nendobj\n" % (number, body)
    xref_at = len(pdf)
    pdf += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    pdf += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    pdf += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref_at)
    return bytes(pdf)


def test_gemini_extracts_synthetic_receipt():
    receipt = GeminiVisionExtractor().extract(make_receipt_pdf(RECEIPT_LINES), "application/pdf")

    assert receipt.vendor.lower() == "cafe uno"
    assert receipt.date == datetime.date(2026, 9, 14)   # printed as 14/09/2026
    assert receipt.total_amount == Decimal("9.20")      # printed as 9,20
    assert receipt.currency == "EUR"
    assert [(item.description.lower(), item.quantity, item.unit_price) for item in receipt.line_items] == [
        ("latte", 2, Decimal("3.75")),
        ("croissant", 1, Decimal("2.20")),
        ("desconto cartao", 1, Decimal("-0.50")),        # a discount line becomes a negative item
    ]
