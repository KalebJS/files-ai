"""File move helpers with dedupe and conflict resolution."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath

from .storage import FileRef
from .storage import Files
from .store import Store


@dataclass(frozen=True)
class MoveResult:
    """Result details for a move operation."""

    file_id: int | None
    destination: FileRef | None
    dry_run: bool
    duplicate: bool


def move_into_folder(
    *,
    files: Files,
    store: Store,
    src: FileRef,
    folder: FileRef,
    mime: str | None,
    extracted_chars: int,
    dry_run: bool = False,
) -> MoveResult:
    """Move one file into target folder and persist metadata."""
    filename = files.name_of(src)
    sha256 = files.hash(src)
    if store.has_hash(sha256):
        return MoveResult(
            file_id=None, destination=None, dry_run=dry_run, duplicate=True
        )

    meta = files.stat(src)
    file_id = store.insert_file(
        sha256=sha256,
        backend=src.backend,
        src_path=src.path,
        size=meta.size,
        mime=mime,
        extracted_chars=extracted_chars,
    )
    files.make_dir(folder, parents=True, exist_ok=True)
    destination = _next_available_destination(files=files, folder=folder, name=filename)
    if not dry_run:
        files.move(src, destination)
        store.set_destination(file_id, destination.path)
    return MoveResult(
        file_id=file_id, destination=destination, dry_run=dry_run, duplicate=False
    )


def _next_available_destination(*, files: Files, folder: FileRef, name: str) -> FileRef:
    """Return the next non-conflicting destination path."""
    candidate = files.join(folder, name)
    if not files.exists(candidate):
        return candidate
    stem, suffix = _split_name(name)
    n = 1
    while True:
        candidate = files.join(folder, f"{stem}-{n}{suffix}")
        if not files.exists(candidate):
            return candidate
        n += 1


def _split_name(name: str) -> tuple[str, str]:
    """Split filename into stem and full suffix."""
    pure = PurePosixPath(name)
    suffix = "".join(pure.suffixes)
    if not suffix:
        return name, ""
    return name[: -len(suffix)], suffix
