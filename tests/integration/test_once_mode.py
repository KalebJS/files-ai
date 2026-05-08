"""Integration tests for one-shot organizer execution."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from files_ai import __main__ as app
from files_ai.agent import AgentDecision
from files_ai.config import get_settings
from files_ai.folder_agent import FolderDecision


class _DummyAgent:
    """Minimal fake agent object for patched runtime execution."""


class _DummyFolderAgent:
    """Minimal fake folder agent object for patched runtime execution."""


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

    target = organized / "Finance" / "Invoices" / "invoice.txt"
    assert target.exists()
    assert not source.exists()

    with sqlite3.connect(state_db) as conn:
        count = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        moved = conn.execute(
            "SELECT dst_path FROM files WHERE dst_path IS NOT NULL LIMIT 1"
        ).fetchone()
    assert count == 1
    assert moved is not None
    assert moved[0].endswith("/Finance/Invoices/invoice.txt")


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
    assert (organized / "Code" / "Projects" / "my-app" / "main.py").exists()


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

    assert (organized / "Finance" / "Taxes" / "w2.pdf").exists()
    assert (organized / "Finance" / "Taxes" / "receipt.txt").exists()
