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
        """Initialize watcher with storage backend and stabilization delay."""
        self.files = files
        self.stabilize_seconds = stabilize_seconds

    def startup_scan(self, dropzone: FileRef) -> Iterator[FileRef]:
        """Yield stable files already present in dropzone."""
        for meta in self.files.walk(dropzone):
            if self._should_skip(meta.ref):
                continue
            if self._is_stable(meta.ref):
                yield meta.ref

    def iter_stable_events(self, dropzone: FileRef) -> Iterator[FileRef]:
        """Yield stable file refs from filesystem events."""
        for event in self.files.watch(dropzone):
            if event.kind not in {"created", "modified", "moved"}:
                continue
            if self._should_skip(event.ref):
                continue
            if self._is_stable(event.ref):
                yield event.ref

    def stop(self) -> None:
        """Stop underlying backend watcher."""
        self.files.stop_watch()

    def _is_stable(self, ref: FileRef) -> bool:
        """Return whether a file size remains stable across a short interval."""
        if not self.files.exists(ref):
            return False
        first = self.files.stat(ref).size
        time.sleep(self.stabilize_seconds)
        if not self.files.exists(ref):
            return False
        second = self.files.stat(ref).size
        return first == second

    def _should_skip(self, ref: FileRef) -> bool:
        """Return whether a file should be ignored."""
        name = self.files.name_of(ref)
        return name.startswith(SKIP_PREFIXES) or name.endswith(SKIP_SUFFIXES)
