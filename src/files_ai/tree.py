"""Folder tree snapshot helpers."""

from __future__ import annotations

from .storage import FileRef
from .storage import Files


def build_tree_snapshot(files: Files, root: FileRef, max_depth: int = 4) -> list[str]:
    """Return sorted folder paths under a root up to a max depth."""
    return sorted(ref.path for ref in files.walk_dirs(root, max_depth=max_depth))
