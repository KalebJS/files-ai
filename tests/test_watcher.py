"""Watcher behavior tests for directory-safe file processing."""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

from files_ai import __main__ as app
from files_ai.storage import FileEvent
from files_ai.storage import FileRef
from files_ai.storage import LocalFiles
from files_ai.watcher import StableFileWatcher


def test_iter_stable_events_ignores_directories(tmp_path: Path) -> None:
    """Yield only files when directory events are received.

    Args:
        tmp_path: Temporary test directory.
    """
    files = LocalFiles(tmp_path)
    drop = FileRef("local", "/dropzone")
    files.make_dir(drop)
    files.make_dir(files.join(drop, "nested"))
    file_ref = files.join(drop, "nested", "invoice.txt")
    (tmp_path / "dropzone" / "nested" / "invoice.txt").write_text(
        "invoice", encoding="utf-8"
    )
    dir_ref = files.join(drop, "nested")

    def _watch(*_: object) -> Iterator[FileEvent]:
        return iter(
            [
                FileEvent(kind="created", ref=dir_ref),
                FileEvent(kind="created", ref=file_ref),
            ]
        )

    files.watch = _watch  # type: ignore[method-assign]
    watcher = StableFileWatcher(files, stabilize_seconds=0.0)

    refs = list(watcher.iter_stable_events(drop))
    assert refs == [file_ref]


def test_with_dropzone_metadata_tracks_relative_folder() -> None:
    """Attach relative source directory metadata from dropzone root."""
    drop = FileRef("local", "/dropzone")
    nested = FileRef("local", "/dropzone/scans/2026/invoice.pdf")
    enriched = app._with_dropzone_metadata(nested, drop)
    assert enriched.extra["dropzone_relative_dir"] == "scans/2026"
