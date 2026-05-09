"""Tests for post-batch reviewer tools."""

from __future__ import annotations

import threading
from pathlib import Path

from files_ai.batch_reviewer import BatchReviewTools
from files_ai.batch_reviewer import run_batch_reviewer
from files_ai.config import Settings
from files_ai.mover import move_into_folder
from files_ai.storage import FileRef
from files_ai.storage import LocalFiles
from files_ai.store import Store


def _build_settings(tmp_path: Path) -> Settings:
    """Build settings object for local tests."""
    return Settings(
        backend="local",
        backend_opts={"root": str(tmp_path)},
        dropzone="/dropzone",
        organized="/organized",
        quarantine="/quarantine",
        state_db=tmp_path / "state.db",
        batch_review_enabled=True,
    )


def test_retry_item_moves_back_to_dropzone_and_tracks(tmp_path: Path) -> None:
    """Retry should move an item to dropzone and update tracking rows."""
    settings = _build_settings(tmp_path)
    files = LocalFiles(tmp_path)
    dropzone = FileRef("local", settings.dropzone)
    organized = FileRef("local", settings.organized)
    files.make_dir(dropzone)
    files.make_dir(organized)
    store = Store(settings.state_db)
    try:
        src = files.join(dropzone, "invoice.txt")
        (tmp_path / "dropzone" / "invoice.txt").write_text("invoice", encoding="utf-8")
        moved = move_into_folder(
            files=files,
            store=store,
            src=src,
            folder=files.join(organized, "Finance/Invoices"),
            duplicate_folder=files.join(FileRef("local", settings.quarantine), "dups"),
            mime="text/plain",
            extracted_chars=7,
        )
        assert moved.file_id is not None
        batch_id = store.start_batch(mode="test")
        tools = BatchReviewTools(
            files=files,
            store=store,
            batch_id=batch_id,
            model="kimi-k2.6",
            organized_root=organized,
            dropzone_root=dropzone,
            max_actions=10,
        )
        dst = tools.retry_item(str(moved.file_id), "retry for better routing")
        assert dst.startswith("/dropzone/")
        row = store.get_file_by_id(moved.file_id)
        assert row is not None
        assert row.dst_path == dst
        history = store.list_move_history(batch_id=batch_id, limit=10)
        assert history
        assert history[0]["action"] == "retry_item"
    finally:
        store.close()


def test_move_item_to_existing_folder_updates_destination(tmp_path: Path) -> None:
    """Move tool should place item into existing organized folder."""
    settings = _build_settings(tmp_path)
    files = LocalFiles(tmp_path)
    dropzone = FileRef("local", settings.dropzone)
    organized = FileRef("local", settings.organized)
    quarantine = FileRef("local", settings.quarantine)
    files.make_dir(dropzone)
    files.make_dir(organized)
    files.make_dir(quarantine)
    files.make_dir(files.join(organized, "10-19 Finance/10 Receipts/10.01 Receipts"))
    store = Store(settings.state_db)
    try:
        src = files.join(dropzone, "receipt.txt")
        (tmp_path / "dropzone" / "receipt.txt").write_text("receipt", encoding="utf-8")
        moved = move_into_folder(
            files=files,
            store=store,
            src=src,
            folder=files.join(organized, "Unsorted"),
            duplicate_folder=files.join(quarantine, "dups"),
            mime="text/plain",
            extracted_chars=7,
        )
        assert moved.file_id is not None
        batch_id = store.start_batch(mode="test")
        tools = BatchReviewTools(
            files=files,
            store=store,
            batch_id=batch_id,
            model="kimi-k2.6",
            organized_root=organized,
            dropzone_root=dropzone,
            max_actions=10,
        )
        dst = tools.move_item_to_existing_folder(
            str(moved.file_id),
            "10-19 Finance/10 Receipts/10.01 Receipts",
            "receipt should be in receipts",
        )
        assert dst.startswith("/organized/10-19 Finance/10 Receipts/10.01 Receipts/")
        row = store.get_file_by_id(moved.file_id)
        assert row is not None
        assert row.dst_path == dst
        history = store.list_move_history(batch_id=batch_id, limit=10)
        assert history
        assert history[0]["action"] == "move_item_to_existing_folder"
    finally:
        store.close()


def test_read_move_history_from_different_thread(tmp_path: Path) -> None:
    """Store-backed history reads should work from non-creator thread."""
    settings = _build_settings(tmp_path)
    files = LocalFiles(tmp_path)
    dropzone = FileRef("local", settings.dropzone)
    organized = FileRef("local", settings.organized)
    files.make_dir(dropzone)
    files.make_dir(organized)
    store = Store(settings.state_db)
    try:
        batch_id = store.start_batch(mode="test")
        store.add_move_history(
            batch_id=batch_id,
            action="move_file",
            src_path="/dropzone/a.txt",
            dst_path="/organized/A/a.txt",
            reason="seed",
            model="test-model",
        )
        tools = BatchReviewTools(
            files=files,
            store=store,
            batch_id=batch_id,
            model="kimi-k2.6",
            organized_root=organized,
            dropzone_root=dropzone,
            max_actions=10,
        )
        result: list[str] = []

        def _worker() -> None:
            result.append(tools.read_move_history(limit=10))

        thread = threading.Thread(target=_worker)
        thread.start()
        thread.join()

        assert result
        assert "move_file" in result[0]
    finally:
        store.close()


def test_concurrent_action_cap_is_enforced(tmp_path: Path) -> None:
    """Concurrent tool calls should still honor max action cap."""
    settings = _build_settings(tmp_path)
    files = LocalFiles(tmp_path)
    dropzone = FileRef("local", settings.dropzone)
    organized = FileRef("local", settings.organized)
    files.make_dir(dropzone)
    files.make_dir(organized)
    store = Store(settings.state_db)
    try:
        batch_id = store.start_batch(mode="test")
        tools = BatchReviewTools(
            files=files,
            store=store,
            batch_id=batch_id,
            model="kimi-k2.6",
            organized_root=organized,
            dropzone_root=dropzone,
            max_actions=1,
        )
        results: list[str] = []
        list_lock = threading.Lock()

        def _worker(path: str) -> None:
            value = tools.create_folder(path, "concurrency test")
            with list_lock:
                results.append(value)

        t1 = threading.Thread(target=_worker, args=("A/One",))
        t2 = threading.Thread(target=_worker, args=("B/Two",))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert len(results) == 2
        assert results.count("action_limit_reached") == 1
        assert tools.action_count == 1
    finally:
        store.close()


def test_run_batch_reviewer_prompt_uses_structured_markdown(
    tmp_path: Path, monkeypatch
) -> None:
    """Build reviewer prompt with markdown headers and fenced sections."""
    settings = _build_settings(tmp_path)
    files = LocalFiles(tmp_path)
    dropzone = FileRef("local", settings.dropzone)
    organized = FileRef("local", settings.organized)
    files.make_dir(dropzone)
    files.make_dir(organized)
    store = Store(settings.state_db)
    try:
        batch_id = store.start_batch(mode="test")

        class _RuntimeAgent:
            def __init__(self) -> None:
                self.last_request: dict[str, object] | None = None

            def invoke(self, request: object, **_: object) -> dict[str, object]:
                if isinstance(request, dict):
                    self.last_request = request
                return {"output": '{"summary":"ok"}'}

        runtime = _RuntimeAgent()
        monkeypatch.setattr("files_ai.batch_reviewer.ChatOllama", lambda **_: object())
        monkeypatch.setattr("files_ai.batch_reviewer.create_agent", lambda **_: runtime)

        run_batch_reviewer(
            files=files,
            store=store,
            settings=settings,
            organized_root=organized,
            dropzone_root=dropzone,
            batch_id=batch_id,
            batch_source_paths=["a.txt"],
            new_file_paths=set(),
            new_folder_paths=set(),
            user_context="User context for batch review.",
        )

        assert runtime.last_request is not None
        messages = runtime.last_request["messages"]
        assert isinstance(messages, list)
        content = messages[0]["content"]
        assert "# Task" in content
        assert "## Batch metadata" in content
        assert "## Upload batch tree" in content
        assert "```json" in content
        assert "## Updated destination tree" in content
        assert "## User context" in content
        assert "```markdown" in content
        assert "User context for batch review." in content
    finally:
        store.close()
