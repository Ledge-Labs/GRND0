# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from typing import Any

import httpx


class Client:
    def __init__(self, base_url: str, api_key: str, timeout: float = 300.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout

    def chat(self, messages: list[dict[str, str]], model: str = "reference-chat") -> dict[str, Any]:
        response = httpx.post(
            f"{self._base_url}/v1/chat/completions",
            headers={"Authorization": f"Bearer {self._api_key}"},
            json={"model": model, "messages": messages},
            timeout=self._timeout,
        )
        response.raise_for_status()
        return response.json()
