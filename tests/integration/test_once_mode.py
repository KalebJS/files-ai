"""Integration tests for one-shot organizer execution."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from files_ai import __main__ as app
from files_ai.agent import AgentDecision
from files_ai.config import get_settings
from files_ai.extract import ExtractionResult
from files_ai.folder_agent import FolderDecision
from files_ai.storage import FileRef
from files_ai.storage import LocalFiles
from files_ai.store import Store


class _DummyAgent:
    """Minimal fake agent object for patched runtime execution."""


class _DummyFolderAgent:
    """Minimal fake folder agent object for patched runtime execution."""


class _DummyAreaAgent:
    """Minimal fake area moderation agent for patched runtime execution."""

    def invoke(self, _request: object, **_kwargs: object) -> dict[str, object]:
        return {
            "output": (
                '{"approved":true,"reasoning":"approved for test",'
                '"folder":null,"confidence":1.0,"quarantine":false}'
            )
        }


def test_once_mode_processes_dropzone_file(monkeypatch, tmp_path: Path) -> None:
    """Process one dropzone file end-to-end in --once mode.

    Args:
        monkeypatch: Pytest monkeypatch fixture.
        tmp_path: Temporary test directory.
    """
    dropzone = tmp_path / "dropzone"
    organized = tmp_path / "organized"
    quarantine = tmp_path / "quarantine"
    dropzone.mkdir(parents=True)
    organized.mkdir(parents=True)
    quarantine.mkdir(parents=True)
    source = dropzone / "invoice.txt"
    source.write_text("Invoice for April services", encoding="utf-8")
    state_db = tmp_path / "state.db"

    monkeypatch.setenv("BACKEND", "local")
    monkeypatch.setenv("BACKEND_OPTS__ROOT", str(tmp_path))
    monkeypatch.setenv("DROPZONE", "/dropzone")
    monkeypatch.setenv("ORGANIZED", "/organized")
    monkeypatch.setenv("QUARANTINE", "/quarantine")
    monkeypatch.setenv("STATE_DB", str(state_db))
    monkeypatch.setenv("DRY_RUN", "false")
    monkeypatch.setenv("MODEL", "test-model")
    monkeypatch.setattr("sys.argv", ["files-ai", "--once"])
    monkeypatch.setattr(app, "build_agent", lambda _: _DummyAgent())
    monkeypatch.setattr(app, "build_folder_agent", lambda _: _DummyFolderAgent())
    monkeypatch.setattr(
        app, "build_area_creation_agent_from_settings", lambda _: _DummyAreaAgent()
    )
    monkeypatch.setattr(
        app,
        "decide_folder",
        lambda *_args, **_kwargs: AgentDecision(
            folder="Finance/Invoices",
            reasoning="integration test route",
            confidence=1.0,
        ),
    )
    monkeypatch.setattr(
        app,
        "decide_folder_action",
        lambda *_args, **_kwargs: FolderDecision(
            action="recurse",
            folder="Unsorted",
            reasoning="integration recurse",
            confidence=1.0,
        ),
    )
    monkeypatch.setattr(app.StableFileWatcher, "is_stable", lambda *_: True)

    get_settings.cache_clear()
    try:
        app.main()
    finally:
        get_settings.cache_clear()

    target = (
        organized / "10-19 Finance" / "10 Invoices" / "10.01 Invoices" / "invoice.txt"
    )
    assert target.exists()
    assert not source.exists()
    assert not any(dropzone.iterdir())

    with sqlite3.connect(state_db) as conn:
        count = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        moved = conn.execute(
            "SELECT dst_path FROM files WHERE dst_path IS NOT NULL LIMIT 1"
        ).fetchone()
    assert count == 1
    assert moved is not None
    assert moved[0].endswith("/10-19 Finance/10 Invoices/10.01 Invoices/invoice.txt")


def test_once_mode_moves_project_folder_as_unit(monkeypatch, tmp_path: Path) -> None:
    """Move dependency-bound project folders without recursing children."""
    dropzone = tmp_path / "dropzone"
    organized = tmp_path / "organized"
    quarantine = tmp_path / "quarantine"
    project = dropzone / "my-app"
    project.mkdir(parents=True)
    organized.mkdir(parents=True)
    quarantine.mkdir(parents=True)
    (project / "pyproject.toml").write_text(
        "[project]\nname='my-app'", encoding="utf-8"
    )
    (project / "main.py").write_text("print('ok')", encoding="utf-8")
    state_db = tmp_path / "state.db"

    monkeypatch.setenv("BACKEND", "local")
    monkeypatch.setenv("BACKEND_OPTS__ROOT", str(tmp_path))
    monkeypatch.setenv("DROPZONE", "/dropzone")
    monkeypatch.setenv("ORGANIZED", "/organized")
    monkeypatch.setenv("QUARANTINE", "/quarantine")
    monkeypatch.setenv("STATE_DB", str(state_db))
    monkeypatch.setenv("DRY_RUN", "false")
    monkeypatch.setenv("MODEL", "test-model")
    monkeypatch.setattr("sys.argv", ["files-ai", "--once"])
    monkeypatch.setattr(app, "build_agent", lambda _: _DummyAgent())
    monkeypatch.setattr(app, "build_folder_agent", lambda _: _DummyFolderAgent())
    monkeypatch.setattr(
        app, "build_area_creation_agent_from_settings", lambda _: _DummyAreaAgent()
    )
    monkeypatch.setattr(
        app,
        "decide_folder",
        lambda *_args, **_kwargs: AgentDecision(
            folder="Unsorted",
            reasoning="unused for folder move",
            confidence=1.0,
        ),
    )
    monkeypatch.setattr(
        app,
        "decide_folder_action",
        lambda *_args, **_kwargs: FolderDecision(
            action="move_folder",
            folder="Code/Projects",
            reasoning="project dependency signals",
            confidence=1.0,
        ),
    )
    monkeypatch.setattr(app.StableFileWatcher, "is_stable", lambda *_: True)

    get_settings.cache_clear()
    try:
        app.main()
    finally:
        get_settings.cache_clear()

    assert not project.exists()
    assert (
        organized
        / "10-19 Code"
        / "10 Projects"
        / "10.01 Projects"
        / "my-app"
        / "main.py"
    ).exists()
    assert not any(dropzone.iterdir())


def test_once_mode_recurses_independent_folder(monkeypatch, tmp_path: Path) -> None:
    """Recurse independent folders and route files individually."""
    dropzone = tmp_path / "dropzone"
    organized = tmp_path / "organized"
    quarantine = tmp_path / "quarantine"
    docs = dropzone / "tax-docs"
    docs.mkdir(parents=True)
    organized.mkdir(parents=True)
    quarantine.mkdir(parents=True)
    (docs / "w2.pdf").write_text("w2", encoding="utf-8")
    (docs / "receipt.txt").write_text("receipt", encoding="utf-8")
    state_db = tmp_path / "state.db"

    monkeypatch.setenv("BACKEND", "local")
    monkeypatch.setenv("BACKEND_OPTS__ROOT", str(tmp_path))
    monkeypatch.setenv("DROPZONE", "/dropzone")
    monkeypatch.setenv("ORGANIZED", "/organized")
    monkeypatch.setenv("QUARANTINE", "/quarantine")
    monkeypatch.setenv("STATE_DB", str(state_db))
    monkeypatch.setenv("DRY_RUN", "false")
    monkeypatch.setenv("MODEL", "test-model")
    monkeypatch.setattr("sys.argv", ["files-ai", "--once"])
    monkeypatch.setattr(app, "build_agent", lambda _: _DummyAgent())
    monkeypatch.setattr(app, "build_folder_agent", lambda _: _DummyFolderAgent())
    monkeypatch.setattr(
        app, "build_area_creation_agent_from_settings", lambda _: _DummyAreaAgent()
    )
    monkeypatch.setattr(
        app,
        "decide_folder",
        lambda *_args, **_kwargs: AgentDecision(
            folder="Finance/Taxes",
            reasoning="tax docs",
            confidence=1.0,
        ),
    )
    monkeypatch.setattr(
        app,
        "decide_folder_action",
        lambda *_args, **_kwargs: FolderDecision(
            action="recurse",
            folder="Unsorted",
            reasoning="independent docs",
            confidence=1.0,
        ),
    )
    monkeypatch.setattr(app.StableFileWatcher, "is_stable", lambda *_: True)

    get_settings.cache_clear()
    try:
        app.main()
    finally:
        get_settings.cache_clear()

    assert (
        organized / "10-19 Finance" / "10 Taxes" / "10.01 Taxes" / "w2.pdf"
    ).exists()
    assert (
        organized / "10-19 Finance" / "10 Taxes" / "10.01 Taxes" / "receipt.txt"
    ).exists()
    assert not docs.exists()
    assert not any(dropzone.iterdir())


def test_once_mode_moves_duplicates_to_quarantine(monkeypatch, tmp_path: Path) -> None:
    """Move duplicate files from dropzone into quarantine/duplicates."""
    dropzone = tmp_path / "dropzone" / "nested"
    organized = tmp_path / "organized"
    quarantine = tmp_path / "quarantine"
    dropzone.mkdir(parents=True)
    organized.mkdir(parents=True)
    quarantine.mkdir(parents=True)
    existing = organized / "Finance" / "Invoices"
    existing.mkdir(parents=True)
    source = dropzone / "invoice-dup.txt"
    source.write_text("same-content", encoding="utf-8")
    state_db = tmp_path / "state.db"
    (existing / "invoice.txt").write_text("same-content", encoding="utf-8")

    files = LocalFiles(tmp_path)
    store = Store(state_db)
    existing_ref = FileRef("local", "/organized/Finance/Invoices/invoice.txt")
    file_id = store.insert_file(
        sha256=files.hash(existing_ref),
        backend="local",
        src_path="/organized/Finance/Invoices/invoice.txt",
        size=len("same-content"),
        mime="text/plain",
        extracted_chars=12,
    )
    store.set_destination(file_id, "/organized/Finance/Invoices/invoice.txt")
    store.close()

    monkeypatch.setenv("BACKEND", "local")
    monkeypatch.setenv("BACKEND_OPTS__ROOT", str(tmp_path))
    monkeypatch.setenv("DROPZONE", "/dropzone")
    monkeypatch.setenv("ORGANIZED", "/organized")
    monkeypatch.setenv("QUARANTINE", "/quarantine")
    monkeypatch.setenv("STATE_DB", str(state_db))
    monkeypatch.setenv("DRY_RUN", "false")
    monkeypatch.setenv("MODEL", "test-model")
    monkeypatch.setattr("sys.argv", ["files-ai", "--once"])
    monkeypatch.setattr(app, "build_agent", lambda _: _DummyAgent())
    monkeypatch.setattr(app, "build_folder_agent", lambda _: _DummyFolderAgent())
    monkeypatch.setattr(
        app, "build_area_creation_agent_from_settings", lambda _: _DummyAreaAgent()
    )
    monkeypatch.setattr(
        app,
        "decide_folder",
        lambda *_args, **_kwargs: AgentDecision(
            folder="Finance/Invoices",
            reasoning="duplicate route",
            confidence=1.0,
        ),
    )
    monkeypatch.setattr(
        app,
        "decide_folder_action",
        lambda *_args, **_kwargs: FolderDecision(
            action="recurse",
            folder="Unsorted",
            reasoning="duplicate recurse",
            confidence=1.0,
        ),
    )
    monkeypatch.setattr(app.StableFileWatcher, "is_stable", lambda *_: True)

    get_settings.cache_clear()
    try:
        app.main()
    finally:
        get_settings.cache_clear()

    duplicate_target = quarantine / "duplicates" / "nested" / "invoice-dup.txt"
    assert duplicate_target.exists()
    assert not source.exists()
    assert not any((tmp_path / "dropzone").iterdir())


def test_once_mode_reimports_when_duplicate_destination_missing(
    monkeypatch, tmp_path: Path
) -> None:
    """Route as normal when hash exists but cached destination is missing."""
    dropzone = tmp_path / "dropzone" / "nested"
    organized = tmp_path / "organized"
    quarantine = tmp_path / "quarantine"
    dropzone.mkdir(parents=True)
    organized.mkdir(parents=True)
    quarantine.mkdir(parents=True)
    source = dropzone / "invoice-dup.txt"
    source.write_text("same-content", encoding="utf-8")
    state_db = tmp_path / "state.db"

    files = LocalFiles(tmp_path)
    store = Store(state_db)
    stale_id = store.insert_file(
        sha256=files.hash(FileRef("local", "/dropzone/nested/invoice-dup.txt")),
        backend="local",
        src_path="/organized/Finance/Invoices/invoice.txt",
        size=len("same-content"),
        mime="text/plain",
        extracted_chars=12,
    )
    store.set_destination(stale_id, "/organized/Finance/Invoices/invoice.txt")
    store.close()

    monkeypatch.setenv("BACKEND", "local")
    monkeypatch.setenv("BACKEND_OPTS__ROOT", str(tmp_path))
    monkeypatch.setenv("DROPZONE", "/dropzone")
    monkeypatch.setenv("ORGANIZED", "/organized")
    monkeypatch.setenv("QUARANTINE", "/quarantine")
    monkeypatch.setenv("STATE_DB", str(state_db))
    monkeypatch.setenv("DRY_RUN", "false")
    monkeypatch.setenv("MODEL", "test-model")
    monkeypatch.setattr("sys.argv", ["files-ai", "--once"])
    monkeypatch.setattr(app, "build_agent", lambda _: _DummyAgent())
    monkeypatch.setattr(app, "build_folder_agent", lambda _: _DummyFolderAgent())
    monkeypatch.setattr(
        app, "build_area_creation_agent_from_settings", lambda _: _DummyAreaAgent()
    )
    monkeypatch.setattr(
        app,
        "decide_folder",
        lambda *_args, **_kwargs: AgentDecision(
            folder="Finance/Invoices",
            reasoning="stale duplicate cache",
            confidence=1.0,
        ),
    )
    monkeypatch.setattr(
        app,
        "decide_folder_action",
        lambda *_args, **_kwargs: FolderDecision(
            action="recurse",
            folder="Unsorted",
            reasoning="stale duplicate recurse",
            confidence=1.0,
        ),
    )
    monkeypatch.setattr(app.StableFileWatcher, "is_stable", lambda *_: True)

    get_settings.cache_clear()
    try:
        app.main()
    finally:
        get_settings.cache_clear()

    moved_target = (
        organized
        / "10-19 Finance"
        / "10 Invoices"
        / "10.01 Invoices"
        / "invoice-dup.txt"
    )
    assert moved_target.exists()
    assert not source.exists()
    duplicate_target = quarantine / "duplicates" / "nested" / "invoice-dup.txt"
    assert not duplicate_target.exists()
    with sqlite3.connect(state_db) as conn:
        updated_dst = conn.execute(
            "SELECT dst_path FROM files WHERE id = ?", (stale_id,)
        ).fetchone()
    assert updated_dst is not None
    assert updated_dst[0] is not None
    assert updated_dst[0].endswith(
        "/10-19 Finance/10 Invoices/10.01 Invoices/invoice-dup.txt"
    )


def test_once_mode_auto_quarantines_encrypted_pdf(monkeypatch, tmp_path: Path) -> None:
    """Auto-quarantine encrypted PDFs without routing via file agent."""
    dropzone = tmp_path / "dropzone"
    organized = tmp_path / "organized"
    quarantine = tmp_path / "quarantine"
    dropzone.mkdir(parents=True)
    organized.mkdir(parents=True)
    quarantine.mkdir(parents=True)
    source = dropzone / "secret.pdf"
    source.write_text("placeholder", encoding="utf-8")
    state_db = tmp_path / "state.db"

    monkeypatch.setenv("BACKEND", "local")
    monkeypatch.setenv("BACKEND_OPTS__ROOT", str(tmp_path))
    monkeypatch.setenv("DROPZONE", "/dropzone")
    monkeypatch.setenv("ORGANIZED", "/organized")
    monkeypatch.setenv("QUARANTINE", "/quarantine")
    monkeypatch.setenv("STATE_DB", str(state_db))
    monkeypatch.setenv("DRY_RUN", "false")
    monkeypatch.setenv("MODEL", "test-model")
    monkeypatch.setattr("sys.argv", ["files-ai", "--once"])
    monkeypatch.setattr(app, "build_agent", lambda _: _DummyAgent())
    monkeypatch.setattr(app, "build_folder_agent", lambda _: _DummyFolderAgent())
    monkeypatch.setattr(
        app, "build_area_creation_agent_from_settings", lambda _: _DummyAreaAgent()
    )
    monkeypatch.setattr(
        app,
        "extract_file",
        lambda *_args, **_kwargs: ExtractionResult(
            text="secret.pdf",
            mime="application/pdf",
            tier=1,
            encrypted=True,
        ),
    )
    monkeypatch.setattr(
        app,
        "decide_folder",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("decide_folder should not run for encrypted PDFs")
        ),
    )
    monkeypatch.setattr(
        app,
        "decide_folder_action",
        lambda *_args, **_kwargs: FolderDecision(
            action="recurse",
            folder="Unsorted",
            reasoning="encrypted recurse",
            confidence=1.0,
        ),
    )
    monkeypatch.setattr(app.StableFileWatcher, "is_stable", lambda *_: True)

    get_settings.cache_clear()
    try:
        app.main()
    finally:
        get_settings.cache_clear()

    target = quarantine / "secret.pdf"
    assert target.exists()
    assert not source.exists()
    assert not any(organized.iterdir())


def test_once_mode_renames_file_when_agent_suggests(
    monkeypatch, tmp_path: Path
) -> None:
    """Rename a file while routing when agent returns optional filename."""
    dropzone = tmp_path / "dropzone"
    organized = tmp_path / "organized"
    quarantine = tmp_path / "quarantine"
    dropzone.mkdir(parents=True)
    organized.mkdir(parents=True)
    quarantine.mkdir(parents=True)
    source = dropzone / "scan.pdf"
    source.write_text("Invoice #1042 due", encoding="utf-8")
    state_db = tmp_path / "state.db"

    monkeypatch.setenv("BACKEND", "local")
    monkeypatch.setenv("BACKEND_OPTS__ROOT", str(tmp_path))
    monkeypatch.setenv("DROPZONE", "/dropzone")
    monkeypatch.setenv("ORGANIZED", "/organized")
    monkeypatch.setenv("QUARANTINE", "/quarantine")
    monkeypatch.setenv("STATE_DB", str(state_db))
    monkeypatch.setenv("DRY_RUN", "false")
    monkeypatch.setenv("MODEL", "test-model")
    monkeypatch.setattr("sys.argv", ["files-ai", "--once"])
    monkeypatch.setattr(app, "build_agent", lambda _: _DummyAgent())
    monkeypatch.setattr(app, "build_folder_agent", lambda _: _DummyFolderAgent())
    monkeypatch.setattr(
        app, "build_area_creation_agent_from_settings", lambda _: _DummyAreaAgent()
    )
    monkeypatch.setattr(
        app,
        "decide_folder",
        lambda *_args, **_kwargs: AgentDecision(
            folder="Finance/Invoices",
            reasoning="rename integration route",
            confidence=1.0,
            filename="2026-05 Invoice 1042.pdf",
        ),
    )
    monkeypatch.setattr(
        app,
        "decide_folder_action",
        lambda *_args, **_kwargs: FolderDecision(
            action="recurse",
            folder="Unsorted",
            reasoning="integration recurse",
            confidence=1.0,
        ),
    )
    monkeypatch.setattr(app.StableFileWatcher, "is_stable", lambda *_: True)

    get_settings.cache_clear()
    try:
        app.main()
    finally:
        get_settings.cache_clear()

    target = (
        organized
        / "10-19 Finance"
        / "10 Invoices"
        / "10.01 Invoices"
        / "2026-05 Invoice 1042.pdf"
    )
    assert target.exists()
    assert not source.exists()
