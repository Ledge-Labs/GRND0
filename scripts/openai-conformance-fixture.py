# SPDX-License-Identifier: MPL-2.0
from __future__ import annotations

import json
import argparse
import time
import uuid
from typing import Any

from fastapi import FastAPI, Header
from pydantic import BaseModel, ConfigDict
import uvicorn


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    model: str
    messages: list[dict[str, Any]]


app = FastAPI(title="OpenAI-compatible routing conformance fixture", docs_url=None, redoc_url=None)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok", "purpose": "routing-conformance-only"}


@app.post("/v1/chat/completions")
async def chat(payload: ChatRequest, x_grnd0_harness: str = Header(default="")) -> dict[str, Any]:
    if x_grnd0_harness == "verification":
        content = json.dumps({"passed": True, "failure_kind": "", "issues": [], "note": "compatible-backend routing fixture"})
    else:
        content = "Compatible backend fixture response."
    return {
        "id": f"fixture_{uuid.uuid4().hex}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": payload.model,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a loopback OpenAI-compatible routing fixture.")
    parser.add_argument("--port", type=int, default=9300)
    args = parser.parse_args()
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
