"""User-maintained context loading utilities."""

from __future__ import annotations

from .storage import FileRef
from .storage import Files
from .storage import NotFound

CONTEXT_FILENAME = "CONTEXT.md"


def load_user_context(
    *, files: Files, dropzone: FileRef, max_bytes: int = 16384
) -> str:
    """Load context markdown located adjacent to dropzone.

    If dropzone is `/dropzone`, this reads `/CONTEXT.md`.
    If dropzone is `/data/dropzone`, this reads `/data/CONTEXT.md`.
    """
    context_ref = files.join(files.parent(dropzone), CONTEXT_FILENAME)
    if not files.exists(context_ref):
        return ""
    try:
        meta = files.stat(context_ref)
    except NotFound:
        return ""
    if meta.is_dir:
        return ""
    payload = files.read_bytes(context_ref, limit=max(0, int(max_bytes)))
    return payload.decode("utf-8", errors="ignore").strip()
