"""Extraction pipeline tests."""

from __future__ import annotations

import io
import zipfile
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
    result = extract_file(files, ref, max_bytes=2048, vision_enabled=False)
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
    result = extract_file(files, ref, max_bytes=128, vision_enabled=False)
    assert "IMG_1234" in result.text


def test_extract_csv_rows(tmp_path: Path) -> None:
    """Extract structured rows from CSV."""
    files = LocalFiles(tmp_path)
    drop = FileRef("local", "/dropzone")
    files.make_dir(drop)
    ref = files.join(drop, "budget.csv")
    (tmp_path / "dropzone" / "budget.csv").write_text(
        "Month,Amount\nMay,1200\nJune,800\n",
        encoding="utf-8",
    )
    result = extract_file(files, ref, max_bytes=2048, vision_enabled=False)
    assert "Month | Amount" in result.text
    assert "May | 1200" in result.text
    assert result.tier == 2


def test_extract_xlsx_content(tmp_path: Path) -> None:
    """Extract worksheet text from XLSX XML."""
    files = LocalFiles(tmp_path)
    drop = FileRef("local", "/dropzone")
    files.make_dir(drop)
    ref = files.join(drop, "sheet.xlsx")
    (tmp_path / "dropzone" / "sheet.xlsx").write_bytes(_build_minimal_xlsx())
    result = extract_file(files, ref, max_bytes=4096, vision_enabled=False)
    assert "Sheet: Sheet1" in result.text
    assert "Name | Score" in result.text
    assert "Kaleb | 100" in result.text


def test_extract_pages_from_index_xml(tmp_path: Path) -> None:
    """Extract iWork package metadata text when previews are unavailable."""
    files = LocalFiles(tmp_path)
    drop = FileRef("local", "/dropzone")
    files.make_dir(drop)
    ref = files.join(drop, "notes.pages")
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr("index.xml", "<root><p>Quarterly Planning Notes</p></root>")
    (tmp_path / "dropzone" / "notes.pages").write_bytes(payload.getvalue())
    result = extract_file(files, ref, max_bytes=2048, vision_enabled=False)
    assert "Quarterly Planning Notes" in result.text
    assert result.tier == 2


def test_extract_image_via_vision(monkeypatch: object, tmp_path: Path) -> None:
    """Use vision path for image extraction when enabled."""
    files = LocalFiles(tmp_path)
    drop = FileRef("local", "/dropzone")
    files.make_dir(drop)
    ref = files.join(drop, "receipt.png")
    (tmp_path / "dropzone" / "receipt.png").write_bytes(b"\x89PNG\r\n\x1a\npayload")
    monkeypatch.setattr("files_ai.extract._extract_with_vision", lambda *_, **__: "A1")
    result = extract_file(files, ref, max_bytes=2048, vision_enabled=True)
    assert result.text == "A1"
    assert result.tier == 3


def test_extract_pdf_dispatches_to_pdf_handler(
    monkeypatch: object, tmp_path: Path
) -> None:
    """Dispatch PDF extraction through PDF handler."""
    files = LocalFiles(tmp_path)
    drop = FileRef("local", "/dropzone")
    files.make_dir(drop)
    ref = files.join(drop, "statement.pdf")
    (tmp_path / "dropzone" / "statement.pdf").write_bytes(b"%PDF-1.4\n%...")
    monkeypatch.setattr(
        "files_ai.extract._extract_pdf_bytes",
        lambda *_args, **_kwargs: ("Statement Total 100.00", False),
    )
    result = extract_file(files, ref, max_bytes=2048, vision_enabled=False)
    assert "Statement Total" in result.text
    assert result.tier == 2


def test_extract_encrypted_pdf_sets_flag(monkeypatch: object, tmp_path: Path) -> None:
    """Mark encrypted PDFs when text extraction returns empty."""
    files = LocalFiles(tmp_path)
    drop = FileRef("local", "/dropzone")
    files.make_dir(drop)
    ref = files.join(drop, "secret.pdf")
    (tmp_path / "dropzone" / "secret.pdf").write_bytes(b"%PDF-1.4\n%...")
    monkeypatch.setattr("files_ai.extract._extract_text", lambda *_a, **_k: ("", False))
    monkeypatch.setattr("files_ai.extract._is_pdf_encrypted", lambda *_a, **_k: True)
    result = extract_file(files, ref, max_bytes=2048, vision_enabled=True)
    assert result.encrypted
    assert result.tier == 1
    assert result.text == "secret.pdf"


def _build_minimal_xlsx() -> bytes:
    """Build a tiny XLSX payload for tests."""
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr(
            "xl/workbook.xml",
            (
                '<?xml version="1.0"?>'
                "<workbook xmlns:r="
                '"http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
                ' xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                '<sheets><sheet name="Sheet1" r:id="rId1"/></sheets>'
                "</workbook>"
            ),
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            (
                '<?xml version="1.0"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" Type="worksheet" '
                'Target="worksheets/sheet1.xml"/>'
                "</Relationships>"
            ),
        )
        archive.writestr(
            "xl/sharedStrings.xml",
            (
                '<?xml version="1.0"?>'
                '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                "<si><t>Name</t></si><si><t>Score</t></si><si><t>Kaleb</t></si>"
                "</sst>"
            ),
        )
        archive.writestr(
            "xl/worksheets/sheet1.xml",
            (
                '<?xml version="1.0"?>'
                '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                "<sheetData>"
                '<row r="1"><c r="A1" t="s"><v>0</v></c>'
                '<c r="B1" t="s"><v>1</v></c></row>'
                '<row r="2"><c r="A2" t="s"><v>2</v></c>'
                '<c r="B2"><v>100</v></c></row>'
                "</sheetData>"
                "</worksheet>"
            ),
        )
    return payload.getvalue()
