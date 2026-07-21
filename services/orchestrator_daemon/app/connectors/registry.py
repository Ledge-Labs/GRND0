# SPDX-License-Identifier: MPL-2.0
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

from app.config import Settings
from app.cognitive_loop.types import RetrievalBundle, RetrievalHit
from .base import KnowledgeSource
from .gitea import GiteaSource
from .local_files import LocalFilesSource
from .vector_http import HttpVectorSource
from .web import WebSource
from app.store import IndexedKnowledgeSource, RuntimeStore


def _secret(value: str) -> str:
    return os.getenv(value[4:], "") if value.startswith("env:") else value


class ConnectorRegistry:
    def __init__(self, settings: Settings, store: RuntimeStore) -> None:
        raw = json.loads(settings.sources_path.read_text(encoding="utf-8"))
        items = raw.get("sources", []) if isinstance(raw, dict) else []
        sources: list[KnowledgeSource] = []
        public_root = settings.harness_path.parent / "self_knowledge"
        for item in items:
            if not isinstance(item, dict) or not bool(item.get("enabled", False)):
                continue
            kind = str(item.get("kind") or "")
            source_id = str(item.get("id") or "").strip()
            if not source_id:
                raise RuntimeError("every enabled knowledge source requires an id")
            if kind == "local_files":
                root_value = str(item.get("root") or "")
                root = Path(root_value)
                if not root.is_absolute():
                    root = (settings.sources_path.parent / root).resolve()
                sources.append(LocalFilesSource(source_id, root, authorized_roots=settings.authorized_read_roots, public_root=public_root, trusted_public=bool(item.get("trusted_public", False))))
            elif kind == "vector_http":
                sources.append(HttpVectorSource(source_id, _secret(str(item.get("query_url") or "")), _secret(str(item.get("token") or ""))))
            else:
                raise RuntimeError(f"unknown knowledge source kind: {kind}")
        sources.append(WebSource("operator-web", settings.web_research_url, settings.capability_token, granted=settings.allow_web))
        sources.append(GiteaSource("operator-git", settings.gitea_url, settings.gitea_username, settings.gitea_password, granted=settings.allow_git))
        sources.append(IndexedKnowledgeSource(store))
        self._sources = tuple(sources)

    def status(self) -> list[dict[str, object]]:
        return [source.status() for source in self._sources]

    def active_ids(self) -> tuple[str, ...]:
        return tuple(str(item["id"]) for item in self.status() if bool(item["available"]))

    async def search(
        self,
        query: str,
        *,
        limit: int = 8,
        source_ids: tuple[str, ...] | None = None,
    ) -> RetrievalBundle:
        active = [source for source in self._sources if bool(source.status().get("available"))]
        if source_ids is not None:
            active = [source for source in active if source.source_id in source_ids]
        if not active:
            return RetrievalBundle(mode="model_knowledge_only", notes=("no_connected_sources",))
        results = await asyncio.gather(
            *(source.search(query, limit=max(2, limit // len(active) + 1)) for source in active),
            return_exceptions=True,
        )
        hits: list[RetrievalHit] = []
        notes: list[str] = []
        for source, result in zip(active, results):
            if isinstance(result, Exception):
                notes.append(f"{source.source_id}:unavailable")
            else:
                hits.extend(result)
        hits.sort(key=lambda hit: (-hit.score, hit.source_id, hit.locator))
        return RetrievalBundle(
            mode="connected" if hits else "connected_no_hits",
            hits=tuple(hits[:limit]),
            connected_sources=tuple(source.source_id for source in active),
            notes=tuple(notes),
        )
