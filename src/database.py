"""Local SQLite persistence and vector search."""

from __future__ import annotations

import json
import math
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from src.config import settings


JSON_COLUMNS = {
    "material_embeddings": {"embedding"},
    "quizzes": {"quiz_data"},
    "quiz_attempts": {"results"},
    "chat_messages": {"metadata", "retrieved_chunk_ids", "messages"},
    "difficult_concepts": {"concepts"},
}

SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS profiles (
    id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE COLLATE NOCASE,
    display_name TEXT NOT NULL, password_hash TEXT NOT NULL DEFAULT '',
    avatar_url TEXT NOT NULL DEFAULT '', theme TEXT NOT NULL DEFAULT 'system',
    daily_requests INTEGER NOT NULL DEFAULT 0, last_request_date TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS materials (
    id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    source_type TEXT NOT NULL, title TEXT NOT NULL, file_path TEXT, url TEXT,
    status TEXT NOT NULL DEFAULT 'pending', error_message TEXT, vector_store_path TEXT,
    title_normalized TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    UNIQUE(user_id, title)
);
CREATE TABLE IF NOT EXISTS material_chunks (
    id TEXT PRIMARY KEY, material_id TEXT NOT NULL REFERENCES materials(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL, content TEXT NOT NULL, token_count INTEGER, page_number INTEGER,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS material_embeddings (
    id TEXT PRIMARY KEY, material_id TEXT NOT NULL REFERENCES materials(id) ON DELETE CASCADE,
    chunk_id TEXT NOT NULL REFERENCES material_chunks(id) ON DELETE CASCADE,
    embedding TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS summaries (
    id TEXT PRIMARY KEY, material_id TEXT NOT NULL UNIQUE REFERENCES materials(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE, summary TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'completed', model_name TEXT, error_message TEXT,
    time_taken REAL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS material_glossary (
    id TEXT PRIMARY KEY, material_id TEXT NOT NULL REFERENCES materials(id) ON DELETE CASCADE,
    word TEXT NOT NULL, normalized_word TEXT NOT NULL, meaning TEXT NOT NULL,
    synonym TEXT NOT NULL, language TEXT NOT NULL DEFAULT '', source TEXT NOT NULL DEFAULT 'generated',
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    UNIQUE(material_id, normalized_word)
);
CREATE TABLE IF NOT EXISTS difficult_concepts (
    id TEXT PRIMARY KEY, material_id TEXT NOT NULL UNIQUE REFERENCES materials(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE, concepts TEXT NOT NULL,
    model_name TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS page_summaries (
    id TEXT PRIMARY KEY, material_id TEXT NOT NULL REFERENCES materials(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE, page_number INTEGER NOT NULL,
    summary TEXT NOT NULL, model_name TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    UNIQUE(material_id, page_number)
);
CREATE TABLE IF NOT EXISTS quizzes (
    id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    material_id TEXT REFERENCES materials(id) ON DELETE CASCADE, source_type TEXT,
    difficulty TEXT, mcq_count INTEGER, tf_count INTEGER, quiz_data TEXT,
    status TEXT NOT NULL DEFAULT 'completed', model_name TEXT, error_message TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS quiz_attempts (
    id TEXT PRIMARY KEY, quiz_id TEXT NOT NULL REFERENCES quizzes(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE, score INTEGER,
    total INTEGER, results TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chat_sessions (
    id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    material_id TEXT NOT NULL REFERENCES materials(id) ON DELETE CASCADE, title TEXT,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chat_messages (
    id TEXT PRIMARY KEY, session_id TEXT REFERENCES chat_sessions(id) ON DELETE CASCADE,
    material_id TEXT, user_id TEXT, role TEXT, content TEXT, metadata TEXT,
    retrieved_chunk_ids TEXT, messages TEXT, created_at TEXT NOT NULL, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS refresh_tokens (
    token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    email TEXT NOT NULL DEFAULT '', expires_at TEXT NOT NULL, revoked INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_materials_user ON materials(user_id);
CREATE INDEX IF NOT EXISTS idx_chunks_material ON material_chunks(material_id, chunk_index);
CREATE INDEX IF NOT EXISTS idx_embeddings_material ON material_embeddings(material_id);
CREATE INDEX IF NOT EXISTS idx_glossary_material ON material_glossary(material_id, normalized_word);
CREATE INDEX IF NOT EXISTS idx_concepts_material ON difficult_concepts(material_id);
CREATE INDEX IF NOT EXISTS idx_page_summaries_material ON page_summaries(material_id, page_number);
CREATE INDEX IF NOT EXISTS idx_sessions_material_user ON chat_sessions(material_id, user_id);
CREATE INDEX IF NOT EXISTS idx_messages_session ON chat_messages(session_id, created_at);
"""


@dataclass
class LocalResponse:
    data: Any


class LocalQuery:
    def __init__(self, database: "LocalDatabase", table: str):
        self.database, self.table = database, table
        self.operation, self.payload, self.columns = "select", None, "*"
        self.filters: list[tuple[str, Any]] = []
        self.order_by: Optional[str] = None
        self.desc, self.single = False, False
        self.row_limit: Optional[int] = None
        self.conflict_column: Optional[str] = None
        self.ignore_duplicates = False

    def select(self, columns: str = "*"):
        self.operation, self.columns = "select", columns
        return self

    def insert(self, data: Any):
        self.operation, self.payload = "insert", data
        return self

    def upsert(self, data: Any, on_conflict: str = "id", ignore_duplicates: bool = False):
        self.operation, self.payload = "upsert", data
        self.conflict_column, self.ignore_duplicates = on_conflict, ignore_duplicates
        return self

    def update(self, data: dict):
        self.operation, self.payload = "update", data
        return self

    def delete(self):
        self.operation = "delete"
        return self

    def eq(self, field: str, value: Any):
        self.filters.append((field, value))
        return self

    def order(self, field: str, desc: bool = False):
        self.order_by, self.desc = field, desc
        return self

    def limit(self, count: int):
        self.row_limit = count
        return self

    def maybe_single(self):
        self.single = True
        return self

    def execute(self) -> LocalResponse:
        return self.database.execute(self)


class LocalRPC:
    def __init__(self, database: "LocalDatabase", name: str, params: dict):
        self.database, self.name, self.params = database, name, params

    def execute(self) -> LocalResponse:
        if self.name == "search_materials_by_title":
            query = str(self.params.get("p_query", "")).strip().lower()
            user_id = str(self.params.get("p_user_id", ""))
            with self.database.connection() as conn:
                rows = conn.execute(
                    "SELECT * FROM materials WHERE user_id = ? AND lower(title) LIKE ? ORDER BY created_at DESC",
                    (user_id, f"%{query}%"),
                ).fetchall()
            return LocalResponse([self.database.decode_row("materials", row) for row in rows])

        if self.name == "match_material_chunks":
            query_embedding = self.params.get("query_embedding") or []
            material_id = str(self.params.get("match_material_id", ""))
            threshold = float(self.params.get("match_threshold", 0.0))
            count = int(self.params.get("match_count", 5))
            with self.database.connection() as conn:
                rows = conn.execute(
                    """SELECT e.chunk_id, e.embedding, c.content
                       FROM material_embeddings e JOIN material_chunks c ON c.id = e.chunk_id
                       WHERE e.material_id = ?""",
                    (material_id,),
                ).fetchall()
            matches = []
            for row in rows:
                similarity = _cosine_similarity(query_embedding, json.loads(row["embedding"]))
                if similarity >= threshold:
                    matches.append({"chunk_id": row["chunk_id"], "content": row["content"], "similarity": similarity})
            matches.sort(key=lambda item: item["similarity"], reverse=True)
            return LocalResponse(matches[:count])

        raise ValueError(f"Unknown local database function: {self.name}")


class LocalDatabase:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        with self.connection() as conn:
            conn.executescript(SCHEMA)
            columns = {row[1] for row in conn.execute("PRAGMA table_info(material_chunks)")}
            if "page_number" not in columns:
                conn.execute("ALTER TABLE material_chunks ADD COLUMN page_number INTEGER")
            conn.commit()

    @contextmanager
    def connection(self):
        conn = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        try:
            yield conn
        finally:
            conn.close()

    def table(self, name: str) -> LocalQuery:
        return LocalQuery(self, name)

    def rpc(self, name: str, params: dict) -> LocalRPC:
        return LocalRPC(self, name, params)

    def decode_row(self, table: str, row: sqlite3.Row | dict) -> dict:
        result = dict(row)
        for column in JSON_COLUMNS.get(table, set()):
            value = result.get(column)
            if isinstance(value, str) and value:
                try:
                    result[column] = json.loads(value)
                except json.JSONDecodeError:
                    pass
        return result

    def _prepare(self, table: str, data: dict, add_defaults: bool = True) -> dict:
        prepared = dict(data)
        if add_defaults:
            prepared.setdefault("id", str(uuid.uuid4()))
            prepared.setdefault("created_at", datetime.now(timezone.utc).isoformat())
        for column in JSON_COLUMNS.get(table, set()):
            if column in prepared and not isinstance(prepared[column], str):
                prepared[column] = json.dumps(prepared[column], ensure_ascii=False)
        return prepared

    def execute(self, query: LocalQuery) -> LocalResponse:
        with self._lock, self.connection() as conn:
            where = " AND ".join(f'"{field}" = ?' for field, _ in query.filters)
            params = [value for _, value in query.filters]
            where_sql = f" WHERE {where}" if where else ""

            if query.operation == "select":
                sql = f'SELECT {query.columns} FROM "{query.table}"{where_sql}'
                if query.order_by:
                    sql += f' ORDER BY "{query.order_by}" {"DESC" if query.desc else "ASC"}'
                if query.row_limit is not None:
                    sql += " LIMIT ?"
                    params.append(query.row_limit)
                rows = conn.execute(sql, params).fetchall()
                data = [self.decode_row(query.table, row) for row in rows]
                return LocalResponse(data[0] if query.single and data else (None if query.single else data))

            if query.operation in {"insert", "upsert"}:
                items = query.payload if isinstance(query.payload, list) else [query.payload]
                inserted = []
                for raw in items:
                    data = self._prepare(query.table, raw)
                    columns = list(data)
                    placeholders = ", ".join("?" for _ in columns)
                    sql = f'INSERT INTO "{query.table}" ({", ".join(columns)}) VALUES ({placeholders})'
                    if query.operation == "upsert":
                        conflict = query.conflict_column or "id"
                        conflict_columns = [column.strip() for column in conflict.split(",")]
                        if query.ignore_duplicates:
                            sql += f" ON CONFLICT({conflict}) DO NOTHING"
                        else:
                            updates = [column for column in columns if column not in conflict_columns]
                            sql += f" ON CONFLICT({conflict}) DO UPDATE SET " + ", ".join(
                                f'"{column}" = excluded."{column}"' for column in updates
                            )
                    conn.execute(sql, [data[column] for column in columns])
                    key_columns = [column.strip() for column in (query.conflict_column or "id").split(",")]
                    key_where = " AND ".join(f'"{column}" = ?' for column in key_columns)
                    row = conn.execute(
                        f'SELECT * FROM "{query.table}" WHERE {key_where}',
                        [data[column] for column in key_columns],
                    ).fetchone()
                    if row:
                        inserted.append(self.decode_row(query.table, row))
                conn.commit()
                return LocalResponse(inserted)

            if query.operation == "update":
                data = self._prepare(query.table, query.payload, add_defaults=False)
                assignments = ", ".join(f'"{column}" = ?' for column in data)
                conn.execute(
                    f'UPDATE "{query.table}" SET {assignments}{where_sql}',
                    [data[column] for column in data] + params,
                )
                conn.commit()
                rows = conn.execute(f'SELECT * FROM "{query.table}"{where_sql}', params).fetchall()
                return LocalResponse([self.decode_row(query.table, row) for row in rows])

            if query.operation == "delete":
                conn.execute(f'DELETE FROM "{query.table}"{where_sql}', params)
                conn.commit()
                return LocalResponse([])

        raise ValueError(f"Unsupported operation: {query.operation}")


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    return dot / (left_norm * right_norm) if left_norm and right_norm else 0.0


_database: Optional[LocalDatabase] = None


def get_database() -> LocalDatabase:
    global _database
    if _database is None:
        _database = LocalDatabase(Path(settings.sqlite_path))
    return _database


def warmup_database() -> None:
    with get_database().connection() as conn:
        conn.execute("SELECT 1").fetchone()
