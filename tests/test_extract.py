"""Extraction pipeline tests."""

from __future__ import annotations

from pathlib import Path

from files_ai.extract import extract_file
from files_ai.storage import FileRef
from files_ai.storage import LocalFiles


def test_extract_text_file(tmp_path: Path) -> None:
    """Extract text content from a plain text file.

    Args:
        tmp_path: Temporary test directory.
    """
    files = LocalFiles(tmp_path)
    drop = FileRef("local", "/dropzone")
    files.make_dir(drop)
    ref = files.join(drop, "invoice.txt")
    (tmp_path / "dropzone" / "invoice.txt").write_text(
        "Invoice #123 for consulting services",
        encoding="utf-8",
    )
    result = extract_file(files, ref, max_bytes=2048, ocr_enabled=False)
    assert "Invoice" in result.text
    assert result.tier >= 1


def test_extract_generic_name_fallbacks_to_filename(tmp_path: Path) -> None:
    """Fallback to filename when no extractable content exists.

    Args:
        tmp_path: Temporary test directory.
    """
    files = LocalFiles(tmp_path)
    drop = FileRef("local", "/dropzone")
    files.make_dir(drop)
    ref = files.join(drop, "IMG_1234.bin")
    (tmp_path / "dropzone" / "IMG_1234.bin").write_bytes(b"\x00\x01\x02")
    result = extract_file(files, ref, max_bytes=128, ocr_enabled=False)
    assert "IMG_1234" in result.text
