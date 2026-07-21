# SPDX-License-Identifier: MPL-2.0
from __future__ import annotations

import hashlib
from typing import Any

import httpx

from app.cognitive_loop.types import RetrievalHit


class HttpVectorSource:
    """Text-query adapter for a vector service owned by the operator.

    The service receives ``{"query": str, "limit": int}`` and returns a JSON
    object with ``hits``. Each hit contains ``text`` and may contain ``id``,
    ``score``, and ``metadata``. Embedding choice and index calibration remain
    properties of the connected service.
    """

    def __init__(self, source_id: str, query_url: str, token: str = "") -> None:
        self.source_id = source_id
        self._query_url = query_url
        self._token = token

    def status(self) -> dict[str, object]:
        return {"id": self.source_id, "kind": "vector_http", "available": bool(self._query_url)}

    async def search(self, query: str, *, limit: int = 6) -> tuple[RetrievalHit, ...]:
        headers = {"Authorization": f"Bearer {self._token}"} if self._token else {}
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(self._query_url, headers=headers, json={"query": query, "limit": limit})
        response.raise_for_status()
        body = response.json()
        raw_hits = body.get("hits", []) if isinstance(body, dict) else []
        hits: list[RetrievalHit] = []
        for index, raw in enumerate(raw_hits):
            if not isinstance(raw, dict) or not str(raw.get("text") or "").strip():
                continue
            text = str(raw["text"])
            metadata = raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}
            locator = str(raw.get("id") or metadata.get("path") or f"hit-{index + 1}")
            hits.append(RetrievalHit(self.source_id, locator, text[:12000], float(raw.get("score") or 0.0), hashlib.sha256(text.encode()).hexdigest()))
        return tuple(hits[:limit])

