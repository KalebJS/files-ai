"""Stable file watcher that debounces incomplete writes."""

from __future__ import annotations

import queue
import threading
import time
from typing import Iterator

from .storage import FileRef
from .storage import Files

SKIP_SUFFIXES = (".tmp", ".crdownload")
SKIP_PREFIXES = (".", "~$")


class StableFileWatcher:
    """Yield stable file references from startup scans and watch events."""

    def __init__(self, files: Files, *, stabilize_seconds: float = 1.0) -> None:
        """Initialize watcher with storage backend and stabilization delay.

        Args:
            files: Storage backend that provides watch and stat operations.
            stabilize_seconds: Delay between file-size checks.
        """
        self.files = files
        self.stabilize_seconds = stabilize_seconds

    def startup_scan(self, dropzone: FileRef) -> Iterator[FileRef]:
        """Yield stable files already present in dropzone.

        Args:
            dropzone: Root directory to scan.

        Yields:
            FileRef: Stable non-skipped files under the dropzone.
        """
        for meta in self.files.walk(dropzone):
            if self.should_skip(meta.ref):
                continue
            if self.is_stable(meta.ref):
                yield meta.ref

    def iter_stable_events(
        self, dropzone: FileRef, *, include_directories: bool = False
    ) -> Iterator[FileRef]:
        """Yield stable file refs from filesystem events.

        Args:
            dropzone: Root directory to watch.
            include_directories: Whether to include directory events.

        Yields:
            FileRef: Stable file references for supported event kinds.
        """
        for event in self.files.watch(dropzone):
            if event.kind not in {"created", "modified", "moved"}:
                continue
            if self.should_skip(event.ref):
                continue
            if not self.files.exists(event.ref):
                continue
            meta = self.files.stat(event.ref)
            if meta.is_dir and include_directories:
                yield event.ref
                continue
            if self.is_stable(event.ref):
                yield event.ref

    def iter_stable_event_batches(
        self,
        dropzone: FileRef,
        *,
        quiet_seconds: float,
        include_directories: bool = False,
    ) -> Iterator[list[FileRef]]:
        """Yield event batches split by a quiet period with no new stable refs."""
        out_queue: queue.Queue[FileRef | None] = queue.Queue()

        def _producer() -> None:
            try:
                for ref in self.iter_stable_events(
                    dropzone, include_directories=include_directories
                ):
                    out_queue.put(ref)
            finally:
                out_queue.put(None)

        producer = threading.Thread(target=_producer, daemon=True)
        producer.start()
        batch: list[FileRef] = []

        while True:
            timeout = quiet_seconds if batch else 0.25
            try:
                item = out_queue.get(timeout=timeout)
            except queue.Empty:
                if batch:
                    yield _dedupe_refs(batch)
                    batch = []
                continue
            if item is None:
                if batch:
                    yield _dedupe_refs(batch)
                return
            batch.append(item)

    def stop(self) -> None:
        """Stop underlying backend watcher."""
        self.files.stop_watch()

    def is_stable(self, ref: FileRef) -> bool:
        """Return whether a file size remains stable across a short interval.

        Args:
            ref: File reference to check.

        Returns:
            bool: `True` when file size is unchanged and the target is not a directory.
        """
        if not self.files.exists(ref):
            return False
        first_meta = self.files.stat(ref)
        if first_meta.is_dir:
            return False
        first = first_meta.size
        time.sleep(self.stabilize_seconds)
        if not self.files.exists(ref):
            return False
        second_meta = self.files.stat(ref)
        if second_meta.is_dir:
            return False
        second = second_meta.size
        return first == second

    def should_skip(self, ref: FileRef) -> bool:
        """Return whether a file should be ignored.

        Args:
            ref: File reference to evaluate.

        Returns:
            bool: `True` when the filename matches skip prefixes or suffixes.
        """
        name = self.files.name_of(ref)
        if name == ".git":
            return False
        return name.startswith(SKIP_PREFIXES) or name.endswith(SKIP_SUFFIXES)


def _dedupe_refs(refs: list[FileRef]) -> list[FileRef]:
    """Deduplicate refs by path while preserving latest event order."""
    seen: dict[str, FileRef] = {}
    order: list[str] = []
    for ref in refs:
        if ref.path not in seen:
            order.append(ref.path)
        seen[ref.path] = ref
    return [seen[path] for path in order]
