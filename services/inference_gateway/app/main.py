# SPDX-License-Identifier: MPL-2.0
from __future__ import annotations

import json
import os
import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, ConfigDict


def required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


TOKEN = required("GRND0_GATEWAY_TOKEN")
STUB_MODE = flag("GRND0_STUB_MODE")
LANES_PATH = Path(os.getenv("GRND0_LANES_PATH", "/app/configs/lanes.example.json"))


@dataclass(frozen=True)
class Backend:
    backend_id: str
    kind: str
    base_url: str
    api_key: str
    model_override: str


def _configuration() -> dict[str, Any]:
    try:
        value = json.loads(LANES_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"invalid lane configuration: {exc}") from exc
    if not isinstance(value, dict) or not isinstance(value.get("backends"), dict):
        raise RuntimeError("lane configuration requires a backend mapping")
    return value


CONFIG = _configuration()


def _is_enabled(item: dict[str, Any]) -> bool:
    if bool(item.get("enabled", True)):
        return True
    env_name = str(item.get("enable_env") or "")
    return bool(env_name and flag(env_name))


def _env_or_literal(item: dict[str, Any], field: str) -> str:
    env_name = str(item.get(f"{field}_env") or "")
    return (os.getenv(env_name, "").strip() if env_name else "") or str(item.get(field) or "").strip()


def resolve_backend(backend_id: str) -> Backend:
    raw = CONFIG["backends"].get(backend_id)
    if not isinstance(raw, dict):
        if backend_id == "operator-provider":
            raw = {
                "kind": "cloud",
                "enabled": True,
                "base_url_env": "GRND0_PROVIDER_BASE_URL",
                "api_key_env": "GRND0_PROVIDER_API_KEY",
                "model_env": "GRND0_PROVIDER_MODEL",
            }
        else:
            raise HTTPException(status_code=503, detail="selected backend is not configured")
    if not _is_enabled(raw):
        raise HTTPException(status_code=503, detail="selected backend is disabled")
    kind = str(raw.get("kind") or "").strip()
    if kind not in {"local", "cloud"}:
        raise HTTPException(status_code=503, detail="selected backend kind is invalid")
    base_url = _env_or_literal(raw, "base_url").rstrip("/")
    model_override = _env_or_literal(raw, "model")
    api_key = _env_or_literal(raw, "api_key")
    if not base_url:
        raise HTTPException(status_code=503, detail="selected backend has no endpoint")
    if kind == "cloud" and not model_override:
        raise HTTPException(status_code=503, detail="selected cloud backend has no model")
    return Backend(backend_id, kind, base_url, api_key, model_override)


def lane_backend(lane_name: str, requested_backend: str) -> str:
    lanes = CONFIG.get("lanes")
    if not isinstance(lanes, list):
        raise HTTPException(status_code=503, detail="lane configuration is invalid")
    lane = next((item for item in lanes if isinstance(item, dict) and item.get("name") == lane_name), None)
    if lane is None:
        raise HTTPException(status_code=400, detail="selected lane is not configured")
    expected = str(lane.get("backend") or "")
    if requested_backend and requested_backend != expected:
        raise HTTPException(status_code=400, detail="lane and backend selection disagree")
    return expected


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    model: str
    messages: list[dict[str, Any]]
    stream: bool = False
    grnd0_harness: str = ""
    grnd0_lane: str = ""
    grnd0_backend: str = ""


def _stub_reply(payload: ChatRequest) -> tuple[str, list[dict[str, Any]]]:
    user_messages = [str(item.get("content", "")) for item in payload.messages if item.get("role") == "user"]
    latest = user_messages[-1] if user_messages else ""
    harness = payload.grnd0_harness
    if harness == "subject-resolution":
        try:
            request = json.loads(latest)
        except json.JSONDecodeError:
            request = {"current_message": latest, "allowed_referents": ["unresolved"]}
        query = str(request.get("current_message") or "")
        menu = [str(item) for item in request.get("allowed_referents", []) if str(item) != "unresolved"]
        dependent = bool(re.search(r"\b(it|that|this|they|them|those|former|latter)\b", query, re.IGNORECASE))
        words = re.findall(r"[A-Za-z0-9][A-Za-z0-9_-]*", query)
        subject = menu[0] if dependent and menu else (words[-1] if words else "current request")
        return json.dumps({"resolved_query": query, "subject": subject, "topic": subject, "relation": "continue" if dependent and menu else "shift", "referents": [], "confidence": 0.8}), []
    if harness == "comprehension":
        try:
            request = json.loads(latest)
        except json.JSONDecodeError:
            request = {}
        connected = bool(request.get("connected_sources"))
        return json.dumps({"intent": "respond", "deliverable": "answer", "evidence": "connected" if connected else "model", "depth": "grounded", "aperture": "focused", "verification": "grounded" if connected else "deliberation", "answer_needs": ["direct answer"], "requires_grounding": False, "confidence": 0.8}), []
    if harness == "verification":
        return json.dumps({"passed": True, "failure_kind": "", "issues": [], "note": "stub contract check passed"}), []
    if harness == "abstention":
        return "The available sources do not ground that claim. Connect an authorized source or grant an applicable capability.", []
    if harness == "recursive-context":
        return "Bounded evidence summary produced by the stub lane.", []
    return f"stub:{latest}", []


app = FastAPI(title="GRND0 inference gateway", version="0.0.1", docs_url=None, redoc_url=None)


def authorize(authorization: str | None) -> None:
    if authorization != f"Bearer {TOKEN}":
        raise HTTPException(status_code=401, detail="invalid gateway credential")


def public_backends() -> list[dict[str, Any]]:
    values = []
    for backend_id, raw in sorted(CONFIG["backends"].items()):
        if not isinstance(raw, dict):
            continue
        values.append({"id": backend_id, "kind": raw.get("kind"), "enabled": _is_enabled(raw), "configured": bool(_env_or_literal(raw, "base_url"))})
    return values


@app.get("/healthz")
async def healthz() -> dict[str, Any]:
    return {"status": "ok", "mode": "stub" if STUB_MODE else "per-lane", "backends": public_backends()}


@app.post("/v1/chat/completions")
async def chat(payload: ChatRequest, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    authorize(authorization)
    if STUB_MODE:
        content, tool_calls = _stub_reply(payload)
        message: dict[str, Any] = {"role": "assistant", "content": content}
        if tool_calls:
            message["tool_calls"] = tool_calls
        return {
            "id": f"stub_{uuid.uuid4().hex}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": "stub-lane",
            "choices": [{"index": 0, "message": message, "finish_reason": "tool_calls" if tool_calls else "stop"}],
            "grnd0_backend": {"id": "stub", "kind": "stub", "model": "stub-lane"},
        }
    backend_id = lane_backend(payload.grnd0_lane, payload.grnd0_backend) if payload.grnd0_lane else (payload.grnd0_backend or "local-inference")
    backend = resolve_backend(backend_id)
    headers = {"Content-Type": "application/json"}
    if payload.grnd0_harness:
        headers["X-GRND0-Harness"] = payload.grnd0_harness
    if backend.api_key:
        headers["Authorization"] = f"Bearer {backend.api_key}"
    upstream = payload.model_dump(exclude={"grnd0_harness", "grnd0_lane", "grnd0_backend"})
    upstream["model"] = backend.model_override or payload.model
    upstream["stream"] = False
    try:
        async with httpx.AsyncClient(timeout=600.0) as client:
            response = await client.post(f"{backend.base_url}/chat/completions", headers=headers, json=upstream)
        response.raise_for_status()
        body = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=502, detail=f"selected {backend.kind} backend failed") from exc
    if not isinstance(body, dict):
        raise HTTPException(status_code=502, detail="selected backend returned an invalid response")
    resolved_model = str(body.get("model") or upstream["model"])
    body["grnd0_backend"] = {"id": backend.backend_id, "kind": backend.kind, "model": resolved_model}
    return body
