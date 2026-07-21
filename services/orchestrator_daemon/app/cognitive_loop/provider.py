# SPDX-License-Identifier: MPL-2.0
from __future__ import annotations

import json
import time
from typing import Any

import httpx

from app.harness_registry import Harness
from app.cognitive_loop.routing import LaneRouter
from app.cognitive_loop.types import ModelCall, ModelReply


def parse_json_object(text: str) -> dict[str, Any] | None:
    body = (text or "").strip()
    if body.startswith("```"):
        body = body.split("\n", 1)[-1]
        if body.rstrip().endswith("```"):
            body = body.rstrip()[:-3].rstrip()
    for candidate in (body, body[body.find("{") : body.rfind("}") + 1]):
        if not candidate:
            continue
        try:
            value = json.loads(candidate)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(value, dict):
            return value
    return None


class ProviderClient:
    def __init__(self, gateway_url: str, gateway_token: str, router: LaneRouter) -> None:
        self._gateway_url = gateway_url.rstrip("/")
        self._gateway_token = gateway_token
        self._router = router

    async def call(
        self,
        harness: Harness,
        prompt: str,
        *,
        effort: int,
        calls: list[ModelCall],
        messages: list[dict[str, Any]] | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: Any = None,
        max_tokens: int = 2048,
    ) -> ModelReply:
        lane = self._router.select(harness, effort)
        system = harness.system_prompt
        if harness.response_schema:
            system += "\n\nResponse contract:\n" + json.dumps(
                harness.response_schema, sort_keys=True, separators=(",", ":")
            )
        payload_messages = messages or [{"role": "user", "content": prompt}]
        payload = {
            "model": lane.model or "reference-chat",
            "messages": [{"role": "system", "content": system}, *payload_messages],
            "stream": False,
            "max_tokens": max_tokens,
            "temperature": 0.0 if harness.response_schema else 0.35,
            "grnd0_harness": harness.name,
            "grnd0_lane": lane.name,
            "grnd0_backend": lane.backend,
        }
        if tools:
            payload["tools"] = tools
            if tool_choice is not None:
                payload["tool_choice"] = tool_choice
        started = time.monotonic()
        async with httpx.AsyncClient(timeout=300.0) as client:
            response = await client.post(
                f"{self._gateway_url}/v1/chat/completions",
                headers={"Authorization": f"Bearer {self._gateway_token}"},
                json=payload,
            )
        response.raise_for_status()
        body = response.json()
        message = body["choices"][0]["message"]
        resolved_model = str(body.get("model") or lane.model or lane.name)
        backend = body.get("grnd0_backend") if isinstance(body.get("grnd0_backend"), dict) else {}
        calls.append(
            ModelCall(
                harness=harness.name,
                lane=lane.name,
                model=resolved_model,
                backend=str(backend.get("id") or lane.backend),
                backend_kind=str(backend.get("kind") or lane.backend_kind),
                duration_ms=round((time.monotonic() - started) * 1000),
            )
        )
        raw_tool_calls = message.get("tool_calls") or []
        tool_calls = tuple(item for item in raw_tool_calls if isinstance(item, dict))
        return ModelReply(
            content=str(message.get("content") or ""),
            model=resolved_model,
            tool_calls=tool_calls,
        )
