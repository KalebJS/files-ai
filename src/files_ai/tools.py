"""Helper tools used by file-organization orchestration."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .mover import MoveResult
from .mover import move_into_folder
from .storage import FileRef
from .storage import Files
from .store import Store


@dataclass
class ToolContext:
    """Shared dependencies used by organizer tools.

    Attributes:
        files: Storage backend.
        store: Persistent metadata store.
        organized_root: Root directory for organized files.
        quarantine_root: Root directory for quarantined files.
        dry_run: Whether move operations should avoid filesystem writes.
    """

    files: Files
    store: Store
    organized_root: FileRef
    quarantine_root: FileRef
    dry_run: bool


class OrganizerTools:
    """Domain operations for folder proposal and file moves."""

    def __init__(self, ctx: ToolContext) -> None:
        """Store tool dependencies.

        Args:
            ctx: Shared tool dependencies.
        """
        self.ctx = ctx

    def list_tree(self, max_depth: int = 4) -> list[str]:
        """List organized-folder tree paths.

        Args:
            max_depth: Maximum folder depth to include.

        Returns:
            list[str]: Sorted folder paths under organized root.
        """
        return sorted(
            ref.path
            for ref in self.ctx.files.walk_dirs(
                self.ctx.organized_root, max_depth=max_depth
            )
        )

    def propose_folder(self, label: str) -> str:
        """Resolve or create a folder from a semantic label.

        Args:
            label: Free-form folder label.

        Returns:
            str: Resolved folder path.
        """
        canonical = _canonical(label)
        cached = self.ctx.store.get_folder(canonical)
        if cached:
            return cached
        folder = _folderize(label)
        self.ctx.store.upsert_folder(canonical, folder)
        return folder

    def move_file(
        self, src: FileRef, folder: str, *, mime: str | None, extracted_chars: int
    ) -> MoveResult:
        """Move a file into a target organized folder.

        Args:
            src: Source file reference.
            folder: Destination folder relative path.
            mime: MIME type when known.
            extracted_chars: Number of extracted text characters.

        Returns:
            MoveResult: Outcome of the move attempt.
        """
        return self.move_ref(src, folder, mime=mime, extracted_chars=extracted_chars)

    def move_ref(
        self, src: FileRef, folder: str, *, mime: str | None, extracted_chars: int
    ) -> MoveResult:
        """Move a file or directory into a target organized folder.

        Args:
            src: Source reference.
            folder: Destination folder relative path.
            mime: MIME type when known.
            extracted_chars: Number of extracted text characters.

        Returns:
            MoveResult: Outcome of the move attempt.
        """
        dst_folder = self.ctx.files.join(self.ctx.organized_root, folder)
        return move_into_folder(
            files=self.ctx.files,
            store=self.ctx.store,
            src=src,
            folder=dst_folder,
            duplicate_folder=self.ctx.files.join(
                self.ctx.quarantine_root, "duplicates"
            ),
            mime=mime,
            extracted_chars=extracted_chars,
            dry_run=self.ctx.dry_run,
        )

    def quarantine_file(
        self, src: FileRef, *, mime: str | None, extracted_chars: int
    ) -> MoveResult:
        """Move a file into quarantine.

        Args:
            src: Source file reference.
            mime: MIME type when known.
            extracted_chars: Number of extracted text characters.

        Returns:
            MoveResult: Outcome of the quarantine move.
        """
        return move_into_folder(
            files=self.ctx.files,
            store=self.ctx.store,
            src=src,
            folder=self.ctx.quarantine_root,
            duplicate_folder=self.ctx.files.join(
                self.ctx.quarantine_root, "duplicates"
            ),
            mime=mime,
            extracted_chars=extracted_chars,
            dry_run=self.ctx.dry_run,
        )


def _canonical(value: str) -> str:
    """Normalize text into a canonical key.

    Args:
        value: Free-form text.

    Returns:
        str: Lowercased underscore-delimited key.
    """
    return re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")


def _folderize(value: str) -> str:
    """Normalize free text into a folder path.

    Args:
        value: Free-form folder text.

    Returns:
        str: Sanitized folder path limited to four segments.
    """
    cleaned = re.sub(r"[^a-zA-Z0-9/_ -]", "", value).strip()
    if not cleaned:
        return "Unsorted"
    parts = [p.strip() for p in cleaned.split("/") if p.strip()]
    return "/".join(parts[:4]) or "Unsorted"
