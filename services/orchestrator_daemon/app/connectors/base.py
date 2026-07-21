# SPDX-License-Identifier: MPL-2.0
from __future__ import annotations

from typing import Protocol

from app.cognitive_loop.types import RetrievalHit


class KnowledgeSource(Protocol):
    source_id: str

    async def search(self, query: str, *, limit: int = 6) -> tuple[RetrievalHit, ...]: ...

    def status(self) -> dict[str, object]: ...


class VectorStoreSource(Protocol):
    """Adapter contract for operator-provided vector retrieval services."""

    source_id: str

    async def search(self, query: str, *, limit: int = 6) -> tuple[RetrievalHit, ...]: ...

