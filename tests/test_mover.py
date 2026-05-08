"""Mover and deduplication tests."""

from __future__ import annotations

from pathlib import Path

from files_ai.mover import move_into_folder
from files_ai.storage import FileRef
from files_ai.storage import LocalFiles
from files_ai.store import Store


def test_move_into_folder_and_dedupe(tmp_path: Path) -> None:
    """Move first file and detect duplicate content on second file.

    Args:
        tmp_path: Temporary test directory.
    """
    files = LocalFiles(tmp_path)
    drop = FileRef("local", "/dropzone")
    org = FileRef("local", "/organized/Receipts")
    files.make_dir(drop)
    files.make_dir(org)
    db = Store(tmp_path / "state.db")
    try:
        ref1 = files.join(drop, "receipt.txt")
        ref2 = files.join(drop, "receipt-copy.txt")
        (tmp_path / "dropzone" / "receipt.txt").write_text("same", encoding="utf-8")
        (tmp_path / "dropzone" / "receipt-copy.txt").write_text(
            "same", encoding="utf-8"
        )
        first = move_into_folder(
            files=files,
            store=db,
            src=ref1,
            folder=org,
            mime="text/plain",
            extracted_chars=4,
        )
        second = move_into_folder(
            files=files,
            store=db,
            src=ref2,
            folder=org,
            mime="text/plain",
            extracted_chars=4,
        )
        assert first.destination is not None
        assert files.exists(first.destination)
        assert second.duplicate
    finally:
        db.close()
