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
    files.make_dir(files.join(organized, "10-19 Finance"))
    files.make_dir(files.join(organized, "10-19 Finance/10 Taxes"))
    files.make_dir(files.join(organized, "10-19 Finance/10 Taxes/10.01 Taxes"))
    (
        tmp_path / "organized" / "10-19 Finance" / "10 Taxes" / "10.01 Taxes" / "w2.pdf"
    ).write_text(
        "w2",
        encoding="utf-8",
    )
    rendered = build_tagged_destination_tree(
        files,
        organized,
        new_file_paths={"/organized/10-19 Finance/10 Taxes/10.01 Taxes/w2.pdf"},
        new_folder_paths={"/organized/10-19 Finance/10 Taxes/10.01 Taxes"},
    )
    payload = json.loads(rendered)
    id_key = "10.01 Taxes [NEW_FOLDER]"
    assert "w2.pdf [NEW]" in payload["10-19 Finance"]["10 Taxes"][id_key]


def test_build_folder_snapshot_tree_omits_files() -> None:
    """Folder snapshot tree should include folders only with JD hierarchy."""
    rendered = build_folder_snapshot_tree(
        [
            "10-19 Finance",
            "20-29 Projects/21 Client Work",
            "30-39 Legal/31 Contracts/31.01 Vendor Contracts",
        ]
    )
    payload = json.loads(rendered)
    assert payload["10-19 Finance"] == {}
    assert payload["20-29 Projects"]["21 Client Work"] == {}
    assert payload["30-39 Legal"]["31 Contracts"]["31.01 Vendor Contracts"] == []
    assert "w2.pdf" not in rendered


def test_build_tagged_destination_tree_limits_files_to_top_five(tmp_path: Path) -> None:
    """Destination tree should render only top 5 files (desc) and ellipsis."""
    files = LocalFiles(tmp_path)
    organized = FileRef("local", "/organized")
    files.make_dir(organized)
    files.make_dir(files.join(organized, "10-19 Finance/10 Taxes/10.01 Taxes"))
    for name in ["a.txt", "b.txt", "c.txt", "d.txt", "e.txt", "f.txt", "g.txt"]:
        (
            tmp_path / "organized" / "10-19 Finance" / "10 Taxes" / "10.01 Taxes" / name
        ).write_text("x", encoding="utf-8")

    rendered = build_tagged_destination_tree(
        files,
        organized,
        new_file_paths=set(),
        new_folder_paths=set(),
    )
    payload = json.loads(rendered)
    assert payload["10-19 Finance"]["10 Taxes"]["10.01 Taxes"] == [
        "g.txt",
        "f.txt",
        "e.txt",
        "d.txt",
        "c.txt",
        "...",
    ]
