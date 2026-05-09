"""Post-batch reviewer that can refine organization with constrained tools."""

from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from langchain.agents import create_agent
from langchain_ollama import ChatOllama

from .config import Settings
from .johnny_decimal import enforce_johnny_decimal_folder
from .storage import FileRef
from .storage import Files
from .store import FileRow
from .store import Store
from .tree import build_tagged_destination_tree
from .tree import build_upload_batch_tree

REVIEW_SYSTEM_PROMPT = """You review one completed upload batch.
Use tools to improve final organization quality.
You may:
- read move history
- create folders
- retry items back to dropzone for rerouting
- move items to existing folders
Rules:
- Keep folder depth <= 4.
- Folder paths must follow Johnny.Decimal Area/Category/ID.
- Never use path traversal.
- Prefer minimal, high-confidence changes.
- Return JSON only: {"summary":"short summary of changes and rationale"}.
"""


@dataclass(frozen=True)
class BatchReviewResult:
    """Result of one post-batch review."""

    summary: str
    retry_refs: list[FileRef]
    action_count: int


class BatchReviewTools:
    """Tool surface exposed to the post-batch reviewer."""

    def __init__(
        self,
        *,
        files: Files,
        store: Store,
        batch_id: int,
        model: str,
        organized_root: FileRef,
        dropzone_root: FileRef,
        max_actions: int,
    ) -> None:
        """Initialize reviewer tools with shared runtime context."""
        self.files = files
        self.store = store
        self.batch_id = batch_id
        self.model = model
        self.organized_root = organized_root
        self.dropzone_root = dropzone_root
        self.max_actions = max_actions
        self._lock = threading.RLock()
        self.action_count = 0
        self.retry_refs: list[FileRef] = []

    def read_move_history(self, limit: int = 100) -> str:
        """Read recent move-history rows for this batch."""
        bounded = max(1, min(int(limit), 300))
        rows = self.store.list_move_history(batch_id=self.batch_id, limit=bounded)
        return json.dumps(rows, ensure_ascii=False)

    def create_folder(self, path: str, reason: str = "") -> str:
        """Create a folder under organized root and track it."""
        with self._lock:
            if not self._consume_action():
                return "action_limit_reached"
            rel = self._coerce_jd_folder(path)
            if not rel:
                return "invalid_folder_path"
            dst = self.files.join(self.organized_root, rel)
            self.files.make_dir(dst, parents=True, exist_ok=True)
            self.store.add_move_history(
                batch_id=self.batch_id,
                file_id=None,
                action="create_folder",
                src_path=None,
                dst_path=dst.path,
                reason=reason,
                model=self.model,
            )
            return dst.path

    def retry_item(self, file_id_or_path: str, reason: str = "") -> str:
        """Move an existing item back to dropzone for rerouting."""
        with self._lock:
            if not self._consume_action():
                return "action_limit_reached"
            row, src_path = self._resolve_target(file_id_or_path)
            if not src_path:
                return "target_not_found"
            src = FileRef(backend=self.files.name, path=src_path)
            if not self.files.exists(src):
                return "target_missing_on_disk"
            dst = _next_available_destination(
                files=self.files,
                folder=self.dropzone_root,
                name=self.files.name_of(src),
            )
            self.files.make_dir(self.dropzone_root, parents=True, exist_ok=True)
            self.files.move(src, dst)
            if row is not None:
                self.store.update_file_destination(row.id, dst.path)
            self.store.add_move_history(
                batch_id=self.batch_id,
                file_id=row.id if row is not None else None,
                action="retry_item",
                src_path=src.path,
                dst_path=dst.path,
                reason=reason,
                model=self.model,
            )
            self.retry_refs.append(dst)
            return dst.path

    def move_item_to_existing_folder(
        self, file_id_or_path: str, folder: str, reason: str = ""
    ) -> str:
        """Move an existing item to an existing organized folder."""
        with self._lock:
            if not self._consume_action():
                return "action_limit_reached"
            rel = self._coerce_jd_folder(folder)
            if not rel:
                return "invalid_folder_path"
            dst_folder = self.files.join(self.organized_root, rel)
            if (
                not self.files.exists(dst_folder)
                or not self.files.stat(dst_folder).is_dir
            ):
                return "destination_folder_missing"
            row, src_path = self._resolve_target(file_id_or_path)
            if not src_path:
                return "target_not_found"
            src = FileRef(backend=self.files.name, path=src_path)
            if not self.files.exists(src):
                return "target_missing_on_disk"
            dst = _next_available_destination(
                files=self.files,
                folder=dst_folder,
                name=self.files.name_of(src),
            )
            self.files.move(src, dst)
            if row is not None:
                self.store.update_file_destination(row.id, dst.path)
            self.store.add_move_history(
                batch_id=self.batch_id,
                file_id=row.id if row is not None else None,
                action="move_item_to_existing_folder",
                src_path=src.path,
                dst_path=dst.path,
                reason=reason,
                model=self.model,
            )
            return dst.path

    def _coerce_jd_folder(self, folder: str) -> str:
        safe = _sanitize_relative_folder(folder)
        if not safe:
            return ""
        return enforce_johnny_decimal_folder(
            files=self.files,
            root=self.organized_root,
            folder=safe,
        )

    def _consume_action(self) -> bool:
        if self.action_count >= self.max_actions:
            return False
        self.action_count += 1
        return True

    def _resolve_target(self, token: str) -> tuple[FileRow | None, str | None]:
        value = token.strip()
        if not value:
            return None, None
        row: FileRow | None = None
        if value.isdigit():
            row = self.store.get_file_by_id(int(value))
        else:
            lookup = value if value.startswith("/") else f"/{value}"
            row = self.store.get_file_by_destination(lookup)
        if row is not None and row.dst_path:
            return row, row.dst_path
        if value.startswith("/"):
            return None, value
        return None, f"/{value}"


def run_batch_reviewer(
    *,
    files: Files,
    store: Store,
    settings: Settings,
    organized_root: FileRef,
    dropzone_root: FileRef,
    batch_id: int,
    batch_source_paths: list[str],
    new_file_paths: set[str],
    new_folder_paths: set[str],
    user_context: str = "",
) -> BatchReviewResult:
    """Run post-batch reviewer and return summary plus retry refs."""
    tools = BatchReviewTools(
        files=files,
        store=store,
        batch_id=batch_id,
        model=settings.batch_review_model,
        organized_root=organized_root,
        dropzone_root=dropzone_root,
        max_actions=settings.batch_review_max_actions,
    )
    upload_tree = build_upload_batch_tree(batch_source_paths)
    destination_tree = build_tagged_destination_tree(
        files,
        organized_root,
        new_file_paths=new_file_paths,
        new_folder_paths=new_folder_paths,
        max_depth=settings.max_depth,
    )
    agent = create_agent(
        model=ChatOllama(
            model=settings.batch_review_model,
            base_url=settings.ollama_base_url,
            client_kwargs={
                "headers": {
                    "Authorization": (
                        f"Bearer {settings.ollama_api_key.get_secret_value()}"
                    )
                }
            },
            temperature=0,
        ),
        tools=[
            tools.read_move_history,
            tools.create_folder,
            tools.retry_item,
            tools.move_item_to_existing_folder,
        ],
        system_prompt=REVIEW_SYSTEM_PROMPT,
    )
    payload = {
        "messages": [
            {
                "role": "user",
                "content": (
                    "# Task\n"
                    "Review this batch and improve organization if needed.\n\n"
                    "## Batch metadata\n"
                    f"- **batch_id**: `{batch_id}`\n\n"
                    "## Upload batch tree\n"
                    "```json\n"
                    f"{upload_tree}\n"
                    "```\n\n"
                    "## Updated destination tree\n"
                    "```json\n"
                    f"{destination_tree}\n"
                    "```\n\n"
                    "## User context\n"
                    "```markdown\n"
                    f"{user_context[:4000]}\n"
                    "```\n"
                ),
            }
        ]
    }
    response = agent.invoke(payload)
    summary = _extract_summary(response)
    if not summary:
        summary = "Post-batch reviewer completed without a structured summary."
    return BatchReviewResult(
        summary=summary,
        retry_refs=_dedupe_retry_refs(tools.retry_refs),
        action_count=tools.action_count,
    )


def _sanitize_relative_folder(folder: str) -> str:
    """Normalize folder into a safe relative path."""
    parts: list[str] = []
    for raw in folder.split("/"):
        clean = re.sub(r"[^a-zA-Z0-9 _.-]", "", raw).strip().strip(".")
        if clean:
            parts.append(clean)
    return "/".join(parts[:4])


def _next_available_destination(*, files: Files, folder: FileRef, name: str) -> FileRef:
    """Return first non-conflicting destination path in folder."""
    candidate = files.join(folder, name)
    if not files.exists(candidate):
        return candidate
    pure = PurePosixPath(name)
    suffix = "".join(pure.suffixes)
    stem = name[: -len(suffix)] if suffix else name
    idx = 1
    while True:
        candidate = files.join(folder, f"{stem}-{idx}{suffix}")
        if not files.exists(candidate):
            return candidate
        idx += 1


def _extract_summary(response: Any) -> str:
    """Extract summary field from agent response content."""
    content = ""
    if isinstance(response, dict):
        if "output" in response and isinstance(response["output"], str):
            content = response["output"]
        elif "messages" in response and isinstance(response["messages"], list):
            for message in reversed(response["messages"]):
                value = getattr(message, "content", None)
                if isinstance(value, str) and value.strip():
                    content = value
                    break
    if not content:
        value = getattr(response, "content", None)
        if isinstance(value, str):
            content = value
    if not content:
        return ""
    match = re.search(r"\{.*\}", content, flags=re.DOTALL)
    if not match:
        return ""
    try:
        payload = json.loads(match.group(0))
    except json.JSONDecodeError:
        return ""
    summary = payload.get("summary", "")
    return str(summary).strip() if isinstance(summary, str) else ""


def _dedupe_retry_refs(refs: list[FileRef]) -> list[FileRef]:
    """Deduplicate retry refs by path preserving first-seen order."""
    seen: set[str] = set()
    output: list[FileRef] = []
    for ref in refs:
        if ref.path in seen:
            continue
        seen.add(ref.path)
        output.append(ref)
    return output
