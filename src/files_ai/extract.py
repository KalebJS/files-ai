"""Tiered file-content extraction helpers."""

from __future__ import annotations

import io
import mimetypes
import re
from dataclasses import dataclass

from .storage import FileRef
from .storage import Files

GENERIC_NAME = re.compile(r"^(img|scan|document|file)[-_ ]?\d*$", re.IGNORECASE)


@dataclass(frozen=True)
class ExtractionResult:
    """Normalized extraction output for one file.

    Attributes:
        text: Extracted text or fallback filename.
        mime: Detected MIME type when available.
        tier: Extraction tier used to produce `text`.
    """

    text: str
    mime: str | None
    tier: int


def extract_file(
    files: Files, ref: FileRef, *, max_bytes: int = 8192, ocr_enabled: bool = False
) -> ExtractionResult:
    """Extract useful text from a file using tiered strategies.

    Args:
        files: Storage backend used for file reads.
        ref: File to extract text from.
        max_bytes: Maximum bytes to read for text-like content.
        ocr_enabled: Whether to run OCR for image files when needed.

    Returns:
        ExtractionResult: Normalized extraction result.
    """
    name = files.name_of(ref)
    first_bytes = files.read_bytes(ref, limit=min(max_bytes, 4096))
    mime = _detect_mime(name, first_bytes)
    tier = 1
    text = ""

    if _needs_tier_two(name, mime):
        text = _extract_text(files, ref, mime, max_bytes=max_bytes).strip()
        tier = 2

    if not text and ocr_enabled:
        text = _extract_ocr(files, ref, mime).strip()
        if text:
            tier = 3

    if not text:
        text = name
    return ExtractionResult(text=text, mime=mime, tier=tier)


def _detect_mime(filename: str, content: bytes) -> str | None:
    """Detect MIME type from bytes with filename fallback.

    Args:
        filename: Source filename used for fallback guessing.
        content: Initial bytes used for content-based detection.

    Returns:
        str | None: MIME type when detected, otherwise `None`.
    """
    try:
        import magic  # type: ignore

        detected = magic.from_buffer(content, mime=True)
        if detected:
            return str(detected)
    except Exception:
        pass
    guessed, _ = mimetypes.guess_type(filename)
    return guessed


def _needs_tier_two(name: str, mime: str | None) -> bool:
    """Return whether richer text extraction is needed.

    Args:
        name: Source filename.
        mime: Detected MIME type.

    Returns:
        bool: `True` when tier-two extraction should run.
    """
    stem = name.rsplit(".", 1)[0]
    if GENERIC_NAME.match(stem):
        return True
    if mime is None:
        return True
    return mime.startswith("text/") or mime in {
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }


def _extract_text(
    files: Files, ref: FileRef, mime: str | None, *, max_bytes: int
) -> str:
    """Extract text from supported document formats.

    Args:
        files: Storage backend used for file reads.
        ref: File reference to extract from.
        mime: Detected MIME type.
        max_bytes: Maximum bytes to read for text media.

    Returns:
        str: Extracted text, or an empty string when unsupported or failed.
    """
    lower = files.name_of(ref).lower()
    if lower.endswith(".pdf") or mime == "application/pdf":
        try:
            from pypdf import PdfReader

            payload = files.read_bytes(ref)
            reader = PdfReader(io.BytesIO(payload))
            return "\n".join(
                (page.extract_text() or "") for page in reader.pages
            ).strip()
        except Exception:
            return ""
    if lower.endswith(".docx") or (
        mime
        == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    ):
        try:
            from docx import Document

            payload = files.read_bytes(ref)
            document = Document(io.BytesIO(payload))
            return "\n".join(par.text for par in document.paragraphs).strip()
        except Exception:
            return ""
    if mime and mime.startswith("text/"):
        return files.read_bytes(ref, limit=max_bytes).decode("utf-8", errors="ignore")
    return ""


def _extract_ocr(files: Files, ref: FileRef, mime: str | None) -> str:
    """Extract text from image content via OCR when possible.

    Args:
        files: Storage backend used for file reads.
        ref: File reference to extract from.
        mime: Detected MIME type.

    Returns:
        str: OCR text, or an empty string if OCR is unavailable or fails.
    """
    if not (mime and mime.startswith("image/")):
        return ""
    try:
        import pytesseract
        from PIL import Image
    except Exception:
        return ""
    payload = files.read_bytes(ref)
    try:
        with Image.open(io.BytesIO(payload)) as image:
            return pytesseract.image_to_string(image)
    except Exception:
        return ""
