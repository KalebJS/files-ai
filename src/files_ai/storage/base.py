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
    backend: str
    path: str
    id: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class FileMeta:
    ref: FileRef
    size: int
    mtime: datetime
    is_dir: bool
    mime: str | None = None
    sha256: str | None = None


@dataclass(frozen=True, slots=True)
class FileEvent:
    kind: str
    ref: FileRef
    src_ref: FileRef | None = None


class StorageError(Exception):
    pass


class NotFound(StorageError):
    pass


class Conflict(StorageError):
    pass


class Files(Protocol):
    name: str

    def exists(self, ref: FileRef) -> bool: ...
    def stat(self, ref: FileRef) -> FileMeta: ...
    def walk(self, root: FileRef) -> Iterator[FileMeta]: ...
    def walk_dirs(self, root: FileRef, max_depth: int = 4) -> Iterator[FileRef]: ...
    def open(self, ref: FileRef) -> BinaryIO: ...
    def read_bytes(self, ref: FileRef, *, limit: int | None = None) -> bytes: ...
    def hash(self, ref: FileRef, algo: str = "sha256") -> str: ...
    def make_dir(
        self, ref: FileRef, *, parents: bool = True, exist_ok: bool = True
    ) -> FileRef: ...
    def move(
        self, src: FileRef, dst: FileRef, *, overwrite: bool = False
    ) -> FileRef: ...
    def copy(
        self, src: FileRef, dst: FileRef, *, overwrite: bool = False
    ) -> FileRef: ...
    def delete(self, ref: FileRef) -> None: ...
    def join(self, root: FileRef, *parts: str) -> FileRef: ...
    def parent(self, ref: FileRef) -> FileRef: ...
    def name_of(self, ref: FileRef) -> str: ...
    def watch(self, root: FileRef) -> Iterator[FileEvent]: ...
    def stop_watch(self) -> None: ...
