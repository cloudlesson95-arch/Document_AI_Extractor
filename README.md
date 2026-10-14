# Document AI Extractor

Upload a photo or PDF of a receipt or invoice, and a vision-capable model extracts the vendor, date, total amount, currency and line items into a validated record. A small classical classifier (scikit-learn, not the language model) suggests an expense category. You review and correct both before they are final, then search your records in a dashboard.

Storage, the database and the extraction model each sit behind a small interface, and one setting, `CLOUD_PROVIDER`, selects the implementation: `local`, `aws` or `azure`.

> 🚧 Work in progress: Phases 0–6 (scaffold, extraction, storage, API, frontend, categorization, AWS deployment) are done; Phase 7 (Azure) is built and being deployed.

## Architecture

```
Next.js (web/) ──HTTP──▶ FastAPI (backend/)
                             │
                             │  CLOUD_PROVIDER =  local            aws         azure
                             ├── FileStorage      disk (uploads/)  S3          Blob Storage
                             ├── RecordStore      SQLite           DynamoDB    Table Storage
                             ├── UploadQuota      SQLite           DynamoDB    Table Storage
                             └── VisionExtractor  Gemini API       Gemini API  Gemini API
```

`local` needs no cloud account and no cloud SDK, which also proves that no cloud-specific code leaks past the interfaces. On `aws` and `azure` the extractor calls the Gemini API too, with its key from AWS Secrets Manager or Azure Key Vault. `UploadQuota` counts uploads per day for every instance of the API together.

## Features by phase

| Phase | Status | What it adds |
|---|---|---|
| 0. Scaffold | ✅ Done | FastAPI app with `/health` and CORS, a CLI, pluggable secrets (`SECRET_BACKEND`), and a Next.js frontend that checks the backend from the browser |
| 1. Extraction | ✅ Done | `ExtractedReceipt` schema, a Gemini vision extractor that raises when the model's output fails validation, and an `extract` CLI command |
| 2. Storage | ✅ Done | `FileStorage` (disk) and `RecordStore` (SQLite) behind interfaces with shared contract tests; `backend/providers.py` picks the implementations from `CLOUD_PROVIDER` |
| 3. API | ✅ Done | Upload and extract, search and filter, the original file for review, and corrections that record whether the model got something wrong |
| 4. Frontend | ✅ Done | An upload page that shrinks photos in the browser, a searchable receipts table, and a review page showing the original next to the editable fields |
| 5. Categorization | ✅ Done | A TF-IDF and logistic-regression classifier suggests an expense category from the vendor and line items; receipts it isn't confident about stay uncategorized. It's trained with scikit-learn and exported to `model.json`, which the app scores in plain Python |
| 6. AWS | ✅ Done | S3 and DynamoDB implementations, the Gemini key in Secrets Manager, and a daily upload limit shared by every instance; the backend on Lambda (container image) behind a Function URL, deployed by a GitHub Actions workflow, and the frontend on Vercel |
| 7. Azure | 🚧 In progress | Blob Storage and Table Storage implementations, tested on the Azurite emulator, and the Gemini key in Key Vault; the same image on Container Apps, signed in to storage and Key Vault with its managed identity, deployed by a second GitHub Actions workflow |

## Local setup

Requires Python 3.13 with [uv](https://docs.astral.sh/uv/), and Node.js 22.12+. The commands are for PowerShell on Windows.

### Backend

```powershell
uv venv --seed --python 3.13 .venv; .venv\Scripts\Activate.ps1
uv pip sync requirements.txt requirements-dev.txt
python -m backend.app set-secret GOOGLE_API_KEY   # stored in the OS keyring; prompts without echoing
python -m backend.app serve --reload              # http://127.0.0.1:8000/docs
```

Run the backend from the repo root as a module (`python -m backend.app`), not as a script. Other commands: `extract <file>` prints the fields extracted from a JPEG, PNG, WebP or PDF as JSON; `get-secret <name>` prints a masked value; `serve --host <host> --port <port>`; `export-model` retrains the expense categorizer and writes `backend/categorization/model.json`. Run it after editing `training_data.csv` and commit the file: the tests fail while it's out of date.

With the backend running, `http://127.0.0.1:8000/docs` describes every endpoint and can call them:

| Endpoint | What it does |
|---|---|
| `POST /receipts` | Upload a JPEG, PNG, WebP or PDF (multipart field `file`); extracts, categorizes, stores and returns the record. A 413 (over `MAX_UPLOAD_MB`), 415, 429 (over the per-minute or daily limit; see `Retry-After`) or 502 (extraction failed) stores nothing |
| `GET /receipts` | Records, newest first, filtered by `vendor_contains`, `date_from`, `date_to`, `min_total`, `max_total` (bounds inclusive) and `category` |
| `GET /receipts/{id}` | One record; its `file_url` serves the original upload |
| `PATCH /receipts/{id}` | JSON with new values for some of `vendor`, `date`, `total_amount`, `currency`, `line_items` and `category`; marks the record `corrected` when an extracted value changes, and `category_corrected` when the category does |

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

`/upload` extracts a receipt, `/receipts` lists them and filters by vendor, date and category, and `/receipts/<id>` shows the original next to the fields and the category to correct. Before uploading, the browser redraws photos as JPEGs of at most 2000 px, so phone photos fit under the upload cap; PDFs are sent as they are.

### Test

The Azure storage tests run on Azurite, Microsoft's storage emulator, in Docker; without it they're skipped (the deploy workflows start it and set `REQUIRE_AZURITE=1`, so there they fail instead). Start it once:

```powershell
docker run -d --rm --name azurite -p 127.0.0.1:10000:10000 -p 127.0.0.1:10002:10002 mcr.microsoft.com/azure-storage/azurite:3.37.0 azurite --blobHost 0.0.0.0 --tableHost 0.0.0.0 --inMemoryPersistence --skipApiVersionCheck
```

```powershell
python -m pytest -v          # backend; AWS tests run on moto's in-memory AWS, Azure storage tests on Azurite (the live Gemini test is skipped)
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
| `CLOUD_PROVIDER` | `local` | `local`, `aws` or `azure`; any other value stops the backend at startup |
| `SECRET_BACKEND` | `keyring` | `keyring`, `env`, `aws_secretsmanager` (which reads `document-ai-extractor/<name>`) or `azure_keyvault` (which reads `<name>` with hyphens for underscores, e.g. `GOOGLE-API-KEY`, from the vault at `AZURE_KEYVAULT_URL`); each falls back to environment variables |
| `KEYRING_SERVICE_NAME` | `document-ai-extractor` | Keyring entry that `set-secret` writes to |
| `CORS_ALLOW_ORIGINS` | `http://localhost:3000` | Browser origins allowed to call the API, separated by spaces; a comma stops the backend at startup |
| `APP_REVISION` | empty | Git SHA of the deployed build, shown in `/health`; the deployment sets it |
| `LOG_LEVEL`, `LOG_TO_FILE` | `INFO`, `true` | Logs go to the console and `logs/app.log` |
| `EXTRACTION_TIMEOUT_SECONDS` | `60` | Timeout for one model call; failed calls are retried twice |
| `MAX_UPLOAD_MB` | `4` | Larger uploads get a 413, on every provider; this keeps requests under Lambda's 6 MB cap. The frontend refuses larger files before sending them, so change `MAX_UPLOAD_MB` in `web/src/lib/upload.ts` with it |
| `UPLOAD_RATE_LIMIT_PER_MINUTE` | `10` | Uploads that reach the model, per minute for the whole process; more get a 429 with `Retry-After` |
| `UPLOAD_DAILY_LIMIT` | `50` | Uploads that reach the model per UTC day, counted for every instance together; more get a 429 until midnight UTC. Unlike the per-minute limit, it bounds a deployment's daily model cost |
| `UPLOAD_DIR`, `SQLITE_PATH` | `<repo>/uploads`, `<repo>/data/receipts.db` | Where the `local` provider keeps uploaded files, records and daily upload counts |
| `S3_BUCKET`, `DYNAMODB_RECORDS_TABLE`, `DYNAMODB_QUOTA_TABLE` | empty | Where the `aws` provider keeps them; AWS credentials and the region come from boto3's usual sources |
| `AZURE_STORAGE_ACCOUNT`, `AZURE_BLOB_CONTAINER`, `AZURE_RECORDS_TABLE`, `AZURE_QUOTA_TABLE` | empty | Where the `azure` provider keeps them. It signs in with `DefaultAzureCredential`: the app's managed identity (named by `AZURE_CLIENT_ID`) when deployed, or your `az login` |
| `AZURE_STORAGE_CONNECTION_STRING` | empty | Azurite only: `UseDevelopmentStorage=true` runs the `azure` provider on the emulator, in place of `AZURE_STORAGE_ACCOUNT` and the sign-in |
| `NEXT_PUBLIC_API_URL` (frontend) | `http://127.0.0.1:8000` | Backend URL, baked into the frontend at build time |

## Deploy to AWS

The backend runs on AWS Lambda as a container image behind a public Function URL, and the frontend on Vercel. You need the AWS CLI v2 signed in to your account, the code in a GitHub repository, and a Vercel account. The PowerShell scripts in `infra/aws/` name every AWS resource after `-AppName` (default `docai`), so other apps in the same account are never touched.

1. **AWS resources and roles**, once (safe to rerun; rerun it after creating or renaming the GitHub repository):
   ```powershell
   .\infra\aws\setup.ps1 -GitHubRepo <owner>/<repo>
   ```
   It asks for `GOOGLE_API_KEY`, which it stores in Secrets Manager as `document-ai-extractor/GOOGLE_API_KEY`, and prints the GitHub values below.
2. **GitHub** (Settings → Secrets and variables → Actions): the secret `AWS_ROLE_TO_ASSUME`, and the variables `AWS_REGION`, `APP_NAME` and `CORS_ALLOW_ORIGINS`.
3. **Backend**: Actions → *Deploy to AWS* → Run workflow, on `main`. It runs the tests, builds and deploys the image, and checks that `/health` reports the new commit; its summary shows the API URL.
4. **Frontend**: import the repository into Vercel with the root directory `web`, set `NEXT_PUBLIC_API_URL` to the API URL, and deploy.

| Value | Comes from | Goes to |
|---|---|---|
| Deploy role ARN | `setup.ps1` output | GitHub secret `AWS_ROLE_TO_ASSUME` |
| Region and app name | `setup.ps1` parameters | GitHub variables `AWS_REGION`, `APP_NAME` |
| Frontend URL | your Vercel project's name: `https://<project>.vercel.app` | GitHub variable `CORS_ALLOW_ORIGINS` with `http://localhost:3000`, separated by spaces; the next backend deploy applies it |
| API URL | the deploy workflow's summary | Vercel's `NEXT_PUBLIC_API_URL`; the next frontend build bakes it in |

`.\infra\aws\teardown.ps1` deletes all of it after asking; `-KeepSecret` keeps the Gemini key, and `-DeleteOidcProvider` also removes the account's GitHub sign-in when no other app's role uses it.

## Deploy to Azure

The same backend image runs on Azure Container Apps, with Blob Storage, Table Storage and the Gemini key in Key Vault. The app signs in to all three, and pulls its image, with its own managed identity, so no storage key, registry password or connection string exists. You need the Azure CLI signed in (`az login`) to a subscription where you can create resources and role assignments; a Free Trial works, since the model is Gemini. Everything goes into one resource group, `docai-rg`.

1. **Azure resources, roles and the GitHub sign-in**, once (safe to rerun):
   ```powershell
   .\infra\azure\setup.ps1 -GitHubRepo <owner>/<repo>
   ```
   It asks for `GOOGLE_API_KEY`, which it stores in Key Vault as `GOOGLE-API-KEY`, and prints the GitHub values below. The first run takes a few minutes.
2. **GitHub**: the secrets `AZURE_DEPLOY_CLIENT_ID`, `AZURE_TENANT_ID` and `AZURE_SUBSCRIPTION_ID`, and the variable `AZURE_RESOURCE_GROUP`. `APP_NAME` and `CORS_ALLOW_ORIGINS` are shared with the AWS deploy, so `-AppName` must match `APP_NAME`.
3. **Backend**: Actions → *Deploy to Azure* → Run workflow, on `main`. It runs the tests, builds and pushes the image, creates or updates the Container App, and checks that `/health` reports the new commit; its summary shows the API URL.
4. **Check**: `curl.exe <API URL>/health` reports `"cloud_provider":"azure"`. To use the frontend with it, set `NEXT_PUBLIC_API_URL=<API URL>` in `web/.env.local` and run `npm run dev`: `http://localhost:3000` is one of the allowed origins.

The app scales to zero when idle, so the first request after a quiet spell waits while it starts. The container registry is billed per day while it exists.

`.\infra\azure\teardown.ps1` deletes the resource group with everything in it, purges its key vault, and deletes the GitHub sign-in, after asking.

## Known limitations

- The API has no authentication: anyone who can reach it can upload (up to the per-minute and daily limits), list, read and correct every receipt. CORS only controls which websites can call it from a browser, not who can call it; `serve` listens on `127.0.0.1` by default for that reason.
- The category classifier is trained on 260 synthetic English receipts in `backend/categorization/training_data.csv` (with `export-model`; the app only reads the exported `model.json`). It reaches 90% cross-validated accuracy on them; real receipts score lower. A receipt it is less than 40% sure about stays uncategorized, and most non-English receipts do.
- On the Gemini API free tier, Google may use submitted documents to improve its products. Don't extract receipts that show personal data such as card numbers, names or addresses.
- Only the Vercel production URL is in `CORS_ALLOW_ORIGINS`, so Vercel's preview deployments can't call the deployed API.

## License

MIT, see [LICENSE](LICENSE).
