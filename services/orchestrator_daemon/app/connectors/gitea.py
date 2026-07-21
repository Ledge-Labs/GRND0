# SPDX-License-Identifier: MPL-2.0
from __future__ import annotations

import base64
import hashlib
from typing import Any
from urllib.parse import quote

import httpx

from app.cognitive_loop.types import RetrievalHit


class GiteaSource:
    def __init__(self, source_id: str, base_url: str, username: str, password: str, *, granted: bool) -> None:
        self.source_id = source_id
        self._base_url = base_url.rstrip("/")
        self._username = username
        self._password = password
        self._granted = granted and bool(password)

    def status(self) -> dict[str, object]:
        return {"id": self.source_id, "kind": "local_git", "available": self._granted}

    async def search(self, query: str, *, limit: int = 6) -> tuple[RetrievalHit, ...]:
        if not self._granted:
            return ()
        auth = (self._username, self._password)
        async with httpx.AsyncClient(timeout=30.0, auth=auth) as client:
            repositories = await client.get(f"{self._base_url}/api/v1/user/repos", params={"limit": 20})
            if not repositories.is_success:
                return ()
            query_terms = {part.casefold() for part in query.split() if len(part) >= 3}
            candidates: list[tuple[float, str, str, str]] = []
            for repository in repositories.json():
                owner = str(repository.get("owner", {}).get("login") or "")
                name = str(repository.get("name") or "")
                branch = str(repository.get("default_branch") or "main")
                if not owner or not name:
                    continue
                tree = await client.get(
                    f"{self._base_url}/api/v1/repos/{quote(owner)}/{quote(name)}/git/trees/{quote(branch)}",
                    params={"recursive": "true", "page": 1, "per_page": 500},
                )
                if not tree.is_success:
                    continue
                for entry in tree.json().get("tree", []):
                    path = str(entry.get("path") or "")
                    if entry.get("type") != "blob" or not path.lower().endswith((".md", ".txt", ".py", ".json", ".yaml", ".yml", ".toml")):
                        continue
                    score = len(query_terms & {part.casefold() for part in path.replace("/", " ").replace("_", " ").split()})
                    candidates.append((float(score), owner, name, path))
            candidates.sort(key=lambda item: (-item[0], item[1], item[2], item[3]))
            hits: list[RetrievalHit] = []
            for score, owner, name, path in candidates[: max(limit * 3, limit)]:
                response = await client.get(
                    f"{self._base_url}/api/v1/repos/{quote(owner)}/{quote(name)}/contents/{quote(path, safe='/')}"
                )
                if not response.is_success:
                    continue
                raw = response.json()
                try:
                    text = base64.b64decode(str(raw.get("content") or "")).decode("utf-8")
                except (ValueError, UnicodeDecodeError):
                    continue
                body_terms = {part.casefold() for part in text[:100000].split()}
                total = score + len(query_terms & body_terms)
                if total <= 0:
                    continue
                hits.append(RetrievalHit(self.source_id, f"{owner}/{name}/{path}", text[:12000], total, hashlib.sha256(text.encode()).hexdigest()))
                if len(hits) >= limit:
                    break
        return tuple(hits)

