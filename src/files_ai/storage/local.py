"""Local filesystem implementation of the Files protocol."""

from __future__ import annotations

import hashlib
import os
import queue
import shutil
import threading
from datetime import datetime
from datetime import timezone
from pathlib import Path
from pathlib import PurePosixPath
from typing import BinaryIO
from typing import Iterator

from watchdog.events import FileSystemEvent
from watchdog.events import FileSystemEventHandler
from watchdog.events import FileSystemMovedEvent
from watchdog.observers.polling import PollingObserver

from .base import Conflict
from .base import FileEvent
from .base import FileMeta
from .base import FileRef
from .base import NotFound


class _QueueHandler(FileSystemEventHandler):
    """Watchdog event adapter that pushes normalized FileEvent objects."""

    def __init__(self, owner: "LocalFiles", out_queue: queue.Queue[FileEvent]) -> None:
        """Store backend and output queue references."""
        self.owner = owner
        self.out_queue = out_queue

    def on_created(self, event: FileSystemEvent) -> None:
        """Handle create events."""
        self._push("created", event.src_path)

    def on_modified(self, event: FileSystemEvent) -> None:
        """Handle modify events."""
        self._push("modified", event.src_path)

    def on_deleted(self, event: FileSystemEvent) -> None:
        """Handle delete events."""
        self._push("deleted", event.src_path)

    def on_moved(self, event: FileSystemMovedEvent) -> None:
        """Handle move events."""
        dst_ref = self.owner._from_abs_path(Path(event.dest_path))
        src_ref = self.owner._from_abs_path(Path(event.src_path))
        if dst_ref is None:
            return
        self.out_queue.put(FileEvent(kind="moved", ref=dst_ref, src_ref=src_ref))

    def _push(self, kind: str, src_path: str) -> None:
        """Convert a raw path to FileRef and queue the event."""
        ref = self.owner._from_abs_path(Path(src_path))
        if ref is None:
            return
        self.out_queue.put(FileEvent(kind=kind, ref=ref))


class LocalFiles:
    """Files backend for one rooted local directory tree."""

    name = "local"

    def __init__(self, root: str | Path, poll_interval_seconds: float = 1.0) -> None:
        """Initialize backend root and watcher state."""
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.poll_interval_seconds = poll_interval_seconds
        self._event_queue: queue.Queue[FileEvent] = queue.Queue()
        self._observer: PollingObserver | None = None
        self._watch_lock = threading.Lock()
        self._stop_event = threading.Event()

    def exists(self, ref: FileRef) -> bool:
        """Return whether a path exists."""
        return self._to_abs_path(ref).exists()

    def stat(self, ref: FileRef) -> FileMeta:
        """Return metadata for a path."""
        target = self._to_abs_path(ref)
        if not target.exists():
            raise NotFound(ref.path)
        s = target.stat()
        return FileMeta(
            ref=ref,
            size=s.st_size,
            mtime=datetime.fromtimestamp(s.st_mtime, tz=timezone.utc),
            is_dir=target.is_dir(),
        )

    def walk(self, root: FileRef) -> Iterator[FileMeta]:
        """Recursively yield file metadata under root."""
        root_abs = self._to_abs_path(root)
        if not root_abs.exists():
            return
        for current_root, _, files in os.walk(root_abs):
            for name in files:
                path = Path(current_root) / name
                ref = self._from_abs_path(path)
                if ref is None:
                    continue
                yield self.stat(ref)

    def walk_dirs(self, root: FileRef, max_depth: int = 4) -> Iterator[FileRef]:
        """Recursively yield directory refs under root."""
        root_abs = self._to_abs_path(root)
        if not root_abs.exists():
            return
        for current_root, dirs, _ in os.walk(root_abs):
            cur = Path(current_root)
            depth = len(cur.relative_to(root_abs).parts)
            if depth >= max_depth:
                dirs[:] = []
                continue
            for name in dirs:
                child = cur / name
                ref = self._from_abs_path(child)
                if ref:
                    yield ref

    def open(self, ref: FileRef) -> BinaryIO:
        """Open a file for binary reading."""
        return self._to_abs_path(ref).open("rb")

    def read_bytes(self, ref: FileRef, *, limit: int | None = None) -> bytes:
        """Read bytes from a file, optionally capped."""
        with self.open(ref) as file_obj:
            return file_obj.read() if limit is None else file_obj.read(limit)

    def hash(self, ref: FileRef, algo: str = "sha256") -> str:
        """Compute content hash for a file."""
        hasher = hashlib.new(algo)
        with self.open(ref) as file_obj:
            while chunk := file_obj.read(1024 * 1024):
                hasher.update(chunk)
        return hasher.hexdigest()

    def make_dir(
        self, ref: FileRef, *, parents: bool = True, exist_ok: bool = True
    ) -> FileRef:
        """Create a directory and return its ref."""
        self._to_abs_path(ref).mkdir(parents=parents, exist_ok=exist_ok)
        return ref

    def move(self, src: FileRef, dst: FileRef, *, overwrite: bool = False) -> FileRef:
        """Move a file, using copy+unlink fallback when needed."""
        self._validate_refs(src, dst)
        src_abs = self._to_abs_path(src)
        dst_abs = self._to_abs_path(dst)
        if dst_abs.exists() and not overwrite:
            raise Conflict(dst.path)
        dst_abs.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.replace(src_abs, dst_abs)
        except OSError:
            shutil.copy2(src_abs, dst_abs)
            with dst_abs.open("rb+") as file_obj:
                file_obj.flush()
                os.fsync(file_obj.fileno())
            src_abs.unlink()
        return dst

    def copy(self, src: FileRef, dst: FileRef, *, overwrite: bool = False) -> FileRef:
        """Copy a file."""
        self._validate_refs(src, dst)
        src_abs = self._to_abs_path(src)
        dst_abs = self._to_abs_path(dst)
        if dst_abs.exists() and not overwrite:
            raise Conflict(dst.path)
        dst_abs.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_abs, dst_abs)
        return dst

    def delete(self, ref: FileRef) -> None:
        """Delete a file or directory tree."""
        target = self._to_abs_path(ref)
        if not target.exists():
            return
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()

    def join(self, root: FileRef, *parts: str) -> FileRef:
        """Join path parts under a root reference."""
        pure = PurePosixPath(root.path)
        for part in parts:
            pure = pure / part
        return FileRef(backend=self.name, path="/" + str(pure).lstrip("/"))

    def parent(self, ref: FileRef) -> FileRef:
        """Return the parent reference."""
        pure = PurePosixPath(ref.path)
        return FileRef(backend=self.name, path="/" + str(pure.parent).lstrip("/"))

    def name_of(self, ref: FileRef) -> str:
        """Return the basename for a file reference."""
        return PurePosixPath(ref.path).name

    def watch(self, root: FileRef) -> Iterator[FileEvent]:
        """Yield filesystem events for a watched root."""
        root_abs = self._to_abs_path(root)
        with self._watch_lock:
            if self._observer is None:
                self._stop_event.clear()
                observer = PollingObserver(timeout=self.poll_interval_seconds)
                handler = _QueueHandler(self, self._event_queue)
                observer.schedule(handler, str(root_abs), recursive=True)
                observer.start()
                self._observer = observer
        while not self._stop_event.is_set():
            try:
                event = self._event_queue.get(timeout=0.25)
            except queue.Empty:
                continue
            yield event

    def stop_watch(self) -> None:
        """Stop an active watcher."""
        with self._watch_lock:
            self._stop_event.set()
            if self._observer is not None:
                self._observer.stop()
                self._observer.join(timeout=2.0)
                self._observer = None

    def _validate_refs(self, src: FileRef, dst: FileRef) -> None:
        """Validate that refs target this backend."""
        if src.backend != self.name or dst.backend != self.name:
            raise Conflict("backend mismatch")

    def _to_abs_path(self, ref: FileRef) -> Path:
        """Resolve a FileRef into an absolute path under backend root."""
        if ref.backend != self.name:
            raise Conflict(f"unsupported backend {ref.backend}")
        rel = ref.path.lstrip("/")
        target = (self.root / rel).resolve()
        if self.root not in target.parents and target != self.root:
            raise Conflict(f"path escapes root: {ref.path}")
        return target

    def _from_abs_path(self, path: Path) -> FileRef | None:
        """Convert absolute path to FileRef if inside backend root."""
        try:
            rel = path.resolve().relative_to(self.root)
        except ValueError:
            return None
        return FileRef(backend=self.name, path="/" + rel.as_posix())
