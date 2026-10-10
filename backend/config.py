import os
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()

# Project root -- anchor for every local path so nothing depends on the current working directory
BASE_DIR = Path(__file__).resolve().parent.parent

# Cloud provider switch: selects the FileStorage / RecordStore / VisionExtractor implementations
CLOUD_PROVIDER = os.getenv("CLOUD_PROVIDER", "local").lower()  # "local", "aws", "azure"
if CLOUD_PROVIDER not in ("local", "aws", "azure"):
    raise ValueError(f"CLOUD_PROVIDER must be 'local', 'aws' or 'azure', got '{CLOUD_PROVIDER}'")

# Browser origins allowed to call the API (the web frontend), separated by spaces: the Lambda "Variables={...}"
# shorthand splits on commas. Empty allows none. Trailing slashes are dropped (browsers send none).
CORS_ALLOW_ORIGINS = [origin.rstrip("/") for origin in os.getenv("CORS_ALLOW_ORIGINS", "http://localhost:3000").split()]
if any("," in origin for origin in CORS_ALLOW_ORIGINS):
    raise ValueError(f"CORS_ALLOW_ORIGINS must be separated by spaces, not commas, got {CORS_ALLOW_ORIGINS}")

# Git SHA of the deployed build (set by the deployment; empty locally), shown in /health
APP_REVISION = os.getenv("APP_REVISION", "")

# Logging configuration
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")  # DEBUG, INFO, WARNING, ERROR, CRITICAL
LOG_TO_CONSOLE = os.getenv("LOG_TO_CONSOLE", "true").lower() in ("1", "true", "yes")
LOG_TO_FILE = os.getenv("LOG_TO_FILE", "true").lower() in ("1", "true", "yes")
LOG_FILE_PATH = os.getenv("LOG_FILE_PATH", str(BASE_DIR / "logs" / "app.log"))
LOG_FORMAT = '%(asctime)s [%(levelname)s] %(name)s: %(message)s'
LOG_DATE_FORMAT = '%Y-%m-%d %H:%M:%S'
CAPTURE_EXTERNAL_LOGS = False  # Capture logs from external libraries

# Secret Provider configuration
SECRET_BACKEND = os.getenv("SECRET_BACKEND", "keyring")  # "keyring", "env", "azure_keyvault", "aws_secretsmanager"
KEYRING_SERVICE_NAME = os.getenv("KEYRING_SERVICE_NAME", "document-ai-extractor")
AZURE_KEYVAULT_URL = os.getenv("AZURE_KEYVAULT_URL", "")

# Preferred models per provider (tried in order, first available wins)
PREFERRED_MODELS = {
    "groq": ["openai/gpt-oss-20b", "qwen/qwen3.6-27b"],
    "gemini": ["gemini-2.5-flash", "gemini-3.5-flash"],
}

# Extraction configuration
EXTRACTION_TIMEOUT_SECONDS = int(os.getenv("EXTRACTION_TIMEOUT_SECONDS", "60"))  # per model call; failed calls are retried twice

# Uploads (POST /receipts). The size cap is the same for every provider: Lambda caps a request at 6 MB and
# base64-encodes binary bodies inside that. The rate limit counts model calls for the whole process.
MAX_UPLOAD_MB = float(os.getenv("MAX_UPLOAD_MB", "4"))
UPLOAD_RATE_LIMIT_PER_MINUTE = int(os.getenv("UPLOAD_RATE_LIMIT_PER_MINUTE", "10"))
# Model calls per UTC day, counted in storage every instance shares, so it bounds a deployment's daily model cost
UPLOAD_DAILY_LIMIT = int(os.getenv("UPLOAD_DAILY_LIMIT", "50"))

# Local storage (CLOUD_PROVIDER=local); directories are created on first use, never at import
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", BASE_DIR / "uploads"))
SQLITE_PATH = Path(os.getenv("SQLITE_PATH", BASE_DIR / "data" / "receipts.db"))

# AWS storage (CLOUD_PROVIDER=aws). Credentials and the region come from boto3's usual sources: the Lambda role and
# AWS_REGION when deployed. The Gemini key is read with SECRET_BACKEND=aws_secretsmanager.
S3_BUCKET = os.getenv("S3_BUCKET", "")
DYNAMODB_RECORDS_TABLE = os.getenv("DYNAMODB_RECORDS_TABLE", "")
DYNAMODB_QUOTA_TABLE = os.getenv("DYNAMODB_QUOTA_TABLE", "")
