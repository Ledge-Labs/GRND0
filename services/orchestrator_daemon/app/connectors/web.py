# SPDX-License-Identifier: MPL-2.0
from __future__ import annotations

import hashlib
import re
from typing import Any

import httpx

from app.cognitive_loop.types import RetrievalHit


class WebSource:
    def __init__(self, source_id: str, service_url: str, token: str, *, granted: bool) -> None:
        self.source_id = source_id
        self._service_url = service_url.rstrip("/")
        self._token = token
        self._granted = granted

    def status(self) -> dict[str, object]:
        return {"id": self.source_id, "kind": "web", "available": self._granted}

    async def search(self, query: str, *, limit: int = 6) -> tuple[RetrievalHit, ...]:
        if not self._granted:
            return ()
        headers = {"Authorization": f"Bearer {self._token}"}
        search_query = query.split("?", 1)[0].strip()
        search_query = re.sub(r"^(?:what|who)\s+is\s+(?:the\s+)?", "", search_query, flags=re.IGNORECASE)
        search_query = search_query or query
        async with httpx.AsyncClient(timeout=45.0) as client:
            response = await client.post(
                f"{self._service_url}/search",
                headers=headers,
                json={"query": search_query, "limit": min(limit, 8)},
            )
            response.raise_for_status()
            results = response.json().get("results", [])
            hits: list[RetrievalHit] = []
            for item in results[:limit]:
                if not isinstance(item, dict):
                    continue
                url = str(item.get("url") or "")
                text = str(item.get("snippet") or "")
                try:
                    fetched = await client.post(
                        f"{self._service_url}/fetch",
                        headers=headers,
                        json={"url": url, "render": True},
                    )
                    if fetched.is_success:
                        text = str(fetched.json().get("text") or text)
                except httpx.HTTPError:
                    pass
                if not url or not text:
                    continue
                hits.append(
                    RetrievalHit(
                        source_id=self.source_id,
                        locator=url,
                        text=text[:16000],
                        score=float(item.get("score") or 0.5),
                        content_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                    )
                )
        return tuple(hits)
