from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import CLOUD_PROVIDER, CORS_ORIGINS
from .logging_config import setup_logging

logger = setup_logging(__name__)

app = FastAPI(
    title="Document AI Extractor API",
    description="Upload receipts/invoices, extract structured fields, review and correct them",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["*"],
)

logger.info(f"[API] Initialized (CLOUD_PROVIDER={CLOUD_PROVIDER}, CORS_ORIGINS={CORS_ORIGINS})")


@app.get("/health")
def health_check():
    return {"status": "ok", "cloud_provider": CLOUD_PROVIDER}
