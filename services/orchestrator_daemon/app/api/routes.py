# SPDX-License-Identifier: MPL-2.0
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from app.config import Settings
from app.connectors.registry import ConnectorRegistry
from app.cognitive_loop.loop import CognitiveLoop
from app.store import RuntimeStore


class Message(BaseModel):
    model_config = ConfigDict(extra="allow")
    role: str
    content: Any = ""


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    model: str = "reference-chat"
    messages: list[Message]
    stream: bool = False
    harness: str = "reference-chat"
    tools: list[dict[str, Any]] | None = None
    tool_choice: Any = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AnthropicRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    model: str = "reference-chat"
    messages: list[Message]
    max_tokens: int = Field(default=1024, gt=0)
    stream: bool = False
    system: Any = ""
    tools: list[dict[str, Any]] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class IngestRequest(BaseModel):
    source_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{1,63}$")
    root: str


def _session(value: str | None, metadata: dict[str, Any]) -> str | None:
    candidate = value or str(metadata.get("session_id") or "")
    if not candidate:
        return None
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", candidate):
        raise HTTPException(status_code=400, detail="invalid session identifier")
    return candidate


def _anthropic_tools(items: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
    if not items:
        return None
    return [
        {
            "type": "function",
            "function": {
                "name": item.get("name"),
                "description": item.get("description", ""),
                "parameters": item.get("input_schema", {"type": "object", "properties": {}}),
            },
        }
        for item in items
    ]


def create_router(
    settings: Settings,
    loop: CognitiveLoop,
    store: RuntimeStore,
    connectors: ConnectorRegistry,
) -> APIRouter:
    router = APIRouter()

    def authorize(
        authorization: str | None = Header(default=None),
        x_api_key: str | None = Header(default=None),
    ) -> None:
        if not settings.auth_required:
            return
        token = authorization.removeprefix("Bearer ") if authorization else x_api_key
        if token != settings.api_key:
            raise HTTPException(status_code=401, detail="invalid API credential")

    @router.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @router.get("/v1/models", dependencies=[Depends(authorize)])
    async def models() -> dict[str, Any]:
        return {"object": "list", "data": [{"id": "reference-chat", "object": "model", "owned_by": "grnd0-local"}]}

    @router.post("/v1/chat/completions", dependencies=[Depends(authorize)])
    async def chat(payload: ChatRequest, x_grnd0_session_id: str | None = Header(default=None)) -> Any:
        result = await loop.run(
            [item.model_dump() for item in payload.messages],
            payload.model,
            payload.harness,
            session_id=_session(x_grnd0_session_id, payload.metadata),
            tools=payload.tools,
            tool_choice=payload.tool_choice,
        )
        created = int(time.time())
        message: dict[str, Any] = {"role": "assistant", "content": result.content}
        finish_reason = "stop"
        if result.tool_calls:
            message["tool_calls"] = list(result.tool_calls)
            finish_reason = "tool_calls"
        body = {
            "id": result.turn_id,
            "object": "chat.completion",
            "created": created,
            "model": result.model,
            "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
            "grnd0_receipt": result.receipt,
        }
        if not payload.stream:
            return body

        async def events():
            chunk = {
                "id": result.turn_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": result.model,
                "choices": [{"index": 0, "delta": message, "finish_reason": finish_reason}],
            }
            yield f"data: {json.dumps(chunk, separators=(',', ':'))}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(events(), media_type="text/event-stream")

    @router.post("/v1/messages", dependencies=[Depends(authorize)])
    async def anthropic(payload: AnthropicRequest, x_grnd0_session_id: str | None = Header(default=None)) -> dict[str, Any]:
        messages = [item.model_dump() for item in payload.messages]
        if payload.system:
            messages.insert(0, {"role": "system", "content": payload.system})
        result = await loop.run(
            messages,
            payload.model,
            "reference-chat",
            session_id=_session(x_grnd0_session_id, payload.metadata),
            tools=_anthropic_tools(payload.tools),
        )
        content: list[dict[str, Any]] = []
        if result.content:
            content.append({"type": "text", "text": result.content})
        for call in result.tool_calls:
            function = call.get("function", {})
            try:
                arguments = json.loads(function.get("arguments") or "{}")
            except json.JSONDecodeError:
                arguments = {}
            content.append({"type": "tool_use", "id": call.get("id"), "name": function.get("name"), "input": arguments})
        return {
            "id": result.turn_id,
            "type": "message",
            "role": "assistant",
            "model": result.model,
            "content": content,
            "stop_reason": "tool_use" if result.tool_calls else "end_turn",
            "usage": {"input_tokens": 0, "output_tokens": 0},
            "grnd0_receipt": result.receipt,
        }

    @router.get("/api/v1/health/discourse-state", dependencies=[Depends(authorize)])
    async def discourse_state(session_id: str) -> dict[str, Any]:
        return (await store.discourse(session_id)).to_dict()

    @router.get("/api/v1/health/last-turn", dependencies=[Depends(authorize)])
    async def last_turn(session_id: str | None = None) -> dict[str, Any]:
        receipt = await store.last_turn(session_id)
        if receipt is None:
            raise HTTPException(status_code=404, detail="no completed turn")
        return receipt

    @router.get("/health/lanes", dependencies=[Depends(authorize)])
    @router.get("/api/v1/health/lanes", dependencies=[Depends(authorize)])
    async def lane_status() -> dict[str, Any]:
        return {"schema": "grnd0.lanes.health.v1", "lanes": loop._router.public_inventory()}

    @router.get("/api/v1/capabilities", dependencies=[Depends(authorize)])
    async def capability_status() -> dict[str, Any]:
        return {
            "sources": connectors.status(),
            "web_granted": settings.allow_web,
            "git_granted": settings.allow_git,
            "authorized_root_count": len(settings.authorized_read_roots),
            "external_tools": "client-controlled",
        }

    @router.post("/api/v1/knowledge/ingest", dependencies=[Depends(authorize)])
    async def ingest(payload: IngestRequest) -> dict[str, Any]:
        try:
            return await store.ingest_root(payload.source_id, Path(payload.root))
        except ValueError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

    if settings.debug_routes:
        @router.get("/debug/config", dependencies=[Depends(authorize)])
        async def debug_config() -> dict[str, Any]:
            return {
                "harnesses": loop._registry.names(),
                "lanes": loop._router.public_inventory(),
                "connectors": connectors.status(),
                "auth_required": settings.auth_required,
            }

    return router
