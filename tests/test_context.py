"""Context loading tests."""

from __future__ import annotations

from pathlib import Path

from files_ai.context import CONTEXT_FILENAME
from files_ai.context import load_user_context
from files_ai.storage import FileRef
from files_ai.storage import LocalFiles


def test_load_user_context_reads_adjacent_context_file(tmp_path: Path) -> None:
    """Read adjacent CONTEXT.md when present."""
    files = LocalFiles(tmp_path)
    dropzone = FileRef("local", "/dropzone")
    files.make_dir(dropzone)
    (tmp_path / "CONTEXT.md").write_text("Business context", encoding="utf-8")
    value = load_user_context(files=files, dropzone=dropzone)
    assert value == "Business context"


def test_load_user_context_creates_default_when_missing(tmp_path: Path) -> None:
    """Create starter CONTEXT.md and return its content when missing."""
    files = LocalFiles(tmp_path)
    dropzone = FileRef("local", "/dropzone")
    files.make_dir(dropzone)
    value = load_user_context(files=files, dropzone=dropzone)
    assert "# About the filesystem user" in value
    assert "# Filesystem expectations" in value
    assert "# Filename formatting instructions" in value
    assert (
        "The user values quick retrieval, clarity, and long-term consistency." in value
    )
    assert "Keep filenames readable and concise." in value
    assert (tmp_path / CONTEXT_FILENAME).exists()


def test_load_user_context_honors_byte_limit(tmp_path: Path) -> None:
    """Bound context content to configured byte limit."""
    files = LocalFiles(tmp_path)
    dropzone = FileRef("local", "/dropzone")
    files.make_dir(dropzone)
    (tmp_path / "CONTEXT.md").write_text("abcdefghij", encoding="utf-8")
    value = load_user_context(files=files, dropzone=dropzone, max_bytes=4)
    assert value == "abcd"
