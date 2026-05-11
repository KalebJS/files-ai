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
    dup = FileRef("local", "/quarantine/duplicates")
    files.make_dir(drop)
    files.make_dir(org)
    files.make_dir(dup)
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
            duplicate_folder=dup,
            mime="text/plain",
            extracted_chars=4,
        )
        second = move_into_folder(
            files=files,
            store=db,
            src=ref2,
            folder=org,
            duplicate_folder=dup,
            mime="text/plain",
            extracted_chars=4,
        )
        assert first.destination is not None
        assert files.exists(first.destination)
        assert second.duplicate
        assert second.destination is not None
        assert files.exists(second.destination)
        assert second.destination.path == "/quarantine/duplicates/receipt-copy.txt"
        assert not files.exists(ref2)
    finally:
        db.close()


def test_move_directory_into_folder_and_dedupe(tmp_path: Path) -> None:
    """Move first directory and dedupe same-content directory."""
    files = LocalFiles(tmp_path)
    drop = FileRef("local", "/dropzone")
    org = FileRef("local", "/organized/Code/Projects")
    dup = FileRef("local", "/quarantine/duplicates")
    files.make_dir(drop)
    files.make_dir(org)
    files.make_dir(dup)
    db = Store(tmp_path / "state.db")
    try:
        ref1 = files.join(drop, "proj-a")
        ref2 = files.join(drop, "proj-b")
        files.make_dir(ref1)
        files.make_dir(ref2)
        (tmp_path / "dropzone" / "proj-a" / "main.py").write_text(
            "print('x')", encoding="utf-8"
        )
        (tmp_path / "dropzone" / "proj-b" / "main.py").write_text(
            "print('x')", encoding="utf-8"
        )
        first = move_into_folder(
            files=files,
            store=db,
            src=ref1,
            folder=org,
            duplicate_folder=dup,
            mime="inode/directory",
            extracted_chars=0,
        )
        second = move_into_folder(
            files=files,
            store=db,
            src=ref2,
            folder=org,
            duplicate_folder=dup,
            mime="inode/directory",
            extracted_chars=0,
        )
        assert first.destination is not None
        assert files.exists(first.destination)
        assert second.duplicate
        assert second.destination is not None
        assert files.exists(second.destination)
        assert second.destination.path == "/quarantine/duplicates/proj-b"
        assert not files.exists(ref2)
    finally:
        db.close()


def test_move_directory_hash_distinguishes_tree_layout(tmp_path: Path) -> None:
    """Do not dedupe different folder trees with different relative paths."""
    files = LocalFiles(tmp_path)
    drop = FileRef("local", "/dropzone")
    org = FileRef("local", "/organized/Code/Projects")
    files.make_dir(drop)
    files.make_dir(org)
    db = Store(tmp_path / "state.db")
    try:
        ref1 = files.join(drop, "proj-a")
        ref2 = files.join(drop, "proj-b")
        files.make_dir(ref1)
        files.make_dir(ref2)
        (tmp_path / "dropzone" / "proj-a" / "main.py").write_text(
            "print('x')", encoding="utf-8"
        )
        (tmp_path / "dropzone" / "proj-b" / "app.py").write_text(
            "print('x')", encoding="utf-8"
        )
        first = move_into_folder(
            files=files,
            store=db,
            src=ref1,
            folder=org,
            duplicate_folder=FileRef("local", "/quarantine/duplicates"),
            mime="inode/directory",
            extracted_chars=0,
        )
        second = move_into_folder(
            files=files,
            store=db,
            src=ref2,
            folder=org,
            duplicate_folder=FileRef("local", "/quarantine/duplicates"),
            mime="inode/directory",
            extracted_chars=0,
        )
        assert not first.duplicate
        assert not second.duplicate
        assert second.destination is not None
        assert files.exists(second.destination)
    finally:
        db.close()


def test_move_into_folder_reuses_stale_hash_record(tmp_path: Path) -> None:
    """Treat stale hash rows as normal moves when destination is missing."""
    files = LocalFiles(tmp_path)
    drop = FileRef("local", "/dropzone")
    org = FileRef("local", "/organized/Receipts")
    dup = FileRef("local", "/quarantine/duplicates")
    files.make_dir(drop)
    files.make_dir(org)
    files.make_dir(dup)
    db = Store(tmp_path / "state.db")
    try:
        ref = files.join(drop, "receipt.txt")
        (tmp_path / "dropzone" / "receipt.txt").write_text("same", encoding="utf-8")
        stale_id = db.insert_file(
            sha256=files.hash(ref),
            backend="local",
            src_path="/organized/Receipts/receipt-old.txt",
            size=4,
            mime="text/plain",
            extracted_chars=4,
        )
        db.set_destination(stale_id, "/organized/Receipts/receipt-old.txt")
        moved = move_into_folder(
            files=files,
            store=db,
            src=ref,
            folder=org,
            duplicate_folder=dup,
            mime="text/plain",
            extracted_chars=4,
        )
        assert moved.file_id == stale_id
        assert not moved.duplicate
        assert moved.destination is not None
        assert moved.destination.path == "/organized/Receipts/receipt.txt"
        assert files.exists(moved.destination)
        assert not files.exists(ref)
        updated = db.get_file_by_id(stale_id)
        assert updated is not None
        assert updated.dst_path == "/organized/Receipts/receipt.txt"
        assert not any((tmp_path / "quarantine" / "duplicates").iterdir())
    finally:
        db.close()


def test_move_into_folder_uses_filename_override(tmp_path: Path) -> None:
    """Move a file using provided filename override."""
    files = LocalFiles(tmp_path)
    drop = FileRef("local", "/dropzone")
    org = FileRef("local", "/organized/Receipts")
    files.make_dir(drop)
    files.make_dir(org)
    db = Store(tmp_path / "state.db")
    try:
        ref = files.join(drop, "scan.pdf")
        (tmp_path / "dropzone" / "scan.pdf").write_text("content", encoding="utf-8")
        moved = move_into_folder(
            files=files,
            store=db,
            src=ref,
            folder=org,
            filename="2026-05 Receipt.pdf",
            mime="application/pdf",
            extracted_chars=7,
        )
        assert moved.destination is not None
        assert moved.destination.path == "/organized/Receipts/2026-05 Receipt.pdf"
        assert files.exists(moved.destination)
        assert not files.exists(ref)
    finally:
        db.close()


def test_move_into_folder_filename_override_conflict_suffix(tmp_path: Path) -> None:
    """Apply numeric suffix when override collides with existing filename."""
    files = LocalFiles(tmp_path)
    drop = FileRef("local", "/dropzone")
    org = FileRef("local", "/organized/Receipts")
    files.make_dir(drop)
    files.make_dir(org)
    db = Store(tmp_path / "state.db")
    try:
        existing = files.join(org, "2026-05 Receipt.pdf")
        files.write_bytes(existing, b"existing")
        ref = files.join(drop, "scan.pdf")
        (tmp_path / "dropzone" / "scan.pdf").write_text("content", encoding="utf-8")
        moved = move_into_folder(
            files=files,
            store=db,
            src=ref,
            folder=org,
            filename="2026-05 Receipt.pdf",
            mime="application/pdf",
            extracted_chars=7,
        )
        assert moved.destination is not None
        assert moved.destination.path == "/organized/Receipts/2026-05 Receipt-1.pdf"
        assert files.exists(moved.destination)
    finally:
        db.close()
