# SPDX-License-Identifier: MPL-2.0
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from app.cognitive_loop.discourse import DiscourseState, DiscourseUpdate, reduce_state
from app.cognitive_loop.types import RetrievalHit
from app.connectors.local_files import SKIP_DIRECTORIES, STOP_WORDS, TEXT_SUFFIXES


def _inside(path: Path, roots: tuple[Path, ...]) -> bool:
    resolved = path.resolve()
    return any(resolved == root or root in resolved.parents for root in roots)


def _tokens(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9][a-z0-9_-]{2,}", text.casefold())
        if token not in STOP_WORDS
    }


class RuntimeStore:
    """Durable receipts, discourse state, and operator-created knowledge index."""

    def __init__(self, path: Path, authorized_roots: tuple[Path, ...]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._path = path
        self._authorized_roots = authorized_roots
        self._db_lock = threading.Lock()
        self._session_locks: dict[str, asyncio.Lock] = {}
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS turns (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    created REAL NOT NULL,
                    receipt TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS turns_session_created ON turns(session_id, created DESC);
                CREATE TABLE IF NOT EXISTS discourse_states (
                    session_id TEXT PRIMARY KEY,
                    state TEXT NOT NULL,
                    updated REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS knowledge_documents (
                    source_id TEXT NOT NULL,
                    locator TEXT NOT NULL,
                    content_sha256 TEXT NOT NULL,
                    text TEXT NOT NULL,
                    updated REAL NOT NULL,
                    PRIMARY KEY(source_id, locator)
                );
                """
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._path)

    def _read_state(self, session_id: str) -> DiscourseState:
        with self._db_lock, self._connect() as db:
            row = db.execute(
                "SELECT state FROM discourse_states WHERE session_id = ?", (session_id,)
            ).fetchone()
        return DiscourseState.from_dict(json.loads(row[0])) if row else DiscourseState(session_id=session_id)

    async def discourse(self, session_id: str) -> DiscourseState:
        return await asyncio.to_thread(self._read_state, session_id)

    async def commit_discourse(self, update: DiscourseUpdate) -> DiscourseState:
        """Serialize one atomic state transition per session."""
        lock = self._session_locks.setdefault(update.session_id, asyncio.Lock())
        async with lock:
            before = await asyncio.to_thread(self._read_state, update.session_id)
            after = reduce_state(before, update)
            payload = json.dumps(after.to_dict(), sort_keys=True, separators=(",", ":"))

            def write() -> None:
                with self._db_lock, self._connect() as db:
                    db.execute(
                        "INSERT INTO discourse_states(session_id, state, updated) VALUES(?, ?, ?) "
                        "ON CONFLICT(session_id) DO UPDATE SET state=excluded.state, updated=excluded.updated",
                        (update.session_id, payload, time.time()),
                    )

            await asyncio.to_thread(write)
            return after

    async def write_turn(self, turn_id: str, session_id: str, receipt: dict[str, Any]) -> None:
        payload = json.dumps(receipt, sort_keys=True, separators=(",", ":"))

        def write() -> None:
            with self._db_lock, self._connect() as db:
                db.execute(
                    "INSERT INTO turns(id, session_id, created, receipt) VALUES(?, ?, ?, ?)",
                    (turn_id, session_id, time.time(), payload),
                )

        await asyncio.to_thread(write)

    async def last_turn(self, session_id: str | None = None) -> dict[str, Any] | None:
        def read() -> dict[str, Any] | None:
            statement = "SELECT receipt FROM turns"
            parameters: tuple[str, ...] = ()
            if session_id:
                statement += " WHERE session_id = ?"
                parameters = (session_id,)
            statement += " ORDER BY created DESC LIMIT 1"
            with self._db_lock, self._connect() as db:
                row = db.execute(statement, parameters).fetchone()
            return json.loads(row[0]) if row else None

        return await asyncio.to_thread(read)

    async def ingest_root(self, source_id: str, root: Path) -> dict[str, Any]:
        root = root.resolve()
        if not _inside(root, self._authorized_roots):
            raise ValueError("the requested root is not covered by an explicit read grant")
        if not root.is_dir():
            raise ValueError("the requested root is not a directory")

        def ingest() -> dict[str, Any]:
            documents: list[tuple[str, str, str, str, float]] = []
            for current, directories, files in os.walk(root):
                directories[:] = sorted(item for item in directories if item not in SKIP_DIRECTORIES)
                for name in sorted(files):
                    path = Path(current) / name
                    if path.suffix.casefold() not in TEXT_SUFFIXES or not _inside(path, self._authorized_roots):
                        continue
                    try:
                        if path.stat().st_size > 2_000_000:
                            continue
                        content = path.read_text(encoding="utf-8")
                    except (OSError, UnicodeDecodeError):
                        continue
                    locator = path.relative_to(root).as_posix()
                    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
                    documents.append((source_id, locator, digest, content, time.time()))
                    if len(documents) >= 20000:
                        break
            with self._db_lock, self._connect() as db:
                db.execute("DELETE FROM knowledge_documents WHERE source_id = ?", (source_id,))
                db.executemany(
                    "INSERT INTO knowledge_documents(source_id, locator, content_sha256, text, updated) VALUES(?, ?, ?, ?, ?)",
                    documents,
                )
            return {"source_id": source_id, "documents": len(documents), "root_label": root.name}

        return await asyncio.to_thread(ingest)

    async def search_knowledge(self, query: str, *, limit: int = 6) -> tuple[RetrievalHit, ...]:
        def search() -> tuple[RetrievalHit, ...]:
            with self._db_lock, self._connect() as db:
                rows = db.execute(
                    "SELECT source_id, locator, content_sha256, text FROM knowledge_documents"
                ).fetchall()
            query_tokens = _tokens(query)
            scored: list[RetrievalHit] = []
            for source_id, locator, digest, content in rows:
                overlap = len(query_tokens & _tokens(f"{locator} {content[:120000]}"))
                if not overlap:
                    continue
                scored.append(
                    RetrievalHit(
                        source_id=str(source_id),
                        locator=str(locator),
                        text=str(content)[:12000],
                        score=overlap / max(1, len(query_tokens)),
                        content_sha256=str(digest),
                    )
                )
            scored.sort(key=lambda hit: (-hit.score, hit.source_id, hit.locator))
            return tuple(scored[: max(1, min(limit, 20))])

        return await asyncio.to_thread(search)

    def knowledge_status(self) -> dict[str, object]:
        with self._db_lock, self._connect() as db:
            row = db.execute(
                "SELECT COUNT(*), COUNT(DISTINCT source_id) FROM knowledge_documents"
            ).fetchone()
        return {"id": "local-index", "kind": "sqlite_index", "available": bool(row[0]), "documents": row[0], "sources": row[1]}


class IndexedKnowledgeSource:
    source_id = "local-index"

    def __init__(self, store: RuntimeStore) -> None:
        self._store = store

    async def search(self, query: str, *, limit: int = 6) -> tuple[RetrievalHit, ...]:
        return await self._store.search_knowledge(query, limit=limit)

    def status(self) -> dict[str, object]:
        return self._store.knowledge_status()
