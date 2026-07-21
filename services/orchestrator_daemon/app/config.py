# SPDX-License-Identifier: MPL-2.0
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def _flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _json_env(name: str, default: Any) -> Any:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{name} must contain valid JSON") from exc


def _roots() -> tuple[Path, ...]:
    values = _json_env("GRND0_AUTHORIZED_READ_ROOTS", [])
    if not isinstance(values, list) or not all(isinstance(item, str) for item in values):
        raise RuntimeError("GRND0_AUTHORIZED_READ_ROOTS must be a JSON string array")
    return tuple(Path(item).expanduser().resolve() for item in values if item.strip())


@dataclass(frozen=True)
class Settings:
    api_key: str
    gateway_url: str
    gateway_token: str
    database_path: Path
    harness_path: Path
    lanes_path: Path
    sources_path: Path
    auth_required: bool
    debug_routes: bool
    authorized_read_roots: tuple[Path, ...] = ()
    allow_web: bool = False
    web_research_url: str = ""
    capability_token: str = ""
    allow_git: bool = False
    gitea_url: str = ""
    gitea_username: str = ""
    gitea_password: str = ""
    rlm_threshold_chars: int = 24000

    @classmethod
    def from_env(cls) -> "Settings":
        auth_required = _flag("GRND0_AUTH_REQUIRED", True)
        bind_host = os.getenv("GRND0_BIND_HOST", "127.0.0.1").strip()
        if bind_host == "0.0.0.0" and not auth_required:
            raise RuntimeError("public binding requires GRND0_AUTH_REQUIRED=true")
        allow_web = _flag("GRND0_ALLOW_WEB", False)
        allow_git = _flag("GRND0_ALLOW_GIT", False)
        capability_token = _required("GRND0_CAPABILITY_TOKEN") if (allow_web or allow_git) else os.getenv("GRND0_CAPABILITY_TOKEN", "")
        return cls(
            api_key=_required("GRND0_API_KEY") if auth_required else "",
            gateway_url=_required("GRND0_GATEWAY_URL").rstrip("/"),
            gateway_token=_required("GRND0_GATEWAY_TOKEN"),
            database_path=Path(os.getenv("GRND0_DATABASE_PATH", "/var/lib/grnd0/state.sqlite")),
            harness_path=Path(os.getenv("GRND0_HARNESS_PATH", "/app/data/harness_templates")),
            lanes_path=Path(os.getenv("GRND0_LANES_PATH", "/app/configs/lanes.example.json")),
            sources_path=Path(os.getenv("GRND0_SOURCES_PATH", "/app/configs/knowledge-sources.example.json")),
            auth_required=auth_required,
            debug_routes=_flag("GRND0_DEBUG_ROUTES", False),
            authorized_read_roots=_roots(),
            allow_web=allow_web,
            web_research_url=os.getenv("GRND0_WEB_RESEARCH_URL", "http://web_research:8090").rstrip("/"),
            capability_token=capability_token,
            allow_git=allow_git,
            gitea_url=os.getenv("GRND0_GITEA_URL", "http://source_forge:3000").rstrip("/"),
            gitea_username=os.getenv("GRND0_GITEA_USERNAME", "grnd0-admin").strip(),
            gitea_password=os.getenv("GRND0_GITEA_PASSWORD", "").strip(),
            rlm_threshold_chars=max(8000, int(os.getenv("GRND0_RLM_THRESHOLD_CHARS", "24000"))),
        )

