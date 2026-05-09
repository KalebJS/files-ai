"""Tree helper tests."""

from __future__ import annotations

import json
from pathlib import Path

from files_ai.storage import FileRef
from files_ai.storage import LocalFiles
from files_ai.tree import build_folder_snapshot_tree
from files_ai.tree import build_tree_snapshot


def test_build_folder_snapshot_tree_omits_files() -> None:
    """Folder snapshot tree should render JD hierarchy and files under IDs."""
    rendered = build_folder_snapshot_tree(
        [
            "10-19 Finance",
            "20-29 Projects/21 Client Work",
            "30-39 Legal/31 Contracts/31.01 Vendor Contracts",
            "30-39 Legal/31 Contracts/31.01 Vendor Contracts/z-notes.txt",
        ]
    )
    payload = json.loads(rendered)
    assert payload["10-19 Finance"] == {}
    assert payload["20-29 Projects"]["21 Client Work"] == {}
    assert payload["30-39 Legal"]["31 Contracts"]["31.01 Vendor Contracts"] == [
        "z-notes.txt"
    ]


def test_build_tree_snapshot_includes_id_files(tmp_path: Path) -> None:
    """Snapshot should include folder scaffolding and files under ID folders."""
    files = LocalFiles(tmp_path)
    organized = FileRef("local", "/organized")
    files.make_dir(files.join(organized, "10-19 Finance/10 Taxes/10.01 Taxes"))
    (
        tmp_path / "organized" / "10-19 Finance" / "10 Taxes" / "10.01 Taxes" / "a.txt"
    ).write_text("x", encoding="utf-8")
    snapshot = build_tree_snapshot(files, organized, max_depth=4)
    assert "10-19 Finance" in snapshot
    assert "10-19 Finance/10 Taxes" in snapshot
    assert "10-19 Finance/10 Taxes/10.01 Taxes" in snapshot
    assert "10-19 Finance/10 Taxes/10.01 Taxes/a.txt" in snapshot
