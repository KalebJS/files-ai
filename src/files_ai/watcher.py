"""Stable file watcher that debounces incomplete writes."""

from __future__ import annotations

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
