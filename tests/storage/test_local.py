from __future__ import annotations

import threading
import time
from pathlib import Path

from files_ai.storage import FileRef
from files_ai.storage import LocalFiles


def test_walk_move_and_hash(tmp_path: Path) -> None:
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
    assert files.hash(src)

    dst = files.join(org, "hello.txt")
    files.move(src, dst)
    assert files.exists(dst)
    assert not files.exists(src)


def test_watch_created_event(tmp_path: Path) -> None:
    files = LocalFiles(tmp_path, poll_interval_seconds=0.1)
    drop = FileRef("local", "/dropzone")
    files.make_dir(drop)
    iterator = files.watch(drop)
    try:
        target = tmp_path / "dropzone" / "new.txt"

        def _create_file() -> None:
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
