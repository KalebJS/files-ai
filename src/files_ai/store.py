"""SQLite persistence layer for files and routing decisions."""

from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY,
    sha256 TEXT UNIQUE,
    backend TEXT NOT NULL,
    src_path TEXT NOT NULL,
    dst_path TEXT,
    size INTEGER NOT NULL,
    mime TEXT,
    extracted_chars INTEGER NOT NULL DEFAULT 0,
    moved_at TEXT
);
CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY,
    file_id INTEGER REFERENCES files(id),
    reasoning TEXT NOT NULL,
    tools_called TEXT NOT NULL,
    model TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS folder_index (
    canonical TEXT PRIMARY KEY,
    path TEXT NOT NULL,
    use_count INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS batches (
    id INTEGER PRIMARY KEY,
    mode TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL DEFAULT 'running',
    summary TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS move_history (
    id INTEGER PRIMARY KEY,
    batch_id INTEGER REFERENCES batches(id),
    file_id INTEGER REFERENCES files(id),
    action TEXT NOT NULL,
    src_path TEXT,
    dst_path TEXT,
    reason TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL DEFAULT '',
    metadata TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
"""


@dataclass(frozen=True)
class FileRow:
    """Materialized file row shape.

    Attributes:
        id: Primary key.
        sha256: File content hash.
        backend: Backend name that stored the file.
        src_path: Original source path.
        dst_path: Final destination path when moved.
        size: Source file size in bytes.
        mime: MIME type when known.
        extracted_chars: Number of extracted text characters.
        moved_at: ISO timestamp when moved.
    """

    id: int
    sha256: str
    backend: str
    src_path: str
    dst_path: str | None
    size: int
    mime: str | None
    extracted_chars: int
    moved_at: str | None


@dataclass(frozen=True)
class BatchRow:
    """Materialized batch row shape."""

    id: int
    mode: str
    started_at: str
    finished_at: str | None
    status: str
    summary: str


class Store:
    """Repository-backed store for metadata and decision history."""

    def __init__(self, db_path: str | Path) -> None:
        """Initialize database connection and schema.

        Args:
            db_path: SQLite database file path.
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._lock = threading.RLock()
        with self._lock:
            self.conn.execute("PRAGMA journal_mode=WAL;")
            self.conn.executescript(SCHEMA)
            self.conn.commit()

    def close(self) -> None:
        """Close database connection."""
        with self._lock:
            self.conn.close()

    def has_hash(self, sha256: str) -> bool:
        """Return whether a file hash already exists.

        Args:
            sha256: File hash to check.

        Returns:
            bool: `True` when the hash is present.
        """
        with self._lock:
            row = self.conn.execute(
                "SELECT 1 FROM files WHERE sha256 = ? LIMIT 1", (sha256,)
            ).fetchone()
        return row is not None

    def insert_file(
        self,
        *,
        sha256: str,
        backend: str,
        src_path: str,
        size: int,
        mime: str | None,
        extracted_chars: int,
    ) -> int:
        """Insert a file record and return its row id.

        Args:
            sha256: File content hash.
            backend: Backend name.
            src_path: Source path in the backend.
            size: Source file size in bytes.
            mime: MIME type when known.
            extracted_chars: Number of extracted text characters.

        Returns:
            int: Inserted row id.
        """
        with self._lock:
            cur = self.conn.execute(
                """
                INSERT INTO files(
                    sha256,
                    backend,
                    src_path,
                    size,
                    mime,
                    extracted_chars
                )
                VALUES(?, ?, ?, ?, ?, ?)
                """,
                (sha256, backend, src_path, size, mime, extracted_chars),
            )
            self.conn.commit()
        return int(cur.lastrowid)

    def set_destination(self, file_id: int, dst_path: str) -> None:
        """Set final destination path and move timestamp for a file.

        Args:
            file_id: File row id.
            dst_path: Destination path after move.
        """
        moved_at = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self.conn.execute(
                "UPDATE files SET dst_path = ?, moved_at = ? WHERE id = ?",
                (dst_path, moved_at, file_id),
            )
            self.conn.commit()

    def add_decision(
        self, file_id: int, *, reasoning: str, tools_called: str, model: str
    ) -> None:
        """Persist model decision details for one file.

        Args:
            file_id: Related file row id.
            reasoning: Model reasoning summary.
            tools_called: Tools or operation used.
            model: Model identifier.
        """
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO decisions(
                    file_id,
                    reasoning,
                    tools_called,
                    model,
                    created_at
                )
                VALUES(?, ?, ?, ?, ?)
                """,
                (
                    file_id,
                    reasoning,
                    tools_called,
                    model,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            self.conn.commit()

    def upsert_folder(self, canonical: str, path: str) -> None:
        """Upsert folder mapping and increment usage count.

        Args:
            canonical: Canonical label key.
            path: Folder path associated with the key.
        """
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO folder_index(canonical, path, use_count)
                VALUES(?, ?, 1)
                ON CONFLICT(canonical) DO UPDATE SET
                    path = excluded.path,
                    use_count = folder_index.use_count + 1
                """,
                (canonical, path),
            )
            self.conn.commit()

    def get_folder(self, canonical: str) -> str | None:
        """Fetch stored folder path for a canonical label.

        Args:
            canonical: Canonical label key.

        Returns:
            str | None: Stored folder path when found.
        """
        with self._lock:
            row = self.conn.execute(
                "SELECT path FROM folder_index WHERE canonical = ?", (canonical,)
            ).fetchone()
        if row is None:
            return None
        return str(row[0])

    def start_batch(self, *, mode: str) -> int:
        """Start a batch record and return its id."""
        with self._lock:
            cur = self.conn.execute(
                """
                INSERT INTO batches(mode, started_at, status, summary)
                VALUES(?, ?, 'running', '')
                """,
                (mode, datetime.now(timezone.utc).isoformat()),
            )
            self.conn.commit()
        return int(cur.lastrowid)

    def finish_batch(self, batch_id: int, *, status: str, summary: str) -> None:
        """Finish batch lifecycle with status and summary."""
        with self._lock:
            self.conn.execute(
                """
                UPDATE batches
                SET finished_at = ?, status = ?, summary = ?
                WHERE id = ?
                """,
                (datetime.now(timezone.utc).isoformat(), status, summary, batch_id),
            )
            self.conn.commit()

    def add_move_history(
        self,
        *,
        batch_id: int,
        action: str,
        src_path: str | None,
        dst_path: str | None,
        reason: str,
        model: str,
        file_id: int | None = None,
        metadata: str = "",
    ) -> None:
        """Append one move-history action for a batch."""
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO move_history(
                    batch_id,
                    file_id,
                    action,
                    src_path,
                    dst_path,
                    reason,
                    model,
                    metadata,
                    created_at
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    batch_id,
                    file_id,
                    action,
                    src_path,
                    dst_path,
                    reason,
                    model,
                    metadata,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            self.conn.commit()

    def list_move_history(
        self, *, batch_id: int, limit: int = 100
    ) -> list[dict[str, Any]]:
        """Return newest move-history rows for a batch."""
        with self._lock:
            rows = self.conn.execute(
                """
                SELECT
                    id,
                    batch_id,
                    file_id,
                    action,
                    src_path,
                    dst_path,
                    reason,
                    model,
                    metadata,
                    created_at
                FROM move_history
                WHERE batch_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (batch_id, limit),
            ).fetchall()
        return [
            {
                "id": int(row[0]),
                "batch_id": int(row[1]),
                "file_id": int(row[2]) if row[2] is not None else None,
                "action": str(row[3]),
                "src_path": str(row[4]) if row[4] is not None else None,
                "dst_path": str(row[5]) if row[5] is not None else None,
                "reason": str(row[6]),
                "model": str(row[7]),
                "metadata": str(row[8]),
                "created_at": str(row[9]),
            }
            for row in rows
        ]

    def get_file_by_id(self, file_id: int) -> FileRow | None:
        """Fetch one file row by id."""
        with self._lock:
            row = self.conn.execute(
                """
                SELECT id, sha256, backend, src_path, dst_path, size, mime,
                       extracted_chars, moved_at
                FROM files
                WHERE id = ?
                """,
                (file_id,),
            ).fetchone()
        if row is None:
            return None
        return FileRow(
            id=int(row[0]),
            sha256=str(row[1]),
            backend=str(row[2]),
            src_path=str(row[3]),
            dst_path=str(row[4]) if row[4] is not None else None,
            size=int(row[5]),
            mime=str(row[6]) if row[6] is not None else None,
            extracted_chars=int(row[7]),
            moved_at=str(row[8]) if row[8] is not None else None,
        )

    def get_file_by_destination(self, dst_path: str) -> FileRow | None:
        """Fetch most recent file row by destination path."""
        with self._lock:
            row = self.conn.execute(
                """
                SELECT id, sha256, backend, src_path, dst_path, size, mime,
                       extracted_chars, moved_at
                FROM files
                WHERE dst_path = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (dst_path,),
            ).fetchone()
        if row is None:
            return None
        return FileRow(
            id=int(row[0]),
            sha256=str(row[1]),
            backend=str(row[2]),
            src_path=str(row[3]),
            dst_path=str(row[4]) if row[4] is not None else None,
            size=int(row[5]),
            mime=str(row[6]) if row[6] is not None else None,
            extracted_chars=int(row[7]),
            moved_at=str(row[8]) if row[8] is not None else None,
        )

    def update_file_destination(self, file_id: int, dst_path: str) -> None:
        """Update destination and moved-at timestamp for existing file row."""
        with self._lock:
            self.conn.execute(
                """
                UPDATE files
                SET dst_path = ?, moved_at = ?
                WHERE id = ?
                """,
                (dst_path, datetime.now(timezone.utc).isoformat(), file_id),
            )
            self.conn.commit()
