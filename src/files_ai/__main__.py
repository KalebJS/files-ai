"""Service entrypoint for continuous file organization."""

from __future__ import annotations

import argparse
import signal
from collections import deque
from pathlib import PurePosixPath

import structlog

from .agent import AgentDecision
from .agent import AgentProtocol
from .agent import build_agent
from .agent import decide_folder
from .config import Settings
from .config import get_settings
from .extract import extract_file
from .folder_agent import FolderAgent
from .folder_agent import FolderDecision
from .folder_agent import build_folder_agent
from .folder_agent import decide_folder_action
from .logging import configure_logging
from .storage import FileRef
from .storage import NotFound
from .storage import get_files
from .store import Store
from .tools import OrganizerTools
from .tools import ToolContext
from .tree import build_tree_snapshot
from .watcher import StableFileWatcher


def main() -> None:
    """Run organizer process in once or watch mode."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()

    settings = get_settings()
    configure_logging(settings.log_level)
    log = structlog.get_logger("files_ai")

    files = get_files(
        settings.backend,
        poll_interval_seconds=settings.poll_interval_seconds,
        **settings.backend_opts,
    )
    dropzone = FileRef(backend=files.name, path=settings.dropzone)
    organized = FileRef(backend=files.name, path=settings.organized)
    quarantine = FileRef(backend=files.name, path=settings.quarantine)
    files.make_dir(dropzone)
    files.make_dir(organized)
    files.make_dir(quarantine)

    store = Store(settings.state_db)
    tools = OrganizerTools(
        ToolContext(
            files=files,
            store=store,
            organized_root=organized,
            quarantine_root=quarantine,
            dry_run=settings.dry_run,
        )
    )
    watcher = StableFileWatcher(files)
    agent = build_agent(settings)
    folder_agent = build_folder_agent(settings)
    stopped = False

    def _stop(*_: object) -> None:
        nonlocal stopped
        stopped = True
        watcher.stop()

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    try:
        for meta in tools.ctx.files.iterdir(dropzone):
            if watcher.should_skip(meta.ref):
                continue
            ref = _with_dropzone_metadata(meta.ref, dropzone)
            _process_ref(
                ref,
                dropzone=dropzone,
                settings=settings,
                tools=tools,
                file_agent=agent,
                folder_agent=folder_agent,
                watcher=watcher,
            )
        if args.once:
            return
        for ref in watcher.iter_stable_events(dropzone, include_directories=True):
            if stopped:
                break
            ref = _with_dropzone_metadata(ref, dropzone)
            _process_ref(
                ref,
                dropzone=dropzone,
                settings=settings,
                tools=tools,
                file_agent=agent,
                folder_agent=folder_agent,
                watcher=watcher,
            )
    finally:
        watcher.stop()
        store.close()
        log.info("shutdown")


def _process_ref(
    ref: FileRef,
    *,
    dropzone: FileRef,
    settings: Settings,
    tools: OrganizerTools,
    file_agent: AgentProtocol,
    folder_agent: FolderAgent,
    watcher: StableFileWatcher,
) -> None:
    """Process a file or directory reference."""
    if watcher.should_skip(ref):
        return
    try:
        meta = tools.ctx.files.stat(ref)
    except NotFound:
        return
    if meta.is_dir:
        _process_directory(
            ref=ref,
            dropzone=dropzone,
            settings=settings,
            tools=tools,
            file_agent=file_agent,
            folder_agent=folder_agent,
            watcher=watcher,
        )
        return
    if watcher.is_stable(ref):
        _process_file(ref, settings=settings, tools=tools, agent=file_agent)


def _process_file(
    ref: FileRef, *, settings: Settings, tools: OrganizerTools, agent: AgentProtocol
) -> None:
    """Process one file end-to-end and persist decision metadata.

    Args:
        ref: Source file reference.
        settings: Runtime settings.
        tools: Organizer tool facade.
        agent: Routing agent with an `invoke` interface.
    """
    log = structlog.get_logger("files_ai.processor").bind(
        path=ref.path,
        source_rel_dir=ref.extra.get("dropzone_relative_dir", ""),
    )
    try:
        if tools.ctx.files.stat(ref).is_dir:
            log.info("skipped_directory")
            return
    except NotFound:
        log.info("skipped_missing")
        return
    extraction = extract_file(
        tools.ctx.files,
        ref,
        max_bytes=settings.extract_max_bytes,
        ocr_enabled=settings.ocr_enabled,
    )
    snapshot = build_tree_snapshot(
        tools.ctx.files, tools.ctx.organized_root, max_depth=settings.max_depth
    )
    decision = decide_folder(
        agent,
        filename=tools.ctx.files.name_of(ref),
        extracted_text=extraction.text,
        tree_snapshot=snapshot,
        source_relative_dir=str(ref.extra.get("dropzone_relative_dir", "")),
    )
    result = _apply_decision(
        ref=ref,
        decision=decision,
        tools=tools,
        mime=extraction.mime,
        extracted_chars=len(extraction.text),
    )
    if result.file_id is not None:
        tools.ctx.store.add_decision(
            result.file_id,
            reasoning=decision.reasoning,
            tools_called="move_file" if not decision.quarantine else "quarantine_file",
            model=settings.model,
        )
    log.info(
        "processed",
        destination=(result.destination.path if result.destination else None),
        duplicate=result.duplicate,
        dry_run=result.dry_run,
        tier=extraction.tier,
        confidence=decision.confidence,
    )


def _process_directory(
    *,
    ref: FileRef,
    dropzone: FileRef,
    settings: Settings,
    tools: OrganizerTools,
    file_agent: AgentProtocol,
    folder_agent: FolderAgent,
    watcher: StableFileWatcher,
) -> None:
    """Process one directory by either moving it or recursing children."""
    log = structlog.get_logger("files_ai.processor").bind(
        path=ref.path,
        source_rel_dir=ref.extra.get("dropzone_relative_dir", ""),
    )
    try:
        if not tools.ctx.files.stat(ref).is_dir:
            return
    except NotFound:
        return
    snapshot = build_tree_snapshot(
        tools.ctx.files, tools.ctx.organized_root, max_depth=settings.max_depth
    )
    decision = decide_folder_action(
        folder_agent,
        files=tools.ctx.files,
        folder_ref=ref,
        tree_snapshot=snapshot,
        source_relative_dir=str(ref.extra.get("dropzone_relative_dir", "")),
    )
    if decision.action == "recurse":
        log.info("folder_recurse", confidence=decision.confidence)
        _recurse_directory(
            ref=ref,
            dropzone=dropzone,
            settings=settings,
            tools=tools,
            file_agent=file_agent,
            folder_agent=folder_agent,
            watcher=watcher,
        )
        return
    result = _apply_folder_decision(
        ref=ref,
        decision=decision,
        tools=tools,
    )
    if result.file_id is not None:
        tools.ctx.store.add_decision(
            result.file_id,
            reasoning=decision.reasoning,
            tools_called=(
                "move_folder" if not decision.quarantine else "quarantine_folder"
            ),
            model=settings.model,
        )
    log.info(
        "folder_processed",
        destination=(result.destination.path if result.destination else None),
        duplicate=result.duplicate,
        dry_run=result.dry_run,
        confidence=decision.confidence,
    )


def _recurse_directory(
    *,
    ref: FileRef,
    dropzone: FileRef,
    settings: Settings,
    tools: OrganizerTools,
    file_agent: AgentProtocol,
    folder_agent: FolderAgent,
    watcher: StableFileWatcher,
) -> None:
    """Recursively process a directory's children with folder decisions."""
    pending: deque[FileRef] = deque(meta.ref for meta in tools.ctx.files.iterdir(ref))
    while pending:
        child = _with_dropzone_metadata(pending.popleft(), dropzone)
        if watcher.should_skip(child):
            continue
        try:
            meta = tools.ctx.files.stat(child)
        except NotFound:
            continue
        if not meta.is_dir:
            if watcher.is_stable(child):
                _process_file(child, settings=settings, tools=tools, agent=file_agent)
            continue
        snapshot = build_tree_snapshot(
            tools.ctx.files, tools.ctx.organized_root, max_depth=settings.max_depth
        )
        decision = decide_folder_action(
            folder_agent,
            files=tools.ctx.files,
            folder_ref=child,
            tree_snapshot=snapshot,
            source_relative_dir=str(child.extra.get("dropzone_relative_dir", "")),
        )
        if decision.action == "recurse":
            pending.extend(meta.ref for meta in tools.ctx.files.iterdir(child))
            continue
        result = _apply_folder_decision(
            ref=child,
            decision=decision,
            tools=tools,
        )
        if result.file_id is not None:
            tools.ctx.store.add_decision(
                result.file_id,
                reasoning=decision.reasoning,
                tools_called=(
                    "move_folder" if not decision.quarantine else "quarantine_folder"
                ),
                model=settings.model,
            )


def _with_dropzone_metadata(ref: FileRef, dropzone: FileRef) -> FileRef:
    """Attach dropzone-relative folder metadata to a file reference.

    Args:
        ref: File reference to enrich.
        dropzone: Dropzone root reference.

    Returns:
        FileRef: New file reference with `dropzone_relative_dir` in `extra`.
    """
    rel_dir = ""
    try:
        rel_path = PurePosixPath(ref.path).relative_to(PurePosixPath(dropzone.path))
        if str(rel_path.parent) != ".":
            rel_dir = rel_path.parent.as_posix()
    except ValueError:
        rel_dir = ""
    extra = dict(ref.extra)
    extra["dropzone_relative_dir"] = rel_dir
    return FileRef(backend=ref.backend, path=ref.path, id=ref.id, extra=extra)


def _apply_decision(
    *,
    ref: FileRef,
    decision: AgentDecision,
    tools: OrganizerTools,
    mime: str | None,
    extracted_chars: int,
):
    """Apply routing decision by moving file or quarantining it.

    Args:
        ref: Source file reference.
        decision: Routing decision from the agent.
        tools: Organizer tool facade.
        mime: MIME type when known.
        extracted_chars: Number of extracted text characters.

    Returns:
        MoveResult: Move/quarantine operation result.
    """
    if decision.quarantine:
        return tools.quarantine_file(ref, mime=mime, extracted_chars=extracted_chars)
    folder = tools.propose_folder(decision.folder)
    parts = [part for part in PurePosixPath(folder).parts if part not in {"", "/"}]
    root_name = PurePosixPath(tools.ctx.organized_root.path).name
    if parts and parts[0] == root_name:
        parts = parts[1:]
    normalized = "/".join(parts[:4]) or "Unsorted"
    return tools.move_file(ref, normalized, mime=mime, extracted_chars=extracted_chars)


def _apply_folder_decision(
    *,
    ref: FileRef,
    decision: FolderDecision,
    tools: OrganizerTools,
):
    """Apply folder decision by moving folder or quarantining it."""
    if decision.quarantine:
        return tools.quarantine_file(ref, mime="inode/directory", extracted_chars=0)
    folder = tools.propose_folder(decision.folder)
    parts = [part for part in PurePosixPath(folder).parts if part not in {"", "/"}]
    root_name = PurePosixPath(tools.ctx.organized_root.path).name
    if parts and parts[0] == root_name:
        parts = parts[1:]
    normalized = "/".join(parts[:4]) or "Unsorted"
    return tools.move_ref(ref, normalized, mime="inode/directory", extracted_chars=0)


if __name__ == "__main__":
    main()
