import datetime
import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import backend.providers as providers
from backend import api
from backend.extraction.base import ExtractionError
from backend.records.base import ReceiptRecord
from backend.utils.rate_limit import RateLimiter

REPO_ROOT = Path(__file__).resolve().parent.parent

# The smallest files detect_mime_type() recognizes, one per supported type
FILES = {
    "image/jpeg": b"\xff\xd8\xff\xe0 jpeg body",
    "image/png": b"\x89PNG\r\n\x1a\n png body",
    "image/webp": b"RIFF\x10\x00\x00\x00WEBPVP8  webp body",
    "application/pdf": b"%PDF-1.7\n pdf body",
}
PNG = FILES["image/png"]


def upload(client: TestClient, content: bytes = PNG):
    # The name and the browser-sent type always say PNG: the API must go by the bytes
    return client.post("/receipts", files={"file": ("receipt.png", content, "image/png")})


def test_health_reports_the_provider_and_the_deployed_revision(monkeypatch):
    monkeypatch.setattr(api, "APP_REVISION", "abc1234")

    response = TestClient(api.app).get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "cloud_provider": api.CLOUD_PROVIDER, "revision": "abc1234"}


def test_health_reports_no_revision_when_none_is_deployed(monkeypatch):
    monkeypatch.setattr(api, "APP_REVISION", "")

    assert TestClient(api.app).get("/health").json()["revision"] is None


def test_api_docs_describe_amounts_as_the_strings_the_responses_carry(client):
    schemas = client.get("/openapi.json").json()["components"]["schemas"]

    types = {option.get("type") for option in schemas["ReceiptResponse"]["properties"]["total_amount"]["anyOf"]}

    assert "string" in types and "number" not in types


def test_upload_extracts_stores_and_returns_the_receipt(client, fake_extractor):
    response = upload(client)

    assert response.status_code == 201
    receipt = response.json()
    assert receipt["vendor"] == "Cafe Uno"
    assert receipt["total_amount"] == "9.20"  # Decimals travel as strings, so they stay exact
    assert receipt["corrected"] is False
    assert receipt["file_key"] == f"receipts/{receipt['id']}.png"
    assert receipt["file_url"] == f"/receipts/{receipt['id']}/file"
    assert fake_extractor.calls == [(PNG, "image/png")]
    assert client.get(f"/receipts/{receipt['id']}").json() == receipt


def test_upload_stores_the_category_suggested_for_the_extracted_fields(client, fake_categorizer):
    receipt = upload(client).json()

    assert (receipt["category"], receipt["category_corrected"]) == ("Meals", False)
    assert [call.vendor for call in fake_categorizer.calls] == ["Cafe Uno"]
    assert client.get(f"/receipts/{receipt['id']}").json()["category"] == "Meals"


def test_an_upload_without_a_likely_category_is_stored_uncategorized(client, fake_categorizer):
    fake_categorizer.category = None

    assert upload(client).json()["category"] is None


def test_a_failing_categorizer_does_not_lose_the_upload(client, fake_categorizer):
    fake_categorizer.error = FileNotFoundError("training_data.csv")

    response = upload(client)

    assert response.status_code == 201
    assert response.json()["category"] is None
    assert [receipt["id"] for receipt in client.get("/receipts").json()] == [response.json()["id"]]


def test_the_api_starts_without_loading_scikit_learn(tmp_path):
    # Fresh interpreter, since other tests load it. On Lambda, only the first upload should pay its ~1 s import.
    code = (
        "import sys\nfrom fastapi.testclient import TestClient\nfrom backend.api import app\n"
        "assert TestClient(app).get('/health').status_code == 200\nprint('sklearn' in sys.modules)"
    )
    env = {**os.environ, "CLOUD_PROVIDER": "local", "LOG_TO_FILE": "false", "LOG_TO_CONSOLE": "false"}

    result = subprocess.run([sys.executable, "-c", code], cwd=REPO_ROOT, env=env, capture_output=True, text=True, check=True)

    assert result.stdout.strip() == "False"


@pytest.mark.parametrize("mime_type", sorted(FILES))
def test_the_original_is_served_back_with_the_type_read_from_its_bytes(client, mime_type):
    receipt = upload(client, FILES[mime_type]).json()

    response = client.get(receipt["file_url"])

    assert receipt["mime_type"] == mime_type
    assert response.status_code == 200
    assert response.content == FILES[mime_type]
    assert response.headers["content-type"] == mime_type
    assert response.headers["x-content-type-options"] == "nosniff"


@pytest.mark.parametrize("bytes_over_the_cap, status", [(0, 201), (1, 413)])
def test_uploads_over_the_size_cap_are_refused_before_extraction(client, fake_extractor, monkeypatch,
                                                                 bytes_over_the_cap, status):
    monkeypatch.setattr(api, "MAX_UPLOAD_BYTES", 100)
    content = PNG.ljust(100 + bytes_over_the_cap, b"x")

    assert upload(client, content).status_code == status
    assert len(fake_extractor.calls) == (1 if status == 201 else 0)


def test_unsupported_file_types_are_refused_with_415(client, fake_extractor):
    response = upload(client, b"GIF89a gif body")

    assert response.status_code == 415
    assert fake_extractor.calls == []


def test_a_failed_extraction_answers_502_and_stores_nothing(client, fake_extractor, tmp_path):
    fake_extractor.error = ExtractionError("Gemini output failed validation")

    response = upload(client)

    assert response.status_code == 502
    assert "Gemini" not in response.json()["detail"]  # the model's error stays in the server log
    assert client.get("/receipts").json() == []
    assert not (tmp_path / "uploads").exists()


def test_uploads_over_the_rate_limit_get_429_with_retry_after(client, fake_extractor, monkeypatch):
    monkeypatch.setattr(api, "upload_limiter", RateLimiter(max_calls=1))
    assert upload(client).status_code == 201

    response = upload(client)

    assert response.status_code == 429
    assert response.headers["retry-after"] == "60"
    assert len(fake_extractor.calls) == 1


def test_refused_uploads_dont_use_up_the_rate_limit(client, monkeypatch):
    monkeypatch.setattr(api, "upload_limiter", RateLimiter(max_calls=1))

    assert upload(client, b"not a receipt").status_code == 415
    assert upload(client).status_code == 201


def at_utc(hour: int, minute: int, second: int) -> datetime.datetime:
    return datetime.datetime(2026, 10, 10, hour, minute, second, tzinfo=datetime.timezone.utc)


def test_uploads_over_the_daily_limit_get_429_until_utc_midnight(client, fake_extractor, monkeypatch):
    monkeypatch.setattr(providers, "UPLOAD_DAILY_LIMIT", 2)
    monkeypatch.setattr(api, "_utc_now", lambda: at_utc(14, 59, 59))
    assert [upload(client).status_code for _ in range(2)] == [201, 201]

    response = upload(client)

    assert response.status_code == 429
    assert response.headers["retry-after"] == str(9 * 3600 + 1)
    assert "limit of 2 uploads" in response.json()["detail"]
    assert len(fake_extractor.calls) == 2
    assert len(client.get("/receipts").json()) == 2
    # The next UTC day starts a new count
    monkeypatch.setattr(api, "_utc_now", lambda: at_utc(14, 59, 59) + datetime.timedelta(hours=10))
    assert upload(client).status_code == 201


def test_the_daily_limit_counts_only_uploads_that_reach_the_model(client, fake_extractor, monkeypatch):
    monkeypatch.setattr(providers, "UPLOAD_DAILY_LIMIT", 1)

    assert upload(client, b"not a receipt").status_code == 415  # refused before the model: not counted
    fake_extractor.error = ExtractionError("unreadable")
    assert upload(client).status_code == 502  # the model was called: counted
    fake_extractor.error = None
    response = upload(client)
    assert response.status_code == 429 and "Today's limit" in response.json()["detail"]


@pytest.fixture
def three_receipts(client):
    """Stored on consecutive days: Cafe Uno (Meals), then Pingo Doce (Groceries), then Cafe Dos (uncategorized)."""
    store = providers.get_record_store()
    for day, (vendor, date, total, category) in enumerate(
        [("Cafe Uno", "2026-09-01", "5.00", "Meals"), ("Pingo Doce", "2026-09-14", "42.10", "Groceries"),
         ("Cafe Dos", "2026-09-30", "12.00", None)],
        start=1,
    ):
        store.put(ReceiptRecord(
            vendor=vendor, date=date, total_amount=total, currency="EUR", line_items=[], category=category,
            file_key="receipts/x.png", mime_type="image/png",
            created_at=datetime.datetime(2026, 10, day, tzinfo=datetime.timezone.utc),
        ))


@pytest.mark.parametrize("query, expected", [
    ("", ["Cafe Dos", "Pingo Doce", "Cafe Uno"]),
    ("vendor_contains=CAFE", ["Cafe Dos", "Cafe Uno"]),
    ("date_from=2026-09-14", ["Cafe Dos", "Pingo Doce"]),
    ("date_to=2026-09-14", ["Pingo Doce", "Cafe Uno"]),
    ("min_total=12", ["Cafe Dos", "Pingo Doce"]),
    ("max_total=12.00", ["Cafe Dos", "Cafe Uno"]),
    ("vendor_contains=cafe&date_from=2026-09-02&max_total=20", ["Cafe Dos"]),
    ("category=Meals", ["Cafe Uno"]),
    ("category=Groceries&min_total=40", ["Pingo Doce"]),
    ("category=Software+%26+Subscriptions", []),
])
def test_list_filters_by_the_query_parameters_newest_first(client, three_receipts, query, expected):
    response = client.get(f"/receipts?{query}")

    assert response.status_code == 200
    assert [receipt["vendor"] for receipt in response.json()] == expected


@pytest.mark.parametrize("query", ["date_from=yesterday", "min_total=ten", "category=Food"])
def test_invalid_filters_are_refused_with_422(client, query):
    assert client.get(f"/receipts?{query}").status_code == 422


@pytest.mark.parametrize("method, path", [("GET", "/receipts/nope"), ("GET", "/receipts/nope/file"),
                                          ("PATCH", "/receipts/nope")])
def test_unknown_receipts_answer_404(client, method, path):
    assert client.request(method, path, json={"vendor": "Other"}).status_code == 404


def test_a_receipt_whose_file_is_missing_answers_404_for_the_file_only(client, fake_extractor):
    record = ReceiptRecord(**fake_extractor.receipt.model_dump(), file_key="receipts/gone.png", mime_type="image/png")
    providers.get_record_store().put(record)

    assert client.get(f"/receipts/{record.id}").status_code == 200
    assert client.get(f"/receipts/{record.id}/file").status_code == 404


def test_a_correction_changes_only_the_given_fields_and_marks_the_receipt_corrected(client):
    original = upload(client).json()

    response = client.patch(f"/receipts/{original['id']}", json={"vendor": "Café Uno", "total_amount": "9.50"})

    assert response.status_code == 200
    corrected = response.json()
    assert (corrected["vendor"], corrected["total_amount"], corrected["corrected"]) == ("Café Uno", "9.50", True)
    assert corrected["updated_at"] > original["updated_at"]
    untouched = original.keys() - {"vendor", "total_amount", "corrected", "updated_at"}
    assert {key: corrected[key] for key in untouched} == {key: original[key] for key in untouched}
    assert client.get(f"/receipts/{original['id']}").json() == corrected


@pytest.mark.parametrize("category", ["Groceries", None])
def test_a_category_change_marks_the_category_not_the_extraction_as_corrected(client, category):
    original = upload(client).json()

    corrected = client.patch(f"/receipts/{original['id']}", json={"category": category}).json()

    assert (corrected["category"], corrected["category_corrected"], corrected["corrected"]) == (category, True, False)
    assert corrected["updated_at"] > original["updated_at"]
    assert client.get(f"/receipts/{original['id']}").json() == corrected


def test_changing_a_field_and_the_category_marks_both(client):
    original = upload(client).json()

    corrected = client.patch(f"/receipts/{original['id']}", json={"vendor": "Cafe Uno Lisboa", "category": "Travel"}).json()

    assert (corrected["corrected"], corrected["category_corrected"]) == (True, True)


@pytest.mark.parametrize("fields", [{}, {"vendor": "Cafe Uno"}, {"total_amount": 9.2, "date": "2026-09-14"},
                                    {"category": "Meals"}])
def test_saving_unchanged_values_is_not_a_correction(client, fields):
    original = upload(client).json()

    response = client.patch(f"/receipts/{original['id']}", json=fields)

    assert response.status_code == 200
    assert response.json() == original  # still uncorrected, and not even updated_at moved


@pytest.mark.parametrize("field", ["id", "file_key", "mime_type", "corrected", "category_corrected", "created_at",
                                   "unknown"])
def test_a_correction_cannot_touch_anything_but_the_editable_fields(client, field):
    original = upload(client).json()

    response = client.patch(f"/receipts/{original['id']}", json={"vendor": "Other", field: "x"})

    assert response.status_code == 422
    assert field in response.json()["detail"]
    assert client.get(f"/receipts/{original['id']}").json() == original


@pytest.mark.parametrize("fields", [
    {"currency": "usd"},
    {"total_amount": "-1"},
    {"date": "2026-02-30"},
    {"line_items": [{"description": "Latte", "quantity": 0, "unit_price": "3.75"}]},
    {"category": "Food"},
], ids=lambda fields: next(iter(fields)))
def test_invalid_corrections_are_refused_with_422_and_change_nothing(client, fields):
    original = upload(client).json()

    response = client.patch(f"/receipts/{original['id']}", json=fields)

    assert response.status_code == 422
    assert [error["loc"][:2] for error in response.json()["detail"]] == [["body", next(iter(fields))]]
    assert client.get(f"/receipts/{original['id']}").json() == original


def test_a_correction_must_be_a_json_object(client):
    original = upload(client).json()

    assert client.patch(f"/receipts/{original['id']}", json=["vendor"]).status_code == 422
