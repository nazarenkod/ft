"""SQLite-хранилище: прогресс переводов и resume-on-failure."""

import hashlib
import sqlite3
from pathlib import Path

from core.models import Chapter, TranslationResult

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT NOT NULL,
    file_hash TEXT NOT NULL UNIQUE,
    total_chapters INTEGER NOT NULL DEFAULT 0,
    output_path TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS chapters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    idx INTEGER NOT NULL,
    title TEXT NOT NULL,
    word_count INTEGER NOT NULL,
    source_text TEXT NOT NULL,
    UNIQUE (project_id, idx)
);

CREATE TABLE IF NOT EXISTS translations (
    chapter_id INTEGER PRIMARY KEY REFERENCES chapters(id),
    text TEXT NOT NULL,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cost_usd REAL NOT NULL DEFAULT 0,
    duration_sec REAL NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'done',
    completed_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


class Storage:
    def __init__(self, db_path: Path | str):
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    def get_or_create_project(self, path: Path, chapters: list[Chapter]) -> int:
        """Находит проект по хэшу файла или создаёт его вместе с главами."""
        fhash = file_hash(path)
        row = self.conn.execute(
            "SELECT id FROM projects WHERE file_hash = ?", (fhash,)
        ).fetchone()
        if row:
            return row["id"]

        cur = self.conn.execute(
            "INSERT INTO projects (filename, file_hash, total_chapters) VALUES (?, ?, ?)",
            (path.name, fhash, len(chapters)),
        )
        project_id = cur.lastrowid
        self.conn.executemany(
            "INSERT INTO chapters (project_id, idx, title, word_count, source_text)"
            " VALUES (?, ?, ?, ?, ?)",
            [(project_id, c.idx, c.title, c.word_count, c.text) for c in chapters],
        )
        self.conn.commit()
        return project_id

    def find_project(self, path: Path) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM projects WHERE file_hash = ?", (file_hash(path),)
        ).fetchone()

    def list_projects(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            """
            SELECT p.id, p.filename, p.total_chapters, p.created_at,
                   COUNT(t.chapter_id) AS done,
                   COALESCE(SUM(t.cost_usd), 0) AS spent
            FROM projects p
            LEFT JOIN chapters c ON c.project_id = p.id
            LEFT JOIN translations t ON t.chapter_id = c.id AND t.status = 'done'
            GROUP BY p.id ORDER BY p.created_at
            """
        ).fetchall()

    def translated_indices(self, project_id: int) -> set[int]:
        """Номера глав, которые уже успешно переведены (для resume)."""
        rows = self.conn.execute(
            """
            SELECT c.idx FROM chapters c
            JOIN translations t ON t.chapter_id = c.id
            WHERE c.project_id = ? AND t.status = 'done'
            """,
            (project_id,),
        ).fetchall()
        return {r["idx"] for r in rows}

    def save_translation(self, project_id: int, result: TranslationResult) -> None:
        """Атомарно фиксирует перевод одной главы."""
        row = self.conn.execute(
            "SELECT id FROM chapters WHERE project_id = ? AND idx = ?",
            (project_id, result.chapter_idx),
        ).fetchone()
        if row is None:
            raise ValueError(f"Глава {result.chapter_idx} не найдена в проекте {project_id}")
        self.conn.execute(
            """
            INSERT OR REPLACE INTO translations
                (chapter_id, text, input_tokens, output_tokens, cost_usd, duration_sec, status)
            VALUES (?, ?, ?, ?, ?, ?, 'done')
            """,
            (
                row["id"],
                result.text,
                result.input_tokens,
                result.output_tokens,
                result.cost_usd,
                result.duration_sec,
            ),
        )
        self.conn.commit()

    def chapter_status(self, project_id: int) -> list[sqlite3.Row]:
        return self.conn.execute(
            """
            SELECT c.idx, c.title, c.word_count,
                   t.status, t.cost_usd, t.duration_sec
            FROM chapters c
            LEFT JOIN translations t ON t.chapter_id = c.id
            WHERE c.project_id = ? ORDER BY c.idx
            """,
            (project_id,),
        ).fetchall()

    def get_translations(self, project_id: int) -> list[sqlite3.Row]:
        """Переведённые главы по порядку — для экспорта в .docx."""
        return self.conn.execute(
            """
            SELECT c.idx, c.title, t.text
            FROM chapters c
            JOIN translations t ON t.chapter_id = c.id
            WHERE c.project_id = ? AND t.status = 'done'
            ORDER BY c.idx
            """,
            (project_id,),
        ).fetchall()

    def set_output_path(self, project_id: int, output_path: str) -> None:
        self.conn.execute(
            "UPDATE projects SET output_path = ? WHERE id = ?", (output_path, project_id)
        )
        self.conn.commit()
