from __future__ import annotations

import argparse
import signal
from pathlib import PurePosixPath

import structlog

from .agent import AgentDecision
from .agent import build_agent
from .agent import decide_folder
from .config import Settings
from .config import get_settings
from .extract import extract_file
from .logging import configure_logging
from .storage import FileRef
from .storage import get_files
from .store import Store
from .tools import OrganizerTools
from .tools import ToolContext
from .tree import build_tree_snapshot
from .watcher import StableFileWatcher


def main() -> None:
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
    stopped = False

    def _stop(*_: object) -> None:
        nonlocal stopped
        stopped = True
        watcher.stop()

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    try:
        for ref in watcher.startup_scan(dropzone):
            _process_file(ref, settings=settings, tools=tools, agent=agent)
        if args.once:
            return
        for ref in watcher.iter_stable_events(dropzone):
            if stopped:
                break
            _process_file(ref, settings=settings, tools=tools, agent=agent)
    finally:
        watcher.stop()
        store.close()
        log.info("shutdown")


def _process_file(
    ref: FileRef, *, settings: Settings, tools: OrganizerTools, agent: object
) -> None:
    log = structlog.get_logger("files_ai.processor").bind(path=ref.path)
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


def _apply_decision(
    *,
    ref: FileRef,
    decision: AgentDecision,
    tools: OrganizerTools,
    mime: str | None,
    extracted_chars: int,
):
    if decision.quarantine:
        return tools.quarantine_file(ref, mime=mime, extracted_chars=extracted_chars)
    folder = tools.propose_folder(decision.folder)
    parts = [part for part in PurePosixPath(folder).parts if part not in {"", "/"}]
    normalized = "/".join(parts[:4]) or "Unsorted"
    return tools.move_file(ref, normalized, mime=mime, extracted_chars=extracted_chars)


if __name__ == "__main__":
    main()
