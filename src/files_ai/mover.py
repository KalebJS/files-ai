"""File move helpers with dedupe and conflict resolution."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import PurePosixPath

from .storage import FileRef
from .storage import Files
from .store import Store


@dataclass(frozen=True)
class MoveResult:
    """Result details for a move operation.

    Attributes:
        file_id: Inserted store row id, if created.
        destination: Destination reference, if assigned.
        dry_run: Whether the operation ran in dry-run mode.
        duplicate: Whether source content was detected as duplicate.
    """

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
    duplicate_folder: FileRef | None = None,
    filename: str | None = None,
    mime: str | None,
    extracted_chars: int,
    dry_run: bool = False,
) -> MoveResult:
    """Move one file into target folder and persist metadata.

    Args:
        files: Storage backend.
        store: Persistent metadata store.
        src: Source file reference.
        folder: Destination folder reference.
        duplicate_folder: Destination folder for duplicate items.
        filename: Optional destination filename override for non-duplicates.
        mime: MIME type when known.
        extracted_chars: Number of extracted text characters.
        dry_run: Whether to avoid filesystem writes.

    Returns:
        MoveResult: Operation result metadata.
    """
    src_filename = files.name_of(src)
    selected_filename = filename.strip() if filename is not None else ""
    target_filename = selected_filename or src_filename
    src_meta = files.stat(src)
    sha256 = _source_hash(files=files, src=src, is_dir=src_meta.is_dir)
    if store.has_hash(sha256):
        if duplicate_folder is None:
            return MoveResult(
                file_id=None, destination=None, dry_run=dry_run, duplicate=True
            )
        duplicate_dst_folder = _duplicate_folder(
            files=files,
            src=src,
            duplicate_folder=duplicate_folder,
        )
        files.make_dir(duplicate_dst_folder, parents=True, exist_ok=True)
        destination = _next_available_destination(
            files=files,
            folder=duplicate_dst_folder,
            name=src_filename,
        )
        if not dry_run:
            files.move(src, destination)
        return MoveResult(
            file_id=None, destination=destination, dry_run=dry_run, duplicate=True
        )

    file_id = store.insert_file(
        sha256=sha256,
        backend=src.backend,
        src_path=src.path,
        size=src_meta.size,
        mime=mime if not src_meta.is_dir else "inode/directory",
        extracted_chars=extracted_chars,
    )
    files.make_dir(folder, parents=True, exist_ok=True)
    destination = _next_available_destination(
        files=files, folder=folder, name=target_filename
    )
    if not dry_run:
        files.move(src, destination)
        store.set_destination(file_id, destination.path)
    return MoveResult(
        file_id=file_id, destination=destination, dry_run=dry_run, duplicate=False
    )


def _next_available_destination(*, files: Files, folder: FileRef, name: str) -> FileRef:
    """Return the next non-conflicting destination path.

    Args:
        files: Storage backend.
        folder: Destination folder reference.
        name: Preferred filename.

    Returns:
        FileRef: First non-conflicting destination reference.
    """
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
    """Split filename into stem and full suffix.

    Args:
        name: Filename to split.

    Returns:
        tuple[str, str]: Stem and full suffix components.
    """
    pure = PurePosixPath(name)
    suffix = "".join(pure.suffixes)
    if not suffix:
        return name, ""
    return name[: -len(suffix)], suffix


def _source_hash(*, files: Files, src: FileRef, is_dir: bool) -> str:
    """Compute a deterministic content hash for files or directory trees."""
    if not is_dir:
        return files.hash(src)
    digest = hashlib.sha256()
    digest.update(b"dir-v1\0")
    root = PurePosixPath(src.path)
    file_metas = sorted(files.walk(src), key=lambda meta: meta.ref.path)
    for meta in file_metas:
        rel = PurePosixPath(meta.ref.path).relative_to(root).as_posix()
        digest.update(rel.encode("utf-8", errors="ignore"))
        digest.update(b"\0")
        digest.update(files.hash(meta.ref).encode("ascii"))
        digest.update(b"\0")
    return f"dir:{digest.hexdigest()}"


def _duplicate_folder(
    *, files: Files, src: FileRef, duplicate_folder: FileRef
) -> FileRef:
    """Build duplicate destination folder preserving source-relative dir."""
    rel_dir = str(src.extra.get("dropzone_relative_dir", "")).strip()
    if not rel_dir:
        return duplicate_folder
    parts = [
        part for part in PurePosixPath(rel_dir).parts if part not in {"", ".", "/"}
    ]
    if not parts:
        return duplicate_folder
    return files.join(duplicate_folder, *parts)
