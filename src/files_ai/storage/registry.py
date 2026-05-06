from __future__ import annotations

from typing import Any

from .base import Files
from .local import LocalFiles


def get_files(name: str, **opts: Any) -> Files:
    backend = name.lower().strip()
    if backend == "local":
        return LocalFiles(**opts)
    raise ValueError(f"Unsupported backend: {name}")
