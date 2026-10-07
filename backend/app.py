import argparse
from .logging_config import setup_logging

logger = setup_logging(__name__)

def main():
    parser = argparse.ArgumentParser(description="Document AI Extractor")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # API commands
    serve_parser = subparsers.add_parser("serve", help="Run the FastAPI REST API server")
    serve_parser.add_argument("--host", default="127.0.0.1", help="Host to bind (default: 127.0.0.1)")
    serve_parser.add_argument("--port", type=int, default=8000, help="Port to bind (default: 8000)")
    serve_parser.add_argument("--reload", action="store_true", help="Restart on code changes (dev only)")

    # Secret management commands
    set_secret_parser = subparsers.add_parser("set-secret", help="Set a secret in the OS keyring")
    set_secret_parser.add_argument("name", help="Secret name (e.g. GOOGLE_API_KEY)")
    set_secret_parser.add_argument("value", nargs="?", default=None, help="Secret value")
    get_secret_parser = subparsers.add_parser("get-secret", help="Get a secret from keyring / env")
    get_secret_parser.add_argument("name", help="Secret name (e.g. GOOGLE_API_KEY)")

    # Extraction commands
    extract_parser = subparsers.add_parser("extract", help="Extract fields from a receipt or invoice file")
    extract_parser.add_argument("path", help="Path to a JPEG, PNG, WebP or PDF file")

    args = parser.parse_args()

    if args.command == "serve":
        import uvicorn
        from .config import BASE_DIR
        logger.info(f"Starting API server on {args.host}:{args.port}")
        uvicorn.run(
            "backend.api:app",
            host=args.host,
            port=args.port,
            reload=args.reload,
            reload_dirs=[str(BASE_DIR / "backend")] if args.reload else None,  # don't watch .venv / web/
        )

    elif args.command == "set-secret":
        import keyring
        import getpass
        from .config import KEYRING_SERVICE_NAME
        val = args.value or getpass.getpass(f"Enter secret value for '{args.name}': ") # to hide raw value
        keyring.set_password(KEYRING_SERVICE_NAME, args.name, val)
        logger.info(f"Secret '{args.name}' set successfully in OS Keyring ('{KEYRING_SERVICE_NAME}').")

    elif args.command == "get-secret":
        from .secrets import get_secret
        val = get_secret(args.name)
        if val is not None:
            masked = val[:4] + "..." + val[-4:] if len(val) > 8 else "***"
            print(f"{args.name}: {masked}")
        else:
            print(f"Secret '{args.name}' not found.")

    elif args.command == "extract":
        import sys
        from pathlib import Path
        from .extraction.base import SUPPORTED_MIME_TYPES, ExtractionError, detect_mime_type
        from .extraction.direct_api import GeminiVisionExtractor
        content = Path(args.path).read_bytes()
        mime_type = detect_mime_type(content)
        if mime_type is None:
            sys.exit(f"Unsupported file type: expected one of {sorted(SUPPORTED_MIME_TYPES)}")
        try:
            receipt = GeminiVisionExtractor().extract(content, mime_type)
        except ExtractionError as e:
            sys.exit(f"Extraction failed: {e}")
        print(receipt.model_dump_json(indent=2))

    else:
        parser.print_help()

if __name__ == "__main__":
    main()
