# SPDX-License-Identifier: MPL-2.0
from __future__ import annotations

import asyncio
import hashlib
import os
import re
from pathlib import Path

from app.cognitive_loop.types import RetrievalHit


TEXT_SUFFIXES = {".md", ".markdown", ".txt", ".rst", ".py", ".json", ".yaml", ".yml", ".toml"}
SKIP_DIRECTORIES = {".git", ".venv", "node_modules", "__pycache__", ".obsidian", ".trash"}
STOP_WORDS = {
    "about", "and", "answer", "are", "can", "connected", "could", "does", "evidence", "for",
    "from", "give", "grounded", "has", "have", "into", "its", "none", "not", "only", "please",
    "question", "report", "search", "should", "source", "the", "use", "was", "were",
    "supports", "that", "their", "them", "then", "there", "these", "this", "through",
    "using", "what", "when", "where", "which", "with", "would",
}


def _inside(path: Path, roots: tuple[Path, ...]) -> bool:
    resolved = path.resolve()
    return any(resolved == root or root in resolved.parents for root in roots)


def _tokens(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9][a-z0-9_-]{2,}", text.casefold())
        if token not in STOP_WORDS
    }


class LocalFilesSource:
    def __init__(
        self,
        source_id: str,
        root: Path,
        *,
        authorized_roots: tuple[Path, ...],
        public_root: Path,
        trusted_public: bool = False,
        max_files: int = 4000,
        max_file_bytes: int = 500_000,
    ) -> None:
        self.source_id = source_id
        self.root = root.resolve()
        permitted = authorized_roots
        if trusted_public and _inside(self.root, (public_root.resolve(),)):
            permitted = (*permitted, public_root.resolve())
        if not _inside(self.root, permitted):
            raise RuntimeError(f"knowledge source {source_id} is outside authorized roots")
        self._permitted = permitted
        self._max_files = max(1, min(max_files, 20000))
        self._max_file_bytes = max(1024, min(max_file_bytes, 2_000_000))

    def status(self) -> dict[str, object]:
        return {"id": self.source_id, "kind": "local_files", "available": self.root.is_dir()}

    def _documents(self) -> list[tuple[Path, str]]:
        found: list[tuple[Path, str]] = []
        if not self.root.is_dir():
            return found
        for current, directories, files in os.walk(self.root):
            directories[:] = sorted(name for name in directories if name not in SKIP_DIRECTORIES)
            for name in sorted(files):
                path = Path(current) / name
                if path.suffix.casefold() not in TEXT_SUFFIXES or not _inside(path, self._permitted):
                    continue
                try:
                    if path.stat().st_size > self._max_file_bytes:
                        continue
                    text = path.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    continue
                found.append((path, text))
                if len(found) >= self._max_files:
                    return found
        return found

    async def search(self, query: str, *, limit: int = 6) -> tuple[RetrievalHit, ...]:
        query_tokens = _tokens(query)

        def run() -> tuple[RetrievalHit, ...]:
            scored: list[RetrievalHit] = []
            for path, text in self._documents():
                haystack = _tokens(path.name + " " + text[:120000])
                overlap = len(query_tokens & haystack)
                if not overlap:
                    continue
                score = overlap / max(1, len(query_tokens))
                locator = path.relative_to(self.root).as_posix()
                excerpt = text[:12000]
                scored.append(
                    RetrievalHit(
                        source_id=self.source_id,
                        locator=locator,
                        text=excerpt,
                        score=score,
                        content_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                    )
                )
            scored.sort(key=lambda hit: (-hit.score, hit.locator))
            return tuple(scored[: max(1, min(limit, 20))])

        return await asyncio.to_thread(run)
