"""Local storage backend tests."""

from __future__ import annotations

import threading
import time
from pathlib import Path

from files_ai.storage import FileRef
from files_ai.storage import LocalFiles


def test_walk_move_and_hash(tmp_path: Path) -> None:
    """Walk files, compute hash, and move file within backend.

    Args:
        tmp_path: Temporary test directory.
    """
    files = LocalFiles(tmp_path)
    drop = FileRef("local", "/dropzone")
    org = FileRef("local", "/organized")
    files.make_dir(drop)
    files.make_dir(org)

    src = files.join(drop, "hello.txt")
    abs_src = tmp_path / src.path.lstrip("/")
    abs_src.write_text("hello world", encoding="utf-8")

    walked = list(files.walk(drop))
    assert len(walked) == 1
    assert walked[0].ref.path == "/dropzone/hello.txt"
    children = list(files.iterdir(drop))
    assert len(children) == 1
    assert children[0].ref.path == "/dropzone/hello.txt"
    assert files.hash(src)

    dst = files.join(org, "hello.txt")
    files.move(src, dst)
    assert files.exists(dst)
    assert not files.exists(src)


def test_move_directory_fallback_copytree(tmp_path: Path, monkeypatch) -> None:
    """Move directories via fallback path when atomic replace fails."""
    files = LocalFiles(tmp_path)
    src_root = FileRef("local", "/dropzone/project")
    dst_root = FileRef("local", "/organized/project")
    files.make_dir(src_root)
    nested = tmp_path / "dropzone" / "project" / "src"
    nested.mkdir(parents=True)
    (nested / "main.py").write_text("print('ok')", encoding="utf-8")

    monkeypatch.setattr(
        "files_ai.storage.local.os.replace", lambda *_: (_ for _ in ()).throw(OSError())
    )

    files.move(src_root, dst_root)
    assert not (tmp_path / "dropzone" / "project").exists()
    assert (tmp_path / "organized" / "project" / "src" / "main.py").exists()


def test_watch_created_event(tmp_path: Path) -> None:
    """Emit created event when new file appears in watched directory.

    Args:
        tmp_path: Temporary test directory.
    """
    files = LocalFiles(tmp_path, poll_interval_seconds=0.1)
    drop = FileRef("local", "/dropzone")
    files.make_dir(drop)
    iterator = files.watch(drop)
    try:
        target = tmp_path / "dropzone" / "new.txt"

        def _create_file() -> None:
            """Create a test file after a short delay."""
            time.sleep(0.3)
            target.write_text("x", encoding="utf-8")

        thread = threading.Thread(target=_create_file, daemon=True)
        thread.start()
        deadline = time.time() + 5
        got_created = False
        while time.time() < deadline:
            event = next(iterator)
            if event.kind == "created" and event.ref.path.endswith("new.txt"):
                got_created = True
                break
        assert got_created
    finally:
        files.stop_watch()
