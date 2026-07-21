# SPDX-License-Identifier: MPL-2.0
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from app.harness_registry import Harness


@dataclass(frozen=True)
class Lane:
    name: str
    model: str
    backend: str
    backend_kind: str
    roles: tuple[str, ...]
    min_effort: int = 0
    max_effort: int = 3
    priority: int = 100


def _enabled(value: object, env_name: str) -> bool:
    if bool(value):
        return True
    return bool(env_name and os.getenv(env_name, "").strip().lower() in {"1", "true", "yes", "on"})


class LaneRouter:
    """Deterministic selection across the lanes supplied by an operator."""

    def __init__(self, path: Path) -> None:
        raw = json.loads(path.read_text(encoding="utf-8"))
        entries = raw.get("lanes") if isinstance(raw, dict) else None
        backends = raw.get("backends") if isinstance(raw, dict) else None
        if not isinstance(backends, dict) or not backends:
            raise RuntimeError("lane configuration must contain explicit backends")
        if not isinstance(entries, list) or not entries:
            raise RuntimeError("lane configuration must contain at least one lane")
        lanes: list[Lane] = []
        for item in entries:
            if not isinstance(item, dict):
                raise RuntimeError("lane entries must be objects")
            backend_id = str(item.get("backend") or "").strip()
            backend = backends.get(backend_id)
            if not isinstance(backend, dict):
                raise RuntimeError(f"lane backend {backend_id!r} is not declared")
            backend_enabled = _enabled(backend.get("enabled", True), str(backend.get("enable_env") or ""))
            lane_enabled = _enabled(item.get("enabled", True), str(item.get("enable_env") or ""))
            if not backend_enabled or not lane_enabled:
                continue
            roles = item.get("roles", ["*"])
            lane = Lane(
                name=str(item.get("name") or "").strip(),
                model=str(item.get("model") or "").strip(),
                backend=backend_id,
                backend_kind=str(backend.get("kind") or "").strip(),
                roles=tuple(str(role).strip() for role in roles),
                min_effort=int(item.get("min_effort", 0)),
                max_effort=int(item.get("max_effort", 3)),
                priority=int(item.get("priority", 100)),
            )
            if not lane.name or lane.min_effort > lane.max_effort:
                raise RuntimeError("lane name and effort bounds are required")
            if lane.backend_kind not in {"local", "cloud"}:
                raise RuntimeError("backend kind must be local or cloud")
            lanes.append(lane)
        if not lanes:
            raise RuntimeError("lane configuration has no enabled lanes")
        self._lanes = tuple(sorted(lanes, key=lambda lane: (lane.priority, lane.name)))

    def select(self, harness: Harness, effort: int) -> Lane:
        candidates = [
            lane
            for lane in self._lanes
            if lane.min_effort <= effort <= lane.max_effort
            and (harness.role in lane.roles or harness.lane in lane.roles or "*" in lane.roles)
        ]
        if not candidates:
            candidates = [lane for lane in self._lanes if lane.min_effort <= effort <= lane.max_effort]
        if not candidates:
            candidates = list(self._lanes)
        return candidates[0]

    def public_inventory(self) -> list[dict[str, object]]:
        return [
            {
                "name": lane.name,
                "backend": lane.backend,
                "backend_kind": lane.backend_kind,
                "model": lane.model or "operator-configured",
                "roles": list(lane.roles),
                "effort": [lane.min_effort, lane.max_effort],
            }
            for lane in self._lanes
        ]
