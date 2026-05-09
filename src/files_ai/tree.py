"""Folder tree snapshot helpers."""

from __future__ import annotations

import json

from .storage import FileRef
from .storage import Files


def build_tree_snapshot(files: Files, root: FileRef, max_depth: int = 4) -> list[str]:
    """Return sorted organized tree paths (folders + files) up to max depth.

    Args:
        files: Storage backend.
        root: Root directory reference.
        max_depth: Maximum depth to include.

    Returns:
        list[str]: Sorted relative paths.
    """
    snapshot: set[str] = set()
    root_path_len = len(root.path)
    for ref in files.walk_dirs(root, max_depth=max_depth):
        rel = ref.path[root_path_len:].lstrip("/")
        if rel:
            parts = [part for part in rel.split("/") if part]
            if parts:
                snapshot.add("/".join(parts[: min(len(parts), 3)]))
    for meta in files.walk(root):
        rel = meta.ref.path[root_path_len:].lstrip("/")
        if not rel:
            continue
        parts = [part for part in rel.split("/") if part]
        if len(parts) >= 4 and len(parts) <= max_depth:
            snapshot.add(rel)
    return sorted(snapshot)


def build_folder_snapshot_tree(paths: list[str]) -> str:
    """Build a JSON tree object from folder paths only."""
    cleaned_folders: list[str] = []
    cleaned_files: list[str] = []
    for raw in paths:
        rel = raw.strip().strip("/")
        if rel:
            parts = [part for part in rel.split("/") if part]
            if len(parts) >= 4:
                cleaned_files.append(rel)
            else:
                cleaned_folders.append(rel)
    if not cleaned_folders and not cleaned_files:
        return "{}"
    tree = _render_johnny_decimal_tree(
        sorted(set(cleaned_files)),
        folder_paths=sorted(set(cleaned_folders)),
    )
    return json.dumps(tree, ensure_ascii=False, indent=2)


def _render_johnny_decimal_tree(
    file_paths: list[str],
    *,
    folder_paths: list[str] | None = None,
    folder_tags: dict[str, str] | None = None,
    file_tags: dict[str, str] | None = None,
    max_files_per_id: int = 3,
) -> dict[str, object]:
    """Render Area/Category/ID tree with ID leaves as file lists."""
    folder_tag_map = folder_tags or {}
    file_tag_map = file_tags or {}
    tree: dict[str, object] = {}
    files_by_id: dict[tuple[str, str, str], set[str]] = {}

    for folder_path in sorted(set(folder_paths or [])):
        parts = [part for part in folder_path.split("/") if part]
        if not parts:
            continue
        area_key = _tagged(parts[0], folder_tag_map.get(parts[0], ""))
        area_node = tree.setdefault(area_key, {})
        assert isinstance(area_node, dict)
        if len(parts) < 2:
            continue

        category_path = "/".join(parts[:2])
        category_key = _tagged(parts[1], folder_tag_map.get(category_path, ""))
        category_node = area_node.setdefault(category_key, {})
        assert isinstance(category_node, dict)
        if len(parts) < 3:
            continue

        id_path = "/".join(parts[:3])
        id_key = _tagged(parts[2], folder_tag_map.get(id_path, ""))
        category_node.setdefault(id_key, [])
        files_by_id.setdefault((area_key, category_key, id_key), set())

    for file_path in sorted(set(file_paths)):
        parts = [part for part in file_path.split("/") if part]
        if len(parts) < 4:
            continue
        area_path = parts[0]
        category_path = "/".join(parts[:2])
        id_path = "/".join(parts[:3])
        area_key = _tagged(parts[0], folder_tag_map.get(area_path, ""))
        category_key = _tagged(parts[1], folder_tag_map.get(category_path, ""))
        id_key = _tagged(parts[2], folder_tag_map.get(id_path, ""))
        file_key = _tagged(parts[-1], file_tag_map.get(file_path, ""))

        area_node = tree.setdefault(area_key, {})
        assert isinstance(area_node, dict)
        category_node = area_node.setdefault(category_key, {})
        assert isinstance(category_node, dict)
        category_node.setdefault(id_key, [])
        files_by_id.setdefault((area_key, category_key, id_key), set()).add(file_key)

    for (area_key, category_key, id_key), id_files in files_by_id.items():
        area_node = tree.get(area_key)
        assert isinstance(area_node, dict)
        category_node = area_node.get(category_key)
        assert isinstance(category_node, dict)
        category_node[id_key] = _top_files_with_ellipsis(
            id_files, max_files=max_files_per_id
        )

    return tree


def _top_files_with_ellipsis(files: set[str], *, max_files: int) -> list[str]:
    ordered = sorted(files, reverse=True)
    if len(ordered) <= max_files:
        return ordered
    return [*ordered[:max_files], "..."]


def _tagged(value: str, tag: str) -> str:
    if not tag:
        return value
    return f"{value} {tag}"
