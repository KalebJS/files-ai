"""Johnny.Decimal normalization tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from files_ai.johnny_decimal import JohnnyDecimalLimitError
from files_ai.johnny_decimal import analyze_johnny_decimal_creation
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


def test_enforce_jd_raises_when_area_capacity_full(tmp_path: Path) -> None:
    """Do not create extra/duplicate areas when all 10 are already present."""
    files = LocalFiles(tmp_path)
    organized = FileRef("local", "/organized")
    files.make_dir(organized)
    for start in (0, 10, 20, 30, 40, 50, 60, 70, 80, 90):
        files.make_dir(
            files.join(organized, f"{start:02d}-{start + 9:02d} Area {start}")
        )

    with pytest.raises(JohnnyDecimalLimitError):
        enforce_johnny_decimal_folder(
            files=files,
            root=organized,
            folder="New Area/New Category/New ID",
        )


def test_enforce_jd_raises_when_category_capacity_full(tmp_path: Path) -> None:
    """Do not spill into a new area when an area already has 10 categories."""
    files = LocalFiles(tmp_path)
    organized = FileRef("local", "/organized")
    files.make_dir(organized)
    files.make_dir(files.join(organized, "20-29 Council Meetings"))
    for num in range(20, 30):
        files.make_dir(
            files.join(organized, f"20-29 Council Meetings/{num:02d} Cat {num}")
        )

    with pytest.raises(JohnnyDecimalLimitError):
        enforce_johnny_decimal_folder(
            files=files,
            root=organized,
            folder="Council Meetings/New Category/New ID",
        )


def test_analyze_creation_flags_new_area_and_category(tmp_path: Path) -> None:
    """Analyze when a proposal requires creating area/category segments."""
    files = LocalFiles(tmp_path)
    organized = FileRef("local", "/organized")
    files.make_dir(files.join(organized, "20-29 Council Meetings/23 Youth Council"))
    analysis = analyze_johnny_decimal_creation(
        files=files,
        root=organized,
        folder="Events/Fall Festival/Flyers",
    )
    assert analysis.requires_moderation
    assert analysis.creates_area
    assert analysis.creates_category


def test_analyze_creation_skips_moderation_for_new_id_only(tmp_path: Path) -> None:
    """Do not require moderation when only an ID is being added."""
    files = LocalFiles(tmp_path)
    organized = FileRef("local", "/organized")
    files.make_dir(
        files.join(organized, "20-29 Council Meetings/23 Youth Council/23.01 Agendas")
    )
    analysis = analyze_johnny_decimal_creation(
        files=files,
        root=organized,
        folder="Council Meetings/Youth Council/Minutes",
    )
    assert not analysis.requires_moderation
    assert not analysis.creates_area
    assert not analysis.creates_category
