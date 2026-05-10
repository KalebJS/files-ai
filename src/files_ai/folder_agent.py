"""Folder-level agent that decides move-as-module vs recurse."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any
from typing import Literal

from langchain.agents import create_agent
from langchain_ollama import ChatOllama
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import ValidationError
from pydantic import field_validator

from .agent import _configure_langsmith
from .config import Settings
from .storage import FileRef
from .storage import Files
from .tree import build_folder_snapshot_tree

FOLDER_SYSTEM_PROMPT = (
    "You decide whether a folder should move as one dependency-bound module.\n"
    "Return JSON only with keys:\n"
    '- action: "move_folder" or "recurse"\n'
    "- reasoning: short rationale\n"
    "- folder: destination folder under organized root "
    "(required when action=move_folder)\n"
    "- confidence: number in [0,1]\n"
    "- quarantine: boolean\n\n"
    "Rules:\n"
    "1) Move folders as one module only when files are interdependent.\n"
    "2) Recurse when children are independent documents/media/notes.\n"
    "3) Never recurse .git directories.\n"
    "4) Keep folder depth <= 4 and use safe names.\n"
    "4.1) For move_folder, output Johnny.Decimal Area/Category/ID path.\n"
    "     Example: 10-19 Life Admin/13 Money/13.02 W-2s\n"
    "4.2) Top-level areas are capped at 10 total: 00-09 through 90-99.\n"
    "4.3) Never create duplicate/overflow 90-99 areas.\n"
    "4.4) Prefer existing broad areas over creating narrow new areas.\n"
    "5) Set quarantine=true only for unsafe/suspicious content.\n"
    "6) If dependency is unclear, choose recurse.\n\n"
    "Dependency policy:\n"
    "- Dependency means files require each other to function or preserve "
    "meaning as a unit.\n"
    "- Strong evidence: manifests/lockfiles + source tree, repository "
    "metadata, app/project structures, build configs, package metadata.\n"
    "- Not enough evidence: same theme/category, same institution, same "
    "folder name, or semantically related standalone documents.\n\n"
    "Few-shot examples:\n"
    "Input:\n"
    "folder_name=Financial\n"
    "source_relative_dir=School\n"
    "children=file:Custom.pdf,file:Processed Information - FAFSA on the Web - "
    "Federal Student Aid.pdf\n"
    "Output:\n"
    '{"action":"recurse","reasoning":"documents are related by topic but are '
    'standalone files; dependency not proven","folder":"Unsorted",'
    '"confidence":0.9,"quarantine":false}\n\n'
    "Input:\n"
    "folder_name=tax-docs\n"
    "source_relative_dir=\n"
    "children=file:w2.pdf,file:receipt.pdf,file:summary.txt\n"
    "Output:\n"
    '{"action":"recurse","reasoning":"independent financial documents; recurse '
    'for per-file routing","folder":"Unsorted","confidence":0.92,'
    '"quarantine":false}\n\n'
    "Input:\n"
    "folder_name=my-app\n"
    "source_relative_dir=Code\n"
    "children=file:pyproject.toml,file:poetry.lock,dir:src,file:README.md\n"
    "Output:\n"
    '{"action":"move_folder","reasoning":"manifest and lockfile with source '
    'tree indicate interdependent project","folder":"Code/Projects",'
    '"confidence":0.95,"quarantine":false}\n\n'
    "Input:\n"
    "folder_name=.git\n"
    "source_relative_dir=my-app\n"
    "children=file:config,dir:objects,dir:refs\n"
    "Output:\n"
    '{"action":"move_folder","reasoning":".git should never be recursed",'
    '"folder":"Code/Repositories","confidence":1.0,"quarantine":false}\n'
)

NEVER_RECURSE_NAMES = {".git"}
DEPENDENCY_MARKERS = {
    "pyproject.toml",
    "requirements.txt",
    "setup.py",
    "poetry.lock",
    "package.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "cargo.toml",
    "go.mod",
    "pom.xml",
    "build.gradle",
    "cmakelists.txt",
    "makefile",
}
CODE_EXTENSIONS = {
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".java",
    ".kt",
    ".go",
    ".rs",
    ".cpp",
    ".c",
    ".h",
    ".hpp",
    ".cs",
    ".rb",
    ".php",
    ".swift",
}
INDEPENDENT_EXTENSIONS = {
    ".pdf",
    ".docx",
    ".txt",
    ".md",
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".heic",
    ".csv",
    ".xlsx",
    ".pptx",
}


class FolderAgentParseError(ValueError):
    """Raised when folder-agent output cannot be parsed."""


@dataclass(frozen=True)
class FolderAgent:
    """Folder routing agent container with shared model."""

    llm: ChatOllama


class FolderDecision(BaseModel):
    """Folder-level routing decision."""

    model_config = ConfigDict(frozen=True)

    action: Literal["move_folder", "recurse"] = "recurse"
    reasoning: str
    folder: str = "Unsorted"
    confidence: float
    quarantine: bool = False

    @field_validator("folder")
    @classmethod
    def _sanitize_folder(cls, folder: str) -> str:
        parts: list[str] = []
        for raw in folder.split("/"):
            clean = re.sub(r"[^a-zA-Z0-9 _.-]", "", raw).strip().strip(".")
            if clean:
                parts.append(clean)
        return "/".join(parts[:4]) or "Unsorted"

    @field_validator("confidence")
    @classmethod
    def _clamp_confidence(cls, confidence: float) -> float:
        return max(0.0, min(1.0, confidence))


class _FolderInspector:
    """Read-only folder-inspection tools exposed to the folder agent."""

    def __init__(self, files: Files, folder_ref: FileRef) -> None:
        self.files = files
        self.folder_ref = folder_ref

    def list_children(self, max_entries: int = 200, max_depth: int = 3) -> str:
        """List children in bounded tree-style output."""
        root_name = self.files.name_of(self.folder_ref) or self.folder_ref.path.rstrip(
            "/"
        )
        lines = [f"{root_name}/"]
        emitted = 0
        truncated = False

        def _walk(dir_ref: FileRef, prefix: str, depth: int) -> None:
            nonlocal emitted
            nonlocal truncated
            children = sorted(
                self.files.iterdir(dir_ref),
                key=lambda meta: self.files.name_of(meta.ref),
            )
            for index, meta in enumerate(children):
                if emitted >= max_entries:
                    truncated = True
                    return
                name = self.files.name_of(meta.ref)
                display = f"{name}/" if meta.is_dir else name
                connector = "└── " if index == len(children) - 1 else "├── "
                lines.append(f"{prefix}{connector}{display}")
                emitted += 1
                if not meta.is_dir:
                    continue
                if name in NEVER_RECURSE_NAMES:
                    continue
                if depth >= max_depth:
                    continue
                child_prefix = (
                    f"{prefix}{'    ' if index == len(children) - 1 else '│   '}"
                )
                _walk(meta.ref, child_prefix, depth + 1)
                if truncated:
                    return

        _walk(self.folder_ref, "", 1)
        if emitted == 0:
            lines.append("└── (empty)")
        if truncated:
            lines.append("...truncated...")
        return "\n".join(lines)

    def sample_file(self, relative_path: str, max_bytes: int = 2000) -> str:
        """Read a UTF-8 text sample from a folder-relative file."""
        safe = PurePosixPath(relative_path)
        if safe.is_absolute() or ".." in safe.parts:
            return "invalid relative path"
        target = self.files.join(self.folder_ref, relative_path)
        target_path = PurePosixPath(target.path)
        root_path = PurePosixPath(self.folder_ref.path)
        if root_path not in target_path.parents and target_path != root_path:
            return "path escapes folder"
        if not self.files.exists(target):
            return "missing file"
        meta = self.files.stat(target)
        if meta.is_dir:
            return "path is a directory"
        payload = self.files.read_bytes(target, limit=max_bytes)
        return payload.decode("utf-8", errors="ignore")

    def project_signals(self, max_entries: int = 300) -> str:
        """Return lightweight dependency/project signals."""
        names: list[str] = []
        code_count = 0
        independent_count = 0
        for idx, meta in enumerate(self.files.iterdir(self.folder_ref)):
            if idx >= max_entries:
                break
            name = self.files.name_of(meta.ref)
            names.append(name)
            if meta.is_dir and name in NEVER_RECURSE_NAMES:
                names.append("marker:.git")
            suffix = PurePosixPath(name).suffix.lower()
            if suffix in CODE_EXTENSIONS:
                code_count += 1
            if suffix in INDEPENDENT_EXTENSIONS:
                independent_count += 1
        found_markers = sorted(
            marker
            for marker in DEPENDENCY_MARKERS
            if marker in {n.lower() for n in names}
        )
        return (
            f"markers={found_markers}\n"
            f"code_count={code_count}\n"
            f"independent_count={independent_count}\n"
            f"child_count={len(names)}"
        )


def build_folder_agent(settings: Settings) -> FolderAgent:
    """Create folder-level decision agent with shared LLM."""
    _configure_langsmith(settings)
    llm = ChatOllama(
        model=settings.model,
        reasoning=settings.model_reasoning,
        base_url=settings.ollama_base_url,
        client_kwargs={
            "headers": {
                "Authorization": f"Bearer {settings.ollama_api_key.get_secret_value()}"
            }
        },
        temperature=0,
    )
    return FolderAgent(llm=llm)


def decide_folder_action(
    agent: FolderAgent,
    *,
    files: Files,
    folder_ref: FileRef,
    tree_snapshot: list[str],
    source_relative_dir: str = "",
    user_context: str = "",
) -> FolderDecision:
    """Decide whether to move folder as one module or recurse."""
    quick = _heuristic_decision(files=files, folder_ref=folder_ref)
    if quick is not None:
        return quick

    inspector = _FolderInspector(files, folder_ref)
    tree_block = build_folder_snapshot_tree(tree_snapshot)
    runtime_agent = create_agent(
        model=agent.llm,
        tools=[
            inspector.list_children,
            inspector.sample_file,
            inspector.project_signals,
        ],
        system_prompt=FOLDER_SYSTEM_PROMPT,
    )
    payload = {
        "messages": [
            {
                "role": "user",
                "content": (
                    "# Task\n"
                    "Decide whether this folder should move as a unit or recurse.\n\n"
                    "## Instructions\n"
                    "- Use tools before answering.\n"
                    "- `list_children` returns a bounded tree view.\n\n"
                    "## Folder metadata\n"
                    f"- **folder_name**: `{files.name_of(folder_ref)}`\n"
                    f"- **source_relative_dir**: `{source_relative_dir}`\n\n"
                    "## Existing tree\n"
                    "```json\n"
                    f"{tree_block}\n"
                    "```\n\n"
                    "## User context\n"
                    "```markdown\n"
                    f"{user_context[:4000]}\n"
                    "```\n"
                ),
            }
        ]
    }
    response = _invoke_agent(
        runtime_agent,
        payload,
        metadata={
            "path": folder_ref.path,
            "source_relative_dir": source_relative_dir or ".",
            "tree_size": len(tree_snapshot),
        },
    )
    content = _extract_content(response)
    raw = _extract_json_str(content)
    if raw is None:
        raise FolderAgentParseError(
            f"Folder agent response did not contain JSON: {content!r}"
        )
    try:
        return FolderDecision.model_validate_json(raw)
    except ValidationError as exc:
        raise FolderAgentParseError(
            f"Folder agent response failed schema validation: {content!r}"
        ) from exc


def _heuristic_decision(*, files: Files, folder_ref: FileRef) -> FolderDecision | None:
    """Return deterministic decisions for strong dependency/independence signals."""
    name = files.name_of(folder_ref)
    if name in NEVER_RECURSE_NAMES:
        return FolderDecision(
            action="move_folder",
            folder="Code/Repositories",
            reasoning=".git directories should never recurse",
            confidence=1.0,
            quarantine=False,
        )

    markers: set[str] = set()
    code_count = 0
    independent_count = 0
    child_count = 0
    file_count = 0
    for meta in files.iterdir(folder_ref):
        child_count += 1
        child_name = files.name_of(meta.ref)
        lower_name = child_name.lower()
        if lower_name in DEPENDENCY_MARKERS:
            markers.add(lower_name)
        if meta.is_dir and child_name in NEVER_RECURSE_NAMES:
            markers.add("repo-marker")
        if not meta.is_dir:
            file_count += 1
        suffix = PurePosixPath(child_name).suffix.lower()
        if suffix in CODE_EXTENSIONS:
            code_count += 1
        if suffix in INDEPENDENT_EXTENSIONS:
            independent_count += 1

    if markers:
        return FolderDecision(
            action="move_folder",
            folder="Code/Projects",
            reasoning="dependency markers indicate an interdependent project",
            confidence=0.95,
            quarantine=False,
        )

    if code_count >= 3 and code_count >= independent_count:
        return FolderDecision(
            action="move_folder",
            folder="Code/Projects",
            reasoning="source files indicate interdependent code project",
            confidence=0.82,
            quarantine=False,
        )

    if file_count > 0 and independent_count == file_count and code_count == 0:
        return FolderDecision(
            action="recurse",
            folder="Unsorted",
            reasoning="standalone document/media files with no dependency signals",
            confidence=0.9,
            quarantine=False,
        )

    if child_count and independent_count >= max(3, code_count * 2):
        return FolderDecision(
            action="recurse",
            folder="Unsorted",
            reasoning="mostly independent documents/media, recurse folder",
            confidence=0.86,
            quarantine=False,
        )

    return None


def _invoke_agent(
    agent: Any,
    payload: dict[str, Any],
    metadata: dict[str, str | int],
) -> Any:
    """Invoke agent with optional tracing metadata."""
    try:
        return agent.invoke(
            payload,
            config={
                "tags": ["folder-agent"],
                "metadata": metadata,
            },
        )
    except TypeError:
        return agent.invoke(payload)


def _extract_content(response: Any) -> str:
    """Extract text content from agent response."""
    if isinstance(response, dict):
        if "output" in response and isinstance(response["output"], str):
            return response["output"]
        messages = response.get("messages")
        if isinstance(messages, list) and messages:
            msg = messages[-1]
            if isinstance(msg, dict):
                return str(msg.get("content", ""))
            return str(getattr(msg, "content", ""))
    return str(response)


def _extract_json_str(content: str) -> str | None:
    """Extract JSON object payload from raw content."""
    content = content.strip()
    if not content:
        return None
    try:
        json.loads(content)
        return content
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if not match:
            return None
        payload = match.group(0)
        try:
            json.loads(payload)
            return payload
        except json.JSONDecodeError:
            return None
