import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def load_cors_origins(value: str) -> subprocess.CompletedProcess:
    # Config is read at import, so each case runs in a fresh interpreter
    code = "import backend.config as c; print(c.CORS_ALLOW_ORIGINS)"
    env = {**os.environ, "CORS_ALLOW_ORIGINS": value, "LOG_TO_FILE": "false"}
    return subprocess.run([sys.executable, "-c", code], cwd=REPO_ROOT, env=env, capture_output=True, text=True)


def test_cors_origins_are_separated_by_spaces_without_trailing_slashes():
    result = load_cors_origins("https://receipts.example.com/  http://localhost:3000")

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "['https://receipts.example.com', 'http://localhost:3000']"


def test_cors_origins_separated_by_commas_stop_the_backend():
    # A comma list would silently match no origin; the Lambda "Variables={...}" shorthand would also split it
    result = load_cors_origins("https://receipts.example.com,http://localhost:3000")

    assert result.returncode != 0
    assert "separated by spaces, not commas" in result.stderr
