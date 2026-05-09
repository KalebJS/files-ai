"""Tree helper tests."""

from __future__ import annotations

import json
from pathlib import Path

from files_ai.storage import FileRef
from files_ai.storage import LocalFiles
from files_ai.tree import build_folder_snapshot_tree
from files_ai.tree import build_tagged_destination_tree
from files_ai.tree import build_upload_batch_tree


def test_build_upload_batch_tree_renders_nested_paths() -> None:
    """Upload batch tree should render folder keys with list children."""
    tree = build_upload_batch_tree(["tax/w2.pdf", "tax/receipt.txt"])
    payload = json.loads(tree)
    assert "tax" in payload
    children = payload["tax"]
    assert "receipt.txt" in children
    assert "w2.pdf" in children


def test_build_tagged_destination_tree_marks_new_paths(tmp_path: Path) -> None:
    """Destination tree should include new markers in JSON output."""
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
    payload = json.loads(rendered)
    finance_children = payload["Finance"]
    taxes = next(item for item in finance_children if isinstance(item, dict))
    taxes_key = next(iter(taxes.keys()))
    assert "[NEW_FOLDER]" in taxes_key
    assert "w2.pdf [NEW]" in taxes[taxes_key]


def test_build_folder_snapshot_tree_omits_files() -> None:
    """Folder snapshot tree should include folders only."""
    rendered = build_folder_snapshot_tree(
        ["10-19 Finance/10 Taxes/10.01 Taxes", "20-29 Projects/21 Client Work"]
    )
    payload = json.loads(rendered)
    assert "10-19 Finance" in payload
    assert "20-29 Projects" in payload
    assert "10.01 Taxes" in rendered
    assert "w2.pdf" not in rendered
