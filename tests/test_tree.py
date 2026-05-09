"""Tree helper tests."""

from __future__ import annotations

from pathlib import Path

from files_ai.storage import FileRef
from files_ai.storage import LocalFiles
from files_ai.tree import build_tagged_destination_tree
from files_ai.tree import build_upload_batch_tree


def test_build_upload_batch_tree_renders_nested_paths() -> None:
    """Upload batch tree should render parent and child nodes."""
    tree = build_upload_batch_tree(["tax/w2.pdf", "tax/receipt.txt"])
    assert "- tax" in tree
    assert "- w2.pdf" in tree
    assert "- receipt.txt" in tree


def test_build_tagged_destination_tree_marks_new_paths(tmp_path: Path) -> None:
    """Destination tree should tag new files and folders."""
    files = LocalFiles(tmp_path)
    organized = FileRef("local", "/organized")
    files.make_dir(organized)
    files.make_dir(files.join(organized, "Finance"))
    files.make_dir(files.join(organized, "Finance/Taxes"))
    (tmp_path / "organized" / "Finance" / "Taxes" / "w2.pdf").write_text(
        "w2",
        encoding="utf-8",
    )
    rendered = build_tagged_destination_tree(
        files,
        organized,
        new_file_paths={"/organized/Finance/Taxes/w2.pdf"},
        new_folder_paths={"/organized/Finance/Taxes"},
    )
    assert "[NEW_FOLDER]" in rendered
    assert "[NEW]" in rendered
