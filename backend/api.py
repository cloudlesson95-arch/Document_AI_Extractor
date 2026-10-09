from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import APP_REVISION, CLOUD_PROVIDER, CORS_ALLOW_ORIGINS
from .logging_config import setup_logging

logger = setup_logging(__name__)

app = FastAPI(
    title="Document AI Extractor API",
    description="Upload receipts/invoices, extract structured fields, review and correct them",
    version="0.1.0",
)

# The web frontend calls the API from the browser, from another origin. Retry-After is exposed so the frontend
# can say when to try again after a 429. Content-Type is always allowed, so JSON and multipart requests need no list.
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOW_ORIGINS,
    allow_methods=["GET", "POST", "PATCH"],
    expose_headers=["Retry-After"],
)

logger.info(f"[API] Initialized (CLOUD_PROVIDER={CLOUD_PROVIDER}, CORS_ALLOW_ORIGINS={CORS_ALLOW_ORIGINS})")


@app.get("/health")
def health_check():
    return {"status": "ok", "cloud_provider": CLOUD_PROVIDER, "revision": APP_REVISION or None}
