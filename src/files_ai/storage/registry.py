"""Backend registry and constructor helpers."""

from __future__ import annotations

from typing import Any

from .base import Files
from .local import LocalFiles


def get_files(name: str, **opts: Any) -> Files:
    """Build a `Files` backend from configured name and options.

    Args:
        name: Backend name.
        **opts: Backend-specific constructor options.

    Returns:
        Files: Instantiated backend implementation.

    Raises:
        ValueError: If backend name is unsupported.
    """
    backend = name.lower().strip()
    if backend == "local":
        return LocalFiles(**opts)
    raise ValueError(f"Unsupported backend: {name}")
