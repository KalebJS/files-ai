"""User-maintained context loading utilities."""

from __future__ import annotations

from .storage import FileRef
from .storage import Files
from .storage import NotFound

CONTEXT_FILENAME = "CONTEXT.md"
DEFAULT_CONTEXT_TEMPLATE = """# About the filesystem user
- This archive belongs to a filesystem user (individual, household, or team).
- The user values quick retrieval, clarity, and long-term consistency.

# Filesystem expectations
- Keep organization predictable and stable over time.
- Prefer specific destinations over broad catch-all folders.
- Reuse existing Johnny.Decimal structure when it is a clear fit.

# Filename formatting instructions
- Keep filenames readable and concise.
- Preserve meaningful details such as dates, version hints, or identifiers.
- Avoid unsafe characters and keep separators consistent.
"""


def load_user_context(
    *, files: Files, dropzone: FileRef, max_bytes: int = 16384
) -> str:
    """Load context markdown located adjacent to dropzone.

    If dropzone is `/dropzone`, this reads `/CONTEXT.md`.
    If dropzone is `/data/dropzone`, this reads `/data/CONTEXT.md`.
    """
    context_ref = files.join(files.parent(dropzone), CONTEXT_FILENAME)
    if not files.exists(context_ref):
        return _create_default_context(
            files=files, ref=context_ref, max_bytes=max_bytes
        )
    try:
        meta = files.stat(context_ref)
    except NotFound:
        return _create_default_context(
            files=files, ref=context_ref, max_bytes=max_bytes
        )
    if meta.is_dir:
        return ""
    payload = files.read_bytes(context_ref, limit=max(0, int(max_bytes)))
    return payload.decode("utf-8", errors="ignore").strip()


def _create_default_context(*, files: Files, ref: FileRef, max_bytes: int) -> str:
    """Create a starter CONTEXT.md and return bounded content."""
    encoded = DEFAULT_CONTEXT_TEMPLATE.encode("utf-8")
    try:
        files.write_bytes(ref, encoded, overwrite=False)
    except Exception:  # noqa: BLE001
        return ""
    payload = files.read_bytes(ref, limit=max(0, int(max_bytes)))
    return payload.decode("utf-8", errors="ignore").strip()
