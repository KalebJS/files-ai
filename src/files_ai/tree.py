"""Folder tree snapshot helpers."""

from __future__ import annotations

from .storage import FileRef
from .storage import Files


def build_tree_snapshot(files: Files, root: FileRef, max_depth: int = 4) -> list[str]:
    """Return sorted folder paths under a root up to a max depth.

    Args:
        files: Storage backend.
        root: Root directory reference.
        max_depth: Maximum depth to include.

    Returns:
        list[str]: Sorted relative folder paths.
    """
    snapshot = []
    root_path_len = len(root.path)
    for ref in files.walk_dirs(root, max_depth=max_depth):
        rel = ref.path[root_path_len:].lstrip("/")
        if rel:
            snapshot.append(rel)
    return sorted(snapshot)
