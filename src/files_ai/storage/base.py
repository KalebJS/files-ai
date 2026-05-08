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
    """Portable backend file reference.

    Attributes:
        backend: Backend name that owns this reference.
        path: Backend-relative absolute-style path.
        id: Optional backend-specific stable identifier.
        extra: Additional metadata carried with the reference.
    """

    backend: str
    path: str
    id: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class FileMeta:
    """Metadata for a file or directory.

    Attributes:
        ref: File reference.
        size: File size in bytes.
        mtime: Last modification timestamp.
        is_dir: Whether the reference points to a directory.
        mime: Optional MIME type.
        sha256: Optional SHA-256 digest.
    """

    ref: FileRef
    size: int
    mtime: datetime
    is_dir: bool
    mime: str | None = None
    sha256: str | None = None


@dataclass(frozen=True, slots=True)
class FileEvent:
    """Filesystem event emitted by a backend watcher.

    Attributes:
        kind: Event kind such as `created`, `modified`, `deleted`, or `moved`.
        ref: Destination/current file reference for the event.
        src_ref: Source reference for move events when available.
    """

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
        """Return whether a reference exists.

        Args:
            ref: Reference to test.

        Returns:
            bool: `True` when the target exists.
        """

    def stat(self, ref: FileRef) -> FileMeta:
        """Return metadata for a reference.

        Args:
            ref: Reference to inspect.

        Returns:
            FileMeta: Metadata for the target.
        """

    def walk(self, root: FileRef) -> Iterator[FileMeta]:
        """Yield files under root recursively.

        Args:
            root: Root reference to walk.

        Yields:
            FileMeta: Metadata entries for files under `root`.
        """

    def walk_dirs(self, root: FileRef, max_depth: int = 4) -> Iterator[FileRef]:
        """Yield directories under root recursively.

        Args:
            root: Root reference to walk.
            max_depth: Maximum relative depth to traverse.

        Yields:
            FileRef: Directory references under `root`.
        """

    def open(self, ref: FileRef) -> BinaryIO:
        """Open a file reference for binary reads.

        Args:
            ref: File reference to open.

        Returns:
            BinaryIO: Readable binary file object.
        """

    def read_bytes(self, ref: FileRef, *, limit: int | None = None) -> bytes:
        """Read bytes from a reference.

        Args:
            ref: File reference to read.
            limit: Optional maximum bytes to read.

        Returns:
            bytes: File payload bytes.
        """

    def hash(self, ref: FileRef, algo: str = "sha256") -> str:
        """Compute a hash for a file reference.

        Args:
            ref: File reference to hash.
            algo: Hash algorithm name accepted by `hashlib`.

        Returns:
            str: Hex digest string.
        """

    def make_dir(
        self, ref: FileRef, *, parents: bool = True, exist_ok: bool = True
    ) -> FileRef:
        """Create a directory reference.

        Args:
            ref: Directory reference to create.
            parents: Whether to create missing parent directories.
            exist_ok: Whether an existing directory is allowed.

        Returns:
            FileRef: Created directory reference.
        """

    def move(self, src: FileRef, dst: FileRef, *, overwrite: bool = False) -> FileRef:
        """Move a reference to a destination.

        Args:
            src: Source reference.
            dst: Destination reference.
            overwrite: Whether to replace an existing destination.

        Returns:
            FileRef: Destination reference.
        """

    def copy(self, src: FileRef, dst: FileRef, *, overwrite: bool = False) -> FileRef:
        """Copy a reference to a destination.

        Args:
            src: Source reference.
            dst: Destination reference.
            overwrite: Whether to replace an existing destination.

        Returns:
            FileRef: Destination reference.
        """

    def delete(self, ref: FileRef) -> None:
        """Delete a file or directory reference.

        Args:
            ref: Reference to delete.
        """

    def join(self, root: FileRef, *parts: str) -> FileRef:
        """Join path parts under a root reference.

        Args:
            root: Root reference.
            *parts: Additional path segments.

        Returns:
            FileRef: Joined reference.
        """

    def parent(self, ref: FileRef) -> FileRef:
        """Return parent reference for a path.

        Args:
            ref: Child reference.

        Returns:
            FileRef: Parent reference.
        """

    def name_of(self, ref: FileRef) -> str:
        """Return basename for a reference.

        Args:
            ref: Reference to inspect.

        Returns:
            str: Basename component.
        """

    def watch(self, root: FileRef) -> Iterator[FileEvent]:
        """Yield filesystem events for a watched root.

        Args:
            root: Root reference to watch.

        Yields:
            FileEvent: Backend filesystem events.
        """

    def stop_watch(self) -> None:
        """Stop active watch stream."""
