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
    """Shared dependencies used by organizer tools."""

    files: Files
    store: Store
    organized_root: FileRef
    quarantine_root: FileRef
    dry_run: bool


class OrganizerTools:
    """Domain operations for folder proposal and file moves."""

    def __init__(self, ctx: ToolContext) -> None:
        """Store tool dependencies."""
        self.ctx = ctx

    def list_tree(self, max_depth: int = 4) -> list[str]:
        """List organized-folder tree paths."""
        return sorted(
            ref.path
            for ref in self.ctx.files.walk_dirs(
                self.ctx.organized_root, max_depth=max_depth
            )
        )

    def propose_folder(self, label: str) -> str:
        """Resolve or create a folder from a semantic label."""
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
        """Move a file into a target organized folder."""
        dst_folder = self.ctx.files.join(self.ctx.organized_root, folder)
        return move_into_folder(
            files=self.ctx.files,
            store=self.ctx.store,
            src=src,
            folder=dst_folder,
            mime=mime,
            extracted_chars=extracted_chars,
            dry_run=self.ctx.dry_run,
        )

    def quarantine_file(
        self, src: FileRef, *, mime: str | None, extracted_chars: int
    ) -> MoveResult:
        """Move a file into quarantine."""
        return move_into_folder(
            files=self.ctx.files,
            store=self.ctx.store,
            src=src,
            folder=self.ctx.quarantine_root,
            mime=mime,
            extracted_chars=extracted_chars,
            dry_run=self.ctx.dry_run,
        )


def _canonical(value: str) -> str:
    """Normalize text into a canonical key."""
    return re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")


def _folderize(value: str) -> str:
    """Normalize free text into a folder path."""
    cleaned = re.sub(r"[^a-zA-Z0-9/_ -]", "", value).strip()
    if not cleaned:
        return "Unsorted"
    parts = [p.strip() for p in cleaned.split("/") if p.strip()]
    return "/".join(parts[:4]) or "Unsorted"
