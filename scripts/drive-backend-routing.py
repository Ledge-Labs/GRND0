# SPDX-License-Identifier: MPL-2.0
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any

import httpx


class DriveFailure(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise DriveFailure(message)


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify mixed local and cloud-compatible lane routing.")
    parser.add_argument("--base-url", default=os.getenv("GRND0_BASE_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--api-key", default=os.getenv("GRND0_API_KEY", ""))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    require(bool(args.api_key), "an endpoint API key is required")
    headers = {"Authorization": f"Bearer {args.api_key}", "X-GRND0-Session-ID": "backend-routing-drive"}
    started = time.time()
    with httpx.Client(timeout=600.0) as client:
        lanes_response = client.get(f"{args.base_url.rstrip('/')}/health/lanes", headers=headers)
        lanes_response.raise_for_status()
        lanes = lanes_response.json().get("lanes", [])
        require({item.get("backend_kind") for item in lanes} == {"local", "cloud"}, "lane health does not expose local and cloud backends")
        response = client.post(
            f"{args.base_url.rstrip('/')}/v1/chat/completions",
            headers=headers,
            json={"model": "reference-chat", "messages": [{"role": "user", "content": "State one concise fact about Saturn."}]},
        )
        response.raise_for_status()
        receipt = response.json().get("grnd0_receipt")
        require(isinstance(receipt, dict), "response lacks a receipt")
        route = receipt.get("route", [])
        kinds = {item.get("backend_kind") for item in route}
        require({"local", "cloud"}.issubset(kinds), "one turn did not cross both configured backend kinds")
        require(any(item.get("harness") == "verification" and item.get("backend_kind") == "cloud" for item in route), "verification did not reach the cloud-compatible lane")
        public_route = [
            {
                "harness": item.get("harness"),
                "lane": item.get("lane"),
                "backend": item.get("backend"),
                "backend_kind": item.get("backend_kind"),
                "model": "[configured-model]",
                "duration_ms": item.get("duration_ms"),
            }
            for item in route
        ]
    result: dict[str, Any] = {
        "schema": "grnd0.backend-routing-drive.v1",
        "status": "green",
        "duration_ms": round((time.time() - started) * 1000),
        "checks": ["lane_health_local_and_cloud", "one_turn_mixed_route", "cloud_verification_lane"],
        "route": public_route,
        "fixture_scope": "The cloud-kind backend is a loopback OpenAI-compatible conformance fixture. This proves lane forwarding and receipt attribution, not cloud-model quality.",
    }
    if args.output:
        args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (DriveFailure, httpx.HTTPError) as exc:
        print(f"drive failed: {exc}")
        raise SystemExit(1) from exc
