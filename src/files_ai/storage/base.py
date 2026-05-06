"""Storage protocol definitions shared by all backends."""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from datetime import datetime
from typing import Any
from typing import BinaryIO
from typing import Iterator
from typing import Protocol


@dataclass(frozen=True, slots=True)
class FileRef:
    """Portable backend file reference."""

    backend: str
    path: str
    id: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class FileMeta:
    """Metadata for a file or directory."""

    ref: FileRef
    size: int
    mtime: datetime
    is_dir: bool
    mime: str | None = None
    sha256: str | None = None


@dataclass(frozen=True, slots=True)
class FileEvent:
    """Filesystem event emitted by a backend watcher."""

    kind: str
    ref: FileRef
    src_ref: FileRef | None = None


class StorageError(Exception):
    """Base storage exception."""


class NotFound(StorageError):
    """Raised when a referenced path does not exist."""


class Conflict(StorageError):
    """Raised when an operation conflicts with backend constraints."""


class Files(Protocol):
    """Interface for storage backends."""

    name: str

    def exists(self, ref: FileRef) -> bool:
        """Return whether a reference exists."""

    def stat(self, ref: FileRef) -> FileMeta:
        """Return metadata for a reference."""

    def walk(self, root: FileRef) -> Iterator[FileMeta]:
        """Yield files under root recursively."""

    def walk_dirs(self, root: FileRef, max_depth: int = 4) -> Iterator[FileRef]:
        """Yield directories under root recursively."""

    def open(self, ref: FileRef) -> BinaryIO:
        """Open a file reference for binary reads."""

    def read_bytes(self, ref: FileRef, *, limit: int | None = None) -> bytes:
        """Read bytes from a reference."""

    def hash(self, ref: FileRef, algo: str = "sha256") -> str:
        """Compute a hash for a file reference."""

    def make_dir(
        self, ref: FileRef, *, parents: bool = True, exist_ok: bool = True
    ) -> FileRef:
        """Create a directory reference."""

    def move(self, src: FileRef, dst: FileRef, *, overwrite: bool = False) -> FileRef:
        """Move a reference to a destination."""

    def copy(self, src: FileRef, dst: FileRef, *, overwrite: bool = False) -> FileRef:
        """Copy a reference to a destination."""

    def delete(self, ref: FileRef) -> None:
        """Delete a file or directory reference."""

    def join(self, root: FileRef, *parts: str) -> FileRef:
        """Join path parts under a root reference."""

    def parent(self, ref: FileRef) -> FileRef:
        """Return parent reference for a path."""

    def name_of(self, ref: FileRef) -> str:
        """Return basename for a reference."""

    def watch(self, root: FileRef) -> Iterator[FileEvent]:
        """Yield filesystem events for a watched root."""

    def stop_watch(self) -> None:
        """Stop active watch stream."""
