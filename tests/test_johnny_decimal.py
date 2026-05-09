"""Johnny.Decimal normalization tests."""

from __future__ import annotations

from pathlib import Path

from files_ai.johnny_decimal import enforce_johnny_decimal_folder
from files_ai.storage import FileRef
from files_ai.storage import LocalFiles


def test_enforce_jd_reuses_existing_labeled_path(tmp_path: Path) -> None:
    """Reuse existing Johnny.Decimal segments when labels match."""
    files = LocalFiles(tmp_path)
    organized = FileRef("local", "/organized")
    files.make_dir(files.join(organized, "10-19 Finance/13 Taxes/13.01 W-2s"))
    value = enforce_johnny_decimal_folder(
        files=files,
        root=organized,
        folder="Finance/Taxes/W-2s",
    )
    assert value == "10-19 Finance/13 Taxes/13.01 W-2s"


def test_enforce_jd_creates_area_category_and_id_when_missing(tmp_path: Path) -> None:
    """Allocate area/category/id when no matching structure exists."""
    files = LocalFiles(tmp_path)
    organized = FileRef("local", "/organized")
    files.make_dir(organized)
    value = enforce_johnny_decimal_folder(
        files=files,
        root=organized,
        folder="Legal/Housing/Lease",
    )
    assert value.startswith("10-19 Legal/")
    assert "/10 Housing/" in value
    assert value.endswith("10.01 Lease")


def test_enforce_jd_avoids_id_collision(tmp_path: Path) -> None:
    """Pick next available ID number when an ID is already used."""
    files = LocalFiles(tmp_path)
    organized = FileRef("local", "/organized")
    files.make_dir(files.join(organized, "10-19 Finance/10 Receipts/10.01 Grocery"))
    value = enforce_johnny_decimal_folder(
        files=files,
        root=organized,
        folder="Finance/Receipts/Gas",
    )
    assert value.endswith("10.02 Gas")
