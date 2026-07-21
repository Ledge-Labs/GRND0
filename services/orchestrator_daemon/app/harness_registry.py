# SPDX-License-Identifier: MPL-2.0
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Harness:
    name: str
    contract: str
    role: str
    system_prompt: str
    lane: str
    knowledge_scope: tuple[str, ...]
    response_schema: dict[str, Any] | None = None


class HarnessRegistry:
    """Fail-closed registry for every internal model call."""

    def __init__(self, root: Path) -> None:
        items: dict[str, Harness] = {}
        for path in sorted(root.glob("*.json")):
            raw = json.loads(path.read_text(encoding="utf-8"))
            required = {"name", "contract", "role", "system_prompt", "lane", "knowledge_scope"}
            missing = sorted(required - raw.keys())
            if missing:
                raise RuntimeError(f"harness {path.name} lacks fields: {', '.join(missing)}")
            name = str(raw["name"]).strip()
            if not name or name in items:
                raise RuntimeError(f"duplicate or empty harness name: {name!r}")
            scope = raw["knowledge_scope"]
            if not isinstance(scope, list) or not all(isinstance(item, str) for item in scope):
                raise RuntimeError(f"harness {name} has an invalid knowledge scope")
            schema = raw.get("response_schema")
            if schema is not None and not isinstance(schema, dict):
                raise RuntimeError(f"harness {name} has an invalid response schema")
            items[name] = Harness(
                name=name,
                contract=str(raw["contract"]).strip(),
                role=str(raw["role"]).strip(),
                system_prompt=str(raw["system_prompt"]).strip(),
                lane=str(raw["lane"]).strip(),
                knowledge_scope=tuple(scope),
                response_schema=schema,
            )
        if not items:
            raise RuntimeError("the harness registry is empty")
        self._items = items

    def require(self, name: str) -> Harness:
        try:
            return self._items[name]
        except KeyError as exc:
            raise ValueError(f"unknown harness: {name}") from exc

    def names(self) -> list[str]:
        return sorted(self._items)

