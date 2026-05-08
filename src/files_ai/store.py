"""SQLite persistence layer for files and routing decisions."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from datetime import timezone
from pathlib import Path

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


class Store:
    """Repository-backed store for metadata and decision history."""

    def __init__(self, db_path: str | Path) -> None:
        """Initialize database connection and schema.

        Args:
            db_path: SQLite database file path.
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.execute("PRAGMA journal_mode=WAL;")
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        """Close database connection."""
        self.conn.close()

    def has_hash(self, sha256: str) -> bool:
        """Return whether a file hash already exists.

        Args:
            sha256: File hash to check.

        Returns:
            bool: `True` when the hash is present.
        """
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
        cur = self.conn.execute(
            """
            INSERT INTO files(sha256, backend, src_path, size, mime, extracted_chars)
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
        self.conn.execute(
            """
            INSERT INTO decisions(file_id, reasoning, tools_called, model, created_at)
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
        row = self.conn.execute(
            "SELECT path FROM folder_index WHERE canonical = ?", (canonical,)
        ).fetchone()
        if row is None:
            return None
        return str(row[0])
