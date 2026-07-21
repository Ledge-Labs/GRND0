# SPDX-License-Identifier: MPL-2.0
from __future__ import annotations

import asyncio
import html
import ipaddress
import json
import os
import re
import socket
from html.parser import HTMLParser
from urllib.parse import parse_qs, quote, unquote, urlencode, urljoin, urlparse

import httpx
import websockets
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field, HttpUrl


TOKEN = os.getenv("GRND0_CAPABILITY_TOKEN", "").strip()
BROWSER_URL = os.getenv("GRND0_BROWSER_URL", "http://browser_harness:9222").rstrip("/")
if not TOKEN:
    raise RuntimeError("GRND0_CAPABILITY_TOKEN is required")


class FetchRequest(BaseModel):
    url: HttpUrl
    render: bool = False


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=5, ge=1, le=8)


class TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.hidden = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self.hidden += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self.hidden:
            self.hidden -= 1

    def handle_data(self, data: str) -> None:
        if not self.hidden and data.strip():
            self.parts.append(data.strip())


def public_host(host: str) -> bool:
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(host, None)}
    except socket.gaierror:
        return False
    return bool(addresses) and all(ipaddress.ip_address(raw).is_global for raw in addresses)


def validate_url(value: str) -> None:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or not public_host(parsed.hostname):
        raise HTTPException(status_code=400, detail="only public HTTP origins are permitted")


def authorize(authorization: str | None) -> None:
    if authorization != f"Bearer {TOKEN}":
        raise HTTPException(status_code=401, detail="invalid capability credential")


async def bounded_fetch(url: str) -> httpx.Response:
    current = url
    async with httpx.AsyncClient(follow_redirects=False, timeout=20.0) as client:
        for _ in range(6):
            validate_url(current)
            response = await client.get(current, headers={"User-Agent": "GRND0/0.0.1"})
            if response.status_code not in {301, 302, 303, 307, 308}:
                return response
            location = response.headers.get("location")
            if not location:
                return response
            current = urljoin(current, location)
    raise HTTPException(status_code=400, detail="redirect limit exceeded")


async def browser_text(url: str) -> str:
    validate_url(url)
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.put(f"{BROWSER_URL}/json/new?{quote(url, safe=':/?=&%')}")
        response.raise_for_status()
        target = response.json()
    socket_url = str(target["webSocketDebuggerUrl"])
    async with websockets.connect(socket_url, open_timeout=10, close_timeout=3, max_size=4_000_000) as channel:
        await channel.send(json.dumps({"id": 1, "method": "Page.enable"}))
        await channel.send(json.dumps({"id": 2, "method": "Runtime.enable"}))
        await channel.send(json.dumps({"id": 3, "method": "Page.navigate", "params": {"url": url}}))
        for _ in range(80):
            message = json.loads(await asyncio.wait_for(channel.recv(), timeout=1.0))
            if message.get("method") == "Page.loadEventFired":
                break
        await channel.send(json.dumps({"id": 4, "method": "Runtime.evaluate", "params": {"expression": "JSON.stringify({url:location.href,text:document.body?document.body.innerText:''})", "returnByValue": True}}))
        while True:
            message = json.loads(await asyncio.wait_for(channel.recv(), timeout=3.0))
            if message.get("id") == 4:
                value = json.loads(message["result"]["result"].get("value") or "{}")
                validate_url(str(value.get("url") or url))
                return str(value.get("text") or "")[:200000]


def plain_text(raw: str) -> str:
    extractor = TextExtractor()
    extractor.feed(raw)
    return re.sub(r"\s+", " ", html.unescape(" ".join(extractor.parts))).strip()


app = FastAPI(title="GRND0 web research", version="0.0.1", docs_url=None, redoc_url=None)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/search")
async def search(payload: SearchRequest, authorization: str | None = Header(default=None)) -> dict[str, object]:
    authorize(authorization)
    search_url = "https://html.duckduckgo.com/html/?" + urlencode({"q": payload.query})
    response = await bounded_fetch(search_url)
    matches = re.findall(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', response.text, re.IGNORECASE | re.DOTALL)
    results: list[dict[str, object]] = []
    for href, title_raw in matches:
        target = html.unescape(href)
        parsed = urlparse(target)
        if parsed.netloc.endswith("duckduckgo.com"):
            target = unquote(parse_qs(parsed.query).get("uddg", [""])[0])
        try:
            validate_url(target)
        except HTTPException:
            continue
        results.append({"url": target, "title": plain_text(title_raw), "snippet": "", "score": 1.0 / (len(results) + 1)})
        if len(results) >= payload.limit:
            break
    return {"query": payload.query, "results": results}


@app.post("/fetch")
async def fetch(payload: FetchRequest, authorization: str | None = Header(default=None)) -> dict[str, str | int | bool]:
    authorize(authorization)
    url = str(payload.url)
    response = await bounded_fetch(url)
    content_type = response.headers.get("content-type", "")
    if "text/" not in content_type and "application/json" not in content_type:
        raise HTTPException(status_code=415, detail="response is not text")
    rendered = False
    text = response.text if "application/json" in content_type else plain_text(response.text)
    if payload.render:
        try:
            text = await browser_text(str(response.url))
            rendered = True
        except Exception:
            rendered = False
    return {"status": response.status_code, "content_type": content_type, "text": text[:200000], "rendered": rendered}
