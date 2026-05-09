"""Folder tree snapshot helpers."""

from __future__ import annotations

from pathlib import PurePosixPath

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


def build_upload_batch_tree(paths: list[str]) -> str:
    """Build a compact upload-tree string from dropzone-relative paths."""
    cleaned: list[str] = []
    for raw in paths:
        rel = raw.strip().lstrip("/")
        if rel:
            cleaned.append(rel)
    if not cleaned:
        return "(empty batch)"
    return _render_path_tree(sorted(set(cleaned)))


def build_tagged_destination_tree(
    files: Files,
    root: FileRef,
    *,
    new_file_paths: set[str],
    new_folder_paths: set[str],
    max_depth: int = 4,
    max_entries: int = 4000,
) -> str:
    """Build organized listing with `[NEW]` and `[NEW_FOLDER]` markers."""
    root_path = PurePosixPath(root.path)
    dir_lines: list[str] = []
    file_lines: list[str] = []

    for ref in files.walk_dirs(root, max_depth=max_depth):
        rel = PurePosixPath(ref.path).relative_to(root_path).as_posix()
        if not rel:
            continue
        tag = " [NEW_FOLDER]" if ref.path in new_folder_paths else ""
        dir_lines.append(f"- [DIR] {rel}/{tag}")

    for meta in files.walk(root):
        rel = PurePosixPath(meta.ref.path).relative_to(root_path).as_posix()
        if not rel:
            continue
        if len(PurePosixPath(rel).parts) > max_depth:
            continue
        tag = " [NEW]" if meta.ref.path in new_file_paths else ""
        file_lines.append(f"- [FILE] {rel}{tag}")

    lines = sorted(set(dir_lines)) + sorted(set(file_lines))
    lines = lines[:max_entries]
    if not lines:
        return "(empty organized tree)"
    return "\n".join(lines)


def _render_path_tree(paths: list[str], tags: dict[str, str] | None = None) -> str:
    """Render slash-separated relative paths to an indented tree string."""
    nodes: dict[str, list[str]] = {"": []}
    for path in paths:
        is_dir = path.endswith("/")
        clean = path.rstrip("/")
        parts = [part for part in clean.split("/") if part]
        prefix = ""
        for idx, part in enumerate(parts):
            final = idx == len(parts) - 1
            token = f"{part}/" if final and is_dir else part
            if prefix not in nodes:
                nodes[prefix] = []
            child_key = f"{prefix}/{token}".strip("/")
            if token not in nodes[prefix]:
                nodes[prefix].append(token)
            prefix = child_key
            if prefix not in nodes:
                nodes[prefix] = []

    for key in nodes:
        nodes[key].sort()

    tag_map = tags or {}
    lines: list[str] = []

    def _walk(prefix: str, depth: int) -> None:
        for child in nodes.get(prefix, []):
            key = f"{prefix}/{child}".strip("/")
            tag = tag_map.get(key, "")
            marker = f" {tag}" if tag else ""
            lines.append(f"{'  ' * depth}- {child}{marker}")
            _walk(key, depth + 1)

    _walk("", 0)
    return "\n".join(lines)
