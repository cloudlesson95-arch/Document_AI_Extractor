import math
import uuid
from typing import Annotated, Any

from fastapi import Body, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import Field, ValidationError

from .config import APP_REVISION, CLOUD_PROVIDER, CORS_ALLOW_ORIGINS, MAX_UPLOAD_MB, UPLOAD_RATE_LIMIT_PER_MINUTE
from .extraction.base import SUPPORTED_MIME_TYPES, ExtractionError, detect_mime_type
from .extraction.schema import ExtractedReceipt
from .logging_config import setup_logging
from .providers import get_file_storage, get_record_store, get_vision_extractor
from .records.base import ReceiptRecord, RecordFilters, apply_update
from .utils.rate_limit import RateLimiter

logger = setup_logging(__name__)

MAX_UPLOAD_BYTES = int(MAX_UPLOAD_MB * 1024 * 1024)
# Fields a correction may change; `corrected` is set by the API, never by the client
EDITABLE_FIELDS = frozenset(ExtractedReceipt.model_fields)

upload_limiter = RateLimiter(UPLOAD_RATE_LIMIT_PER_MINUTE)

app = FastAPI(
    title="Document AI Extractor API",
    description="Upload receipts/invoices, extract structured fields, review and correct them",
    version="0.1.0",
)


# Added before CORSMiddleware, so it runs inside it. Without it, an unexpected exception becomes a 500 from
# Starlette's outermost error handler, which has no CORS headers, and the browser only reports a "CORS error".
@app.middleware("http")
async def answer_unexpected_errors_as_json(request: Request, call_next):
    try:
        return await call_next(request)
    except NotImplementedError as e:  # a CLOUD_PROVIDER whose implementations arrive in a later phase
        logger.error(f"[API] {request.method} {request.url.path}: {e}")
        return JSONResponse({"detail": str(e)}, status_code=503)
    except Exception:
        logger.exception(f"[API] {request.method} {request.url.path} failed")
        return JSONResponse({"detail": "Internal server error"}, status_code=500)


# The web frontend calls the API from the browser, from another origin. Retry-After is exposed so the frontend
# can say when to try again after a 429. Content-Type is always allowed, so JSON and multipart requests need no list.
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOW_ORIGINS,
    allow_methods=["GET", "POST", "PATCH"],
    expose_headers=["Retry-After"],
)

logger.info(f"[API] Initialized (CLOUD_PROVIDER={CLOUD_PROVIDER}, CORS_ALLOW_ORIGINS={CORS_ALLOW_ORIGINS})")


class ReceiptResponse(ReceiptRecord):
    """A stored receipt as the API returns it. Amounts are JSON strings such as "9.20", so they stay exact."""

    file_url: str = Field(description="Path of the original upload, relative to the API's base URL")


def _response(record: ReceiptRecord) -> ReceiptResponse:
    return ReceiptResponse(**record.model_dump(), file_url=f"/receipts/{record.id}/file")


def _get_record(record_id: str) -> ReceiptRecord:
    record = get_record_store().get(record_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Receipt not found")
    return record


@app.get("/health")
def health_check():
    return {"status": "ok", "cloud_provider": CLOUD_PROVIDER, "revision": APP_REVISION or None}


@app.post("/receipts", response_model=ReceiptResponse, status_code=201)
def create_receipt(file: Annotated[UploadFile, File(description="A JPEG, PNG, WebP or PDF receipt or invoice")]):
    """Extract the fields of an uploaded receipt or invoice, then store the file and the record.

    Nothing is stored when the answer is 413 (over MAX_UPLOAD_MB), 415 (unsupported type), 429 (over the
    upload rate limit; see Retry-After) or 502 (the model's extraction failed).
    """
    content = file.file.read(MAX_UPLOAD_BYTES + 1)  # one byte over the cap is enough to refuse it
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=f"The file is larger than {MAX_UPLOAD_MB:g} MB")
    mime_type = detect_mime_type(content)  # from the bytes: the file name and browser-sent type can lie
    if mime_type is None:
        raise HTTPException(status_code=415, detail="Unsupported file type: upload a JPEG, PNG, WebP or PDF")

    # After the cheap checks, so only uploads that reach the model use up the limit
    retry_after = upload_limiter.acquire()
    if retry_after:
        raise HTTPException(status_code=429, detail="Too many uploads, try again shortly",
                            headers={"Retry-After": str(math.ceil(retry_after))})

    # Extract before storing anything, so a failed extraction leaves no orphaned file
    try:
        receipt = get_vision_extractor().extract(content, mime_type)
    except ExtractionError as e:
        logger.warning(f"[API] Extraction failed ({mime_type}, {len(content) / 1024:.0f} KB): {e}")
        raise HTTPException(status_code=502, detail="The model couldn't read this document. "
                                                    "Try again, or upload a sharper image.")

    record_id = uuid.uuid4().hex
    file_key = get_file_storage().upload(f"receipts/{record_id}.{mime_type.split('/')[1]}", content)
    record = ReceiptRecord(**receipt.model_dump(), id=record_id, file_key=file_key, mime_type=mime_type)
    get_record_store().put(record)
    logger.info(f"[API] Stored receipt {record_id} ({mime_type}, {len(content) / 1024:.0f} KB)")
    return _response(record)


@app.get("/receipts", response_model=list[ReceiptResponse])
def list_receipts(filters: Annotated[RecordFilters, Query()]):
    """Receipts matching every given filter, newest first.

    Bounds are inclusive, and vendor_contains is a case-insensitive substring. A receipt whose vendor, date
    or total is unknown never matches a filter on that field.
    """
    return [_response(record) for record in get_record_store().search(filters)]


@app.get("/receipts/{record_id}", response_model=ReceiptResponse)
def get_receipt(record_id: str):
    """One receipt; file_url serves its original upload, for the review page to show side by side."""
    return _response(_get_record(record_id))


@app.get(
    "/receipts/{record_id}/file",
    response_class=Response,
    responses={200: {"description": "The original upload",
                     "content": {mime_type: {} for mime_type in sorted(SUPPORTED_MIME_TYPES)}}},
)
def get_receipt_file(record_id: str):
    """The original upload, with its stored type.

    The API serves it for every provider instead of handing out presigned URLs; uploads are capped at
    MAX_UPLOAD_MB, so the response also fits Lambda's 6 MB limit.
    """
    record = _get_record(record_id)
    try:
        content = get_file_storage().download(record.file_key)
    except FileNotFoundError:
        logger.error(f"[API] Receipt {record_id} has no stored file at {record.file_key!r}")
        raise HTTPException(status_code=404, detail="The original file of this receipt is missing")
    # nosniff: browsers must keep the stored type, so an upload is never run as HTML or script
    return Response(content, media_type=record.mime_type, headers={"X-Content-Type-Options": "nosniff"})


@app.patch("/receipts/{record_id}", response_model=ReceiptResponse)
def correct_receipt(
    record_id: str,
    fields: Annotated[dict[str, Any], Body(
        description=f"New values for some of: {', '.join(sorted(EDITABLE_FIELDS))}",
        examples=[{"vendor": "Cafe Uno", "total_amount": "9.20"}],
    )],
):
    """Correct some extracted fields; fields left out keep their values.

    The receipt is marked as corrected only if a value actually changes, so `corrected` counts the receipts
    the model got wrong, not the ones that were merely reviewed.
    """
    not_editable = set(fields) - EDITABLE_FIELDS
    if not_editable:
        raise HTTPException(status_code=422, detail=f"These fields can't be edited: {sorted(not_editable)}")
    record = _get_record(record_id)
    try:
        candidate = apply_update(record, fields)  # validates the new values without saving them
    except ValidationError as e:
        # The shape of FastAPI's own 422s, so the frontend can match each error to its form field
        errors = e.errors(include_url=False, include_context=False, include_input=False)
        raise HTTPException(status_code=422, detail=[{**error, "loc": ["body", *error["loc"]]} for error in errors])

    changed = sorted(name for name in fields if getattr(candidate, name) != getattr(record, name))
    if not changed:
        return _response(record)
    updated = get_record_store().update(record_id, {**fields, "corrected": True})
    logger.info(f"[API] Receipt {record_id} corrected: {changed}")
    return _response(updated)
