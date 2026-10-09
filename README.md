# Document AI Extractor

Upload a photo or PDF of a receipt or invoice, and a vision-capable model extracts the vendor, date, total amount, currency and line items into a validated record. You review and correct the extraction before it is final, then search your records in a dashboard.

Storage, the database and the extraction model each sit behind a small interface, and one setting, `CLOUD_PROVIDER`, selects the implementation: `local`, `aws` or `azure`.

> 🚧 Work in progress: Phases 0–3 (scaffold, extraction, storage, API) are done; the rest is planned.

## Architecture

```
Next.js (web/) ──HTTP──▶ FastAPI (backend/)
                             │
                             │  CLOUD_PROVIDER =  local            aws        azure
                             ├── FileStorage      disk (uploads/)  S3         Blob Storage
                             ├── RecordStore      SQLite           DynamoDB   Table Storage
                             └── VisionExtractor  Gemini API       Bedrock    Azure OpenAI
```

`local` needs no cloud account and no cloud SDK, which also proves that no cloud-specific code leaks past the interfaces.

## Features by phase

| Phase | Status | What it adds |
|---|---|---|
| 0. Scaffold | ✅ Done | FastAPI app with `/health` and CORS, a CLI, pluggable secrets (`SECRET_BACKEND`), and a Next.js frontend that checks the backend from the browser |
| 1. Extraction | ✅ Done | `ExtractedReceipt` schema, a Gemini vision extractor that raises when the model's output fails validation, and an `extract` CLI command |
| 2. Storage | ✅ Done | `FileStorage` (disk) and `RecordStore` (SQLite) behind interfaces with shared contract tests; `backend/providers.py` picks the implementations from `CLOUD_PROVIDER` |
| 3. API | ✅ Done | Upload and extract, search and filter, the original file for review, and corrections that record whether the model got something wrong |
| 4. Frontend | Planned | Upload page, receipts table, and a review page showing the original next to the editable fields |
| 5. Categorization | Optional | A small classical-ML classifier for expense categories |
| 6. AWS | Planned | S3, DynamoDB and Bedrock implementations; Lambda (container image) behind a Function URL |
| 7. Azure | Planned | Blob Storage, Table Storage and Azure OpenAI implementations; the same image on Container Apps |

## Local setup

Requires Python 3.13 with [uv](https://docs.astral.sh/uv/), and Node.js 22.12+. The commands are for PowerShell on Windows.

### Backend

```powershell
uv venv --seed --python 3.13 .venv; .venv\Scripts\Activate.ps1
uv pip sync requirements.txt requirements-dev.txt
python -m backend.app set-secret GOOGLE_API_KEY   # stored in the OS keyring; prompts without echoing
python -m backend.app serve --reload              # http://127.0.0.1:8000/docs
```

Run the backend from the repo root as a module (`python -m backend.app`), not as a script. Other commands: `extract <file>` prints the fields extracted from a JPEG, PNG, WebP or PDF as JSON; `get-secret <name>` prints a masked value; `serve --host <host> --port <port>`.

With the backend running, `http://127.0.0.1:8000/docs` describes every endpoint and can call them:

| Endpoint | What it does |
|---|---|
| `POST /receipts` | Upload a JPEG, PNG, WebP or PDF (multipart field `file`); extracts, stores and returns the record. A 413 (over `MAX_UPLOAD_MB`), 415, 429 (see `Retry-After`) or 502 (extraction failed) stores nothing |
| `GET /receipts` | Records, newest first, filtered by `vendor_contains`, `date_from`, `date_to`, `min_total` and `max_total` (bounds inclusive) |
| `GET /receipts/{id}` | One record; its `file_url` serves the original upload |
| `PATCH /receipts/{id}` | JSON with new values for some of `vendor`, `date`, `total_amount`, `currency` and `line_items`; marks the record `corrected` only when a value changes |

Amounts are JSON strings such as `"9.20"`, so they stay exact. To try it from PowerShell:

```powershell
curl.exe -F "file=@receipt.pdf" http://127.0.0.1:8000/receipts
curl.exe "http://127.0.0.1:8000/receipts?vendor_contains=cafe&date_from=2026-01-01"
```

`requirements.txt` is a lock file for Python 3.13 that your venv (and later the container image) installs, so every environment runs the same library versions; `requirements-dev.txt` adds the test tools. To change dependencies, edit `requirements.in` (or `requirements-dev.in`), recompile with the command in its header, then run the `uv pip sync` line again.

### Frontend

In a second terminal:

```powershell
cd web
npm ci
npm run dev    # http://localhost:3000
```

The backend URL defaults to `http://127.0.0.1:8000`; to change it, copy `web/.env.example` to `web/.env.local`.

Open `http://localhost:3000`, not `127.0.0.1:3000`: the backend only accepts browser requests from the origins in `CORS_ALLOW_ORIGINS`. The home page shows a green status line when it can reach the backend.

### Test

```powershell
python -m pytest -v          # backend (the live Gemini test is skipped)
$env:RUN_LIVE_TESTS="1"; python -m pytest tests/test_extraction_live.py -v   # calls the real Gemini API
cd web
npm run lint                 # frontend lint
npm test                     # frontend unit tests (Vitest)
npm run build                # frontend type check and production build
```

### Configuration

Every setting has a working local default. The backend reads environment variables, or a `.env` file in the repo root (gitignored; start from `.env.example`); the full list is in [`backend/config.py`](backend/config.py). The frontend reads `web/.env.local` (gitignored).

| Variable | Default | Purpose |
|---|---|---|
| `CLOUD_PROVIDER` | `local` | `local`, `aws` or `azure` (`aws` and `azure` arrive in Phases 6–7); any other value stops the backend at startup |
| `SECRET_BACKEND` | `keyring` | `keyring`, `env`, `azure_keyvault` or `aws_secretsmanager`; each falls back to environment variables |
| `KEYRING_SERVICE_NAME` | `document-ai-extractor` | Keyring entry that `set-secret` writes to |
| `CORS_ALLOW_ORIGINS` | `http://localhost:3000` | Browser origins allowed to call the API, separated by spaces; a comma stops the backend at startup |
| `APP_REVISION` | empty | Git SHA of the deployed build, shown in `/health`; the deployment sets it |
| `LOG_LEVEL`, `LOG_TO_FILE` | `INFO`, `true` | Logs go to the console and `logs/app.log` |
| `EXTRACTION_TIMEOUT_SECONDS` | `60` | Timeout for one model call; failed calls are retried twice |
| `MAX_UPLOAD_MB` | `4` | Larger uploads get a 413, on every provider; this keeps requests under Lambda's 6 MB cap |
| `UPLOAD_RATE_LIMIT_PER_MINUTE` | `10` | Uploads that reach the model, per minute for the whole process; more get a 429 with `Retry-After` |
| `UPLOAD_DIR`, `SQLITE_PATH` | `<repo>/uploads`, `<repo>/data/receipts.db` | Where the `local` provider keeps uploaded files and records |
| `NEXT_PUBLIC_API_URL` (frontend) | `http://127.0.0.1:8000` | Backend URL, baked into the frontend at build time |

## Known limitations

- The API has no authentication: anyone who can reach it can upload (up to the rate limit), list, read and correct every receipt. CORS only controls which websites can call it from a browser, not who can call it; `serve` listens on `127.0.0.1` by default for that reason.
- On the Gemini API free tier, Google may use submitted documents to improve its products. Don't extract receipts that show personal data such as card numbers, names or addresses.

## License

MIT, see [LICENSE](LICENSE).
