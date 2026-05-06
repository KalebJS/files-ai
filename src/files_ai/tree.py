from __future__ import annotations

from .storage import FileRef
from .storage import Files


def build_tree_snapshot(files: Files, root: FileRef, max_depth: int = 4) -> list[str]:
    return sorted(ref.path for ref in files.walk_dirs(root, max_depth=max_depth))
