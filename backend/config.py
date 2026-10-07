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

# API configuration -- browser origins allowed to call the API (comma-separated)
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",") if o.strip()]

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
