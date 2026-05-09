"""Johnny.Decimal path validation and allocation helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath

from .storage import FileRef
from .storage import Files

AREA_PATTERN = re.compile(r"^(?P<start>\d{2})-(?P<end>\d{2})\s+(?P<label>.+)$")
CATEGORY_PATTERN = re.compile(r"^(?P<num>\d{2})\s+(?P<label>.+)$")
ID_PATTERN = re.compile(r"^(?P<cat>\d{2})\.(?P<num>\d{2})\s+(?P<label>.+)$")


@dataclass
class _Index:
    areas: dict[int, str]
    categories: dict[tuple[int, int], str]
    ids: dict[tuple[int, int, int], str]


def enforce_johnny_decimal_folder(*, files: Files, root: FileRef, folder: str) -> str:
    """Return a folder path normalized to Area/Category/ID shape."""
    index = _build_index(files=files, root=root)
    area_label, category_label, id_label = _extract_labels(folder)
    area_segment = _ensure_area(index=index, label=area_label)
    area_start = _parse_area(area_segment)[0]
    category_segment = _ensure_category(
        index=index, area_start=area_start, label=category_label
    )
    category_num = _parse_category(category_segment)[0]
    id_segment = _ensure_id(
        index=index,
        area_start=area_start,
        category_num=category_num,
        label=id_label,
    )
    return "/".join([area_segment, category_segment, id_segment])


def _build_index(*, files: Files, root: FileRef) -> _Index:
    areas: dict[int, str] = {}
    categories: dict[tuple[int, int], str] = {}
    ids: dict[tuple[int, int, int], str] = {}
    root_path = PurePosixPath(root.path)
    for ref in files.walk_dirs(root, max_depth=3):
        rel = PurePosixPath(ref.path).relative_to(root_path).as_posix()
        if not rel:
            continue
        parts = rel.split("/")
        if len(parts) >= 1:
            parsed_area = _parse_area(parts[0])
            if parsed_area is not None:
                areas.setdefault(parsed_area[0], parts[0])
        if len(parts) >= 2:
            parsed_area = _parse_area(parts[0])
            parsed_cat = _parse_category(parts[1])
            if parsed_area is not None and parsed_cat is not None:
                categories.setdefault((parsed_area[0], parsed_cat[0]), parts[1])
        if len(parts) >= 3:
            parsed_area = _parse_area(parts[0])
            parsed_cat = _parse_category(parts[1])
            parsed_id = _parse_id(parts[2])
            if (
                parsed_area is not None
                and parsed_cat is not None
                and parsed_id is not None
                and parsed_id[0] == parsed_cat[0]
            ):
                ids.setdefault(
                    (parsed_area[0], parsed_cat[0], parsed_id[1]),
                    parts[2],
                )
    return _Index(areas=areas, categories=categories, ids=ids)


def _extract_labels(folder: str) -> tuple[str, str, str]:
    raw_parts = [p.strip() for p in folder.split("/") if p.strip()]
    cleaned = [_clean_label(_strip_numeric_prefix(part)) for part in raw_parts]
    if len(cleaned) >= 3:
        return cleaned[0], cleaned[1], cleaned[2]
    if len(cleaned) == 2:
        return cleaned[0], cleaned[1], cleaned[1]
    if len(cleaned) == 1:
        return "General", cleaned[0], cleaned[0]
    return "General", "General", "Inbox"


def _ensure_area(*, index: _Index, label: str) -> str:
    wanted = _normalize_name(label)
    for start, segment in sorted(index.areas.items()):
        parsed = _parse_area(segment)
        if parsed is None:
            continue
        if _normalize_name(parsed[1]) == wanted:
            return segment
    slot = _next_area_slot(index)
    segment = f"{slot:02d}-{slot + 9:02d} {label}"
    index.areas[slot] = segment
    return segment


def _ensure_category(*, index: _Index, area_start: int, label: str) -> str:
    wanted = _normalize_name(label)
    for (area, num), segment in sorted(index.categories.items()):
        if area != area_start:
            continue
        parsed = _parse_category(segment)
        if parsed is None:
            continue
        if _normalize_name(parsed[1]) == wanted:
            return segment
    slot = _next_category_slot(index=index, area_start=area_start)
    if slot is None:
        new_area = _next_area_slot(index)
        area_segment = f"{new_area:02d}-{new_area + 9:02d} {label}"
        index.areas[new_area] = area_segment
        area_start = new_area
        slot = area_start
    segment = f"{slot:02d} {label}"
    index.categories[(area_start, slot)] = segment
    return segment


def _ensure_id(*, index: _Index, area_start: int, category_num: int, label: str) -> str:
    wanted = _normalize_name(label)
    for (area, cat, num), segment in sorted(index.ids.items()):
        if area != area_start or cat != category_num:
            continue
        parsed = _parse_id(segment)
        if parsed is None:
            continue
        if _normalize_name(parsed[2]) == wanted:
            return segment
    slot = _next_id_slot(index=index, area_start=area_start, category_num=category_num)
    if slot is None:
        next_category = _next_category_slot(index=index, area_start=area_start)
        if next_category is None:
            next_area = _next_area_slot(index)
            index.areas[next_area] = f"{next_area:02d}-{next_area + 9:02d} {label}"
            area_start = next_area
            category_num = area_start
        else:
            category_num = next_category
        index.categories[(area_start, category_num)] = f"{category_num:02d} {label}"
        slot = 1
    segment = f"{category_num:02d}.{slot:02d} {label}"
    index.ids[(area_start, category_num, slot)] = segment
    return segment


def _next_area_slot(index: _Index) -> int:
    for value in [10, 20, 30, 40, 50, 60, 70, 80, 90, 0]:
        if value not in index.areas:
            return value
    return 90


def _next_category_slot(*, index: _Index, area_start: int) -> int | None:
    used = {
        number
        for (area, number), _ in index.categories.items()
        if area == area_start and area_start <= number <= area_start + 9
    }
    for value in range(area_start, area_start + 10):
        if value not in used:
            return value
    return None


def _next_id_slot(*, index: _Index, area_start: int, category_num: int) -> int | None:
    used = {
        num
        for (area, cat, num), _ in index.ids.items()
        if area == area_start and cat == category_num
    }
    for value in range(1, 100):
        if value not in used:
            return value
    return None


def _parse_area(value: str) -> tuple[int, str] | None:
    match = AREA_PATTERN.match(value)
    if not match:
        return None
    start = int(match.group("start"))
    end = int(match.group("end"))
    if end != start + 9:
        return None
    return start, _clean_label(match.group("label"))


def _parse_category(value: str) -> tuple[int, str] | None:
    match = CATEGORY_PATTERN.match(value)
    if not match:
        return None
    return int(match.group("num")), _clean_label(match.group("label"))


def _parse_id(value: str) -> tuple[int, int, str] | None:
    match = ID_PATTERN.match(value)
    if not match:
        return None
    return (
        int(match.group("cat")),
        int(match.group("num")),
        _clean_label(match.group("label")),
    )


def _strip_numeric_prefix(value: str) -> str:
    area = AREA_PATTERN.match(value)
    if area:
        return area.group("label")
    category = CATEGORY_PATTERN.match(value)
    if category:
        return category.group("label")
    item_id = ID_PATTERN.match(value)
    if item_id:
        return item_id.group("label")
    return value


def _clean_label(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9 _.-]", "", value).strip().strip(".")
    return cleaned or "General"


def _normalize_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()
