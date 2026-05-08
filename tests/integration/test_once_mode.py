"""Integration tests for one-shot organizer execution."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from files_ai import __main__ as app
from files_ai.agent import AgentDecision
from files_ai.config import get_settings


class _DummyAgent:
    """Minimal fake agent object for patched runtime execution."""


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
    monkeypatch.setattr(
        app,
        "decide_folder",
        lambda *_args, **_kwargs: AgentDecision(
            folder="Finance/Invoices",
            reasoning="integration test route",
            confidence=1.0,
        ),
    )
    monkeypatch.setattr(app.StableFileWatcher, "_is_stable", lambda *_: True)

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
