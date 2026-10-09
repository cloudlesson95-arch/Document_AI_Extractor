import logging
import os

from backend import logging_config

TMP_LOG = os.path.join("/tmp", "app.log")


def test_file_logging_falls_back_to_tmp_on_a_read_only_disk(monkeypatch):
    opened = []

    class ReadOnlyDiskFileHandler(logging.Handler):
        """Fails like FileHandler on Lambda's read-only disk for every path except /tmp; opens nothing."""

        def __init__(self, path, encoding=None):
            if path != TMP_LOG:
                raise OSError(30, "Read-only file system", path)
            super().__init__()
            opened.append(path)

    monkeypatch.setattr(logging_config, "LOG_TO_FILE", True)
    monkeypatch.setattr(logging_config.logging, "FileHandler", ReadOnlyDiskFileHandler)

    logger = logging_config.setup_logging("test.read_only_disk")

    assert opened == [TMP_LOG]
    assert any(isinstance(handler, ReadOnlyDiskFileHandler) for handler in logger.handlers)
