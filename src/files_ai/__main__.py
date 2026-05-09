"""Service entrypoint for continuous file organization."""

from __future__ import annotations

import argparse
import json
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
from .context import load_user_context
from .extract import extract_file
from .folder_agent import FolderAgent
from .folder_agent import FolderDecision
from .folder_agent import build_folder_agent
from .folder_agent import decide_folder_action
from .johnny_decimal import enforce_johnny_decimal_folder
from .logging import configure_logging
from .storage import FileRef
from .storage import Files
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
        startup_refs = [
            _with_dropzone_metadata(meta.ref, dropzone)
            for meta in tools.ctx.files.iterdir(dropzone)
            if not watcher.should_skip(meta.ref)
        ]
        _process_batch(
            refs=startup_refs,
            mode="startup",
            dropzone=dropzone,
            settings=settings,
            tools=tools,
            file_agent=agent,
            folder_agent=folder_agent,
            watcher=watcher,
        )
        if args.once:
            return
        for refs in watcher.iter_stable_event_batches(
            dropzone,
            quiet_seconds=settings.watch_quiet_seconds,
            include_directories=True,
        ):
            if stopped:
                break
            _process_batch(
                refs=[_with_dropzone_metadata(ref, dropzone) for ref in refs],
                mode="watch",
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
    batch_id: int | None = None,
    user_context: str = "",
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
            batch_id=batch_id,
            user_context=user_context,
        )
        return
    if watcher.is_stable(ref):
        _process_file(
            ref,
            dropzone=dropzone,
            settings=settings,
            tools=tools,
            agent=file_agent,
            batch_id=batch_id,
            user_context=user_context,
        )


def _process_batch(
    *,
    refs: list[FileRef],
    mode: str,
    dropzone: FileRef,
    settings: Settings,
    tools: OrganizerTools,
    file_agent: AgentProtocol,
    folder_agent: FolderAgent,
    watcher: StableFileWatcher,
) -> None:
    """Process a batch of refs and persist batch summary."""
    if not refs:
        return
    user_context = load_user_context(
        files=tools.ctx.files,
        dropzone=dropzone,
        max_bytes=settings.context_max_bytes,
    )
    batch_id = tools.ctx.store.start_batch(mode=mode)
    for ref in refs:
        _process_ref(
            ref,
            dropzone=dropzone,
            settings=settings,
            tools=tools,
            file_agent=file_agent,
            folder_agent=folder_agent,
            watcher=watcher,
            batch_id=batch_id,
            user_context=user_context,
        )
    tools.ctx.store.finish_batch(
        batch_id,
        status="completed",
        summary="Batch processing completed.",
    )


def _process_file(
    ref: FileRef,
    *,
    dropzone: FileRef,
    settings: Settings,
    tools: OrganizerTools,
    agent: AgentProtocol,
    batch_id: int | None = None,
    user_context: str = "",
) -> None:
    """Process one file end-to-end and persist decision metadata.

    Args:
        ref: Source file reference.
        dropzone: Dropzone root reference.
        settings: Runtime settings.
        tools: Organizer tool facade.
        agent: Routing agent with an `invoke` interface.
        batch_id: Optional batch id used for move-history tracking.
        user_context: User-maintained context included in agent prompts.
    """
    log = structlog.get_logger("files_ai.processor").bind(
        path=ref.path,
        source_rel_dir=ref.extra.get("dropzone_relative_dir", ""),
    )
    original_filename = tools.ctx.files.name_of(ref)
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
        user_context=user_context,
    )
    result = _apply_decision(
        ref=ref,
        decision=decision,
        tools=tools,
        target_filename=decision.filename,
        mime=extraction.mime,
        extracted_chars=len(extraction.text),
    )
    final_filename = (
        PurePosixPath(result.destination.path).name
        if result.destination is not None
        else None
    )
    rename_requested = decision.filename is not None
    renamed = (
        final_filename is not None
        and final_filename != original_filename
        and not result.duplicate
    )
    if result.destination is not None and not result.dry_run:
        _prune_dropzone_ancestors(
            files=tools.ctx.files,
            ref=ref,
            dropzone=dropzone,
        )
    if result.file_id is not None:
        tools.ctx.store.add_decision(
            result.file_id,
            reasoning=decision.reasoning,
            tools_called="move_file" if not decision.quarantine else "quarantine_file",
            model=settings.model,
        )
    if batch_id is not None:
        action = "quarantine_file" if decision.quarantine else "move_file"
        if result.duplicate:
            action = "duplicate_file"
        tools.ctx.store.add_move_history(
            batch_id=batch_id,
            file_id=result.file_id,
            action=action,
            src_path=ref.path,
            dst_path=result.destination.path
            if result.destination is not None
            else None,
            reason=decision.reasoning,
            model=settings.model,
            metadata=json.dumps(
                {
                    "original_filename": original_filename,
                    "requested_filename": decision.filename,
                    "final_filename": final_filename,
                    "rename_requested": rename_requested,
                    "renamed": renamed,
                },
                ensure_ascii=False,
            ),
        )
    log.info(
        "processed",
        destination=(result.destination.path if result.destination else None),
        duplicate=result.duplicate,
        dry_run=result.dry_run,
        tier=extraction.tier,
        confidence=decision.confidence,
        rename_requested=rename_requested,
        renamed=renamed,
        filename=final_filename,
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
    batch_id: int | None = None,
    user_context: str = "",
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
        user_context=user_context,
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
            batch_id=batch_id,
            user_context=user_context,
        )
        if not tools.ctx.dry_run:
            _prune_dropzone_ancestors(
                files=tools.ctx.files,
                ref=ref,
                dropzone=dropzone,
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
    if batch_id is not None:
        action = "quarantine_folder" if decision.quarantine else "move_folder"
        if result.duplicate:
            action = "duplicate_folder"
        tools.ctx.store.add_move_history(
            batch_id=batch_id,
            file_id=result.file_id,
            action=action,
            src_path=ref.path,
            dst_path=result.destination.path
            if result.destination is not None
            else None,
            reason=decision.reasoning,
            model=settings.model,
        )
    if result.destination is not None and not result.dry_run:
        _prune_dropzone_ancestors(files=tools.ctx.files, ref=ref, dropzone=dropzone)
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
    batch_id: int | None = None,
    user_context: str = "",
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
                _process_file(
                    child,
                    dropzone=dropzone,
                    settings=settings,
                    tools=tools,
                    agent=file_agent,
                    batch_id=batch_id,
                    user_context=user_context,
                )
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
            user_context=user_context,
        )
        if decision.action == "recurse":
            pending.extend(meta.ref for meta in tools.ctx.files.iterdir(child))
            continue
        result = _apply_folder_decision(
            ref=child,
            decision=decision,
            tools=tools,
        )
        if result.destination is not None and not result.dry_run:
            _prune_dropzone_ancestors(
                files=tools.ctx.files,
                ref=child,
                dropzone=dropzone,
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
        if batch_id is not None:
            action = "quarantine_folder" if decision.quarantine else "move_folder"
            if result.duplicate:
                action = "duplicate_folder"
            tools.ctx.store.add_move_history(
                batch_id=batch_id,
                file_id=result.file_id,
                action=action,
                src_path=child.path,
                dst_path=(
                    result.destination.path if result.destination is not None else None
                ),
                reason=decision.reasoning,
                model=settings.model,
            )


def _prune_dropzone_ancestors(*, files: Files, ref: FileRef, dropzone: FileRef) -> None:
    """Remove empty ancestors up to but not including the dropzone root."""
    current = files.parent(ref)
    dropzone_path = PurePosixPath(dropzone.path)
    while True:
        current_path = PurePosixPath(current.path)
        if current_path == dropzone_path:
            return
        if dropzone_path not in current_path.parents:
            return
        if not files.exists(current):
            current = files.parent(current)
            continue
        if not files.stat(current).is_dir:
            return
        if any(True for _ in files.iterdir(current)):
            return
        files.delete(current)
        current = files.parent(current)


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
    target_filename: str | None,
    mime: str | None,
    extracted_chars: int,
):
    """Apply routing decision by moving file or quarantining it.

    Args:
        ref: Source file reference.
        decision: Routing decision from the agent.
        tools: Organizer tool facade.
        target_filename: Optional filename override proposed by the file agent.
        mime: MIME type when known.
        extracted_chars: Number of extracted text characters.

    Returns:
        MoveResult: Move/quarantine operation result.
    """
    if decision.quarantine:
        return tools.quarantine_file(ref, mime=mime, extracted_chars=extracted_chars)
    normalized = enforce_johnny_decimal_folder(
        files=tools.ctx.files,
        root=tools.ctx.organized_root,
        folder=decision.folder,
    )
    return tools.move_file(
        ref,
        normalized,
        filename=target_filename,
        mime=mime,
        extracted_chars=extracted_chars,
    )


def _apply_folder_decision(
    *,
    ref: FileRef,
    decision: FolderDecision,
    tools: OrganizerTools,
):
    """Apply folder decision by moving folder or quarantining it."""
    if decision.quarantine:
        return tools.quarantine_file(ref, mime="inode/directory", extracted_chars=0)
    normalized = enforce_johnny_decimal_folder(
        files=tools.ctx.files,
        root=tools.ctx.organized_root,
        folder=decision.folder,
    )
    return tools.move_ref(ref, normalized, mime="inode/directory", extracted_chars=0)


if __name__ == "__main__":
    main()
