"""Protocol conformance smoke tests for LocalFiles."""

from __future__ import annotations

from pathlib import Path

from files_ai.storage import FileRef
from files_ai.storage import LocalFiles


def test_protocol_conformance_surface(tmp_path: Path) -> None:
    """Validate core `Files` protocol operations for local backend.

    Args:
        tmp_path: Temporary test directory.
    """
    files = LocalFiles(tmp_path)
    root = FileRef("local", "/dropzone")
    files.make_dir(root)
    child = files.join(root, "a.txt")
    (tmp_path / "dropzone" / "a.txt").write_text("abc", encoding="utf-8")

    assert files.exists(child)
    assert files.name_of(child) == "a.txt"
    assert files.parent(child).path == "/dropzone"
    assert files.read_bytes(child, limit=2) == b"ab"
    files.write_bytes(child, b"xyz")
    assert files.read_bytes(child) == b"xyz"
    assert files.stat(child).size == 3
    assert list(files.walk(root))
    assert list(files.iterdir(root))
