import pytest

from backend.extraction.base import detect_mime_type


@pytest.mark.parametrize("content, expected", [
    (b"%PDF-1.4\n%...", "application/pdf"),
    (b"\xff\xd8\xff\xe0\x00\x10JFIF", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n\x00\x00\x00\x0dIHDR", "image/png"),
    (b"RIFF\x24\x00\x00\x00WEBPVP8 ", "image/webp"),
    (b"RIFF\x24\x00\x00\x00WAVEfmt ", None),  # RIFF container, but audio
    (b"GIF89a", None),                         # a real image type we don't support
    (b"", None),
])
def test_detect_mime_type_reads_the_file_signature(content, expected):
    assert detect_mime_type(content) == expected
