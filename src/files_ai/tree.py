"""Folder tree snapshot helpers."""

from __future__ import annotations

import json
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


def build_folder_snapshot_tree(paths: list[str]) -> str:
    """Build a JSON tree object from folder paths only."""
    cleaned: list[str] = []
    for raw in paths:
        rel = raw.strip().strip("/")
        if rel:
            cleaned.append(rel)
    if not cleaned:
        return "{}"
    tree = _render_johnny_decimal_tree([], folder_paths=sorted(set(cleaned)))
    return json.dumps(tree, ensure_ascii=False, indent=2)


def build_upload_batch_tree(paths: list[str]) -> str:
    """Build a JSON upload-tree from dropzone-relative paths."""
    cleaned: list[str] = []
    for raw in paths:
        rel = raw.strip().lstrip("/")
        if rel:
            cleaned.append(rel)
    if not cleaned:
        return "{}"
    tree = _render_tree_object(sorted(set(cleaned)))
    return json.dumps(tree, ensure_ascii=False, indent=2)


def build_tagged_destination_tree(
    files: Files,
    root: FileRef,
    *,
    new_file_paths: set[str],
    new_folder_paths: set[str],
    max_depth: int = 4,
    max_entries: int = 4000,
) -> str:
    """Build JSON organized tree with `[NEW]` and `[NEW_FOLDER]` markers."""
    root_path = PurePosixPath(root.path)
    dir_paths: list[str] = []
    file_paths: list[str] = []
    folder_tags: dict[str, str] = {}
    file_tags: dict[str, str] = {}

    for ref in files.walk_dirs(root, max_depth=max_depth):
        rel = PurePosixPath(ref.path).relative_to(root_path).as_posix()
        if not rel:
            continue
        dir_paths.append(rel)
        if ref.path in new_folder_paths:
            folder_tags[rel] = "[NEW_FOLDER]"

    for meta in files.walk(root):
        rel = PurePosixPath(meta.ref.path).relative_to(root_path).as_posix()
        if not rel:
            continue
        if len(PurePosixPath(rel).parts) > max_depth:
            continue
        file_paths.append(rel)
        if meta.ref.path in new_file_paths:
            file_tags[rel] = "[NEW]"

    all_dirs = sorted(set(dir_paths))[:max_entries]
    all_files = sorted(set(file_paths))[:max_entries]
    if not all_dirs and not all_files:
        return "{}"
    tree = _render_johnny_decimal_tree(
        all_files,
        folder_paths=all_dirs,
        folder_tags=folder_tags,
        file_tags=file_tags,
    )
    return json.dumps(tree, ensure_ascii=False, indent=2)


def _render_johnny_decimal_tree(
    file_paths: list[str],
    *,
    folder_paths: list[str] | None = None,
    folder_tags: dict[str, str] | None = None,
    file_tags: dict[str, str] | None = None,
    max_files_per_id: int = 5,
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


def _render_tree_object(
    file_paths: list[str],
    *,
    folder_paths: list[str] | None = None,
    folder_tags: dict[str, str] | None = None,
    file_tags: dict[str, str] | None = None,
) -> dict[str, list[object]]:
    """Render slash-separated paths to nested JSON folder objects."""
    folder_tag_map = folder_tags or {}
    file_tag_map = file_tags or {}
    node = _new_node()
    for folder_path in folder_paths or []:
        _ensure_node_path(node, folder_path, folder_tag_map)
    for file_path in file_paths:
        parts = [part for part in file_path.split("/") if part]
        if not parts:
            continue
        if len(parts) == 1:
            tagged = _tagged(parts[0], file_tag_map.get(parts[0], ""))
            files = node["files"]
            assert isinstance(files, set)
            files.add(tagged)
            continue
        parent = _ensure_node_path(node, "/".join(parts[:-1]), folder_tag_map)
        tagged = _tagged(parts[-1], file_tag_map.get(file_path, ""))
        files = parent["files"]
        assert isinstance(files, set)
        files.add(tagged)
    return _root_to_output(node)


def _new_node() -> dict[str, object]:
    return {"folders": {}, "files": set()}


def _ensure_node_path(
    node: dict[str, object],
    folder_path: str,
    folder_tags: dict[str, str],
) -> dict[str, object]:
    parts = [part for part in folder_path.split("/") if part]
    built: list[str] = []
    current = node
    for part in parts:
        built.append(part)
        tagged = _tagged(part, folder_tags.get("/".join(built), ""))
        folders = current["folders"]
        assert isinstance(folders, dict)
        child = folders.get(tagged)
        if child is None:
            child = _new_node()
            folders[tagged] = child
        assert isinstance(child, dict)
        current = child
    return current


def _root_to_output(node: dict[str, object]) -> dict[str, list[object]]:
    output: dict[str, list[object]] = {}
    folders = node["folders"]
    files = node["files"]
    assert isinstance(folders, dict)
    assert isinstance(files, set)
    for folder_name in sorted(folders):
        child_node = folders[folder_name]
        assert isinstance(child_node, dict)
        output[folder_name] = _node_children(child_node)
    if files:
        output["ROOT"] = sorted(files)
    return output


def _node_children(node: dict[str, object]) -> list[object]:
    folders = node["folders"]
    files = node["files"]
    assert isinstance(folders, dict)
    assert isinstance(files, set)
    children: list[object] = []
    for folder_name in sorted(folders):
        child_node = folders[folder_name]
        assert isinstance(child_node, dict)
        children.append({folder_name: _node_children(child_node)})
    children.extend(sorted(files))
    return children


def _tagged(value: str, tag: str) -> str:
    if not tag:
        return value
    return f"{value} {tag}"
