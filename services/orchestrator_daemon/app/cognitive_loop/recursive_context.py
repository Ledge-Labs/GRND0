# SPDX-License-Identifier: MPL-2.0
from __future__ import annotations

import hashlib
import json

from app.cognitive_loop.provider import ProviderClient
from app.cognitive_loop.types import Comprehension, ModelCall, RetrievalBundle, RetrievalHit
from app.harness_registry import HarnessRegistry


async def condense_retrieval(
    bundle: RetrievalBundle,
    comprehension: Comprehension,
    registry: HarnessRegistry,
    provider: ProviderClient,
    calls: list[ModelCall],
    *,
    threshold_chars: int,
) -> RetrievalBundle:
    rendered = bundle.render(max_chars=threshold_chars * 8)
    if len(rendered) <= threshold_chars:
        return bundle
    chunks = [rendered[index : index + 8000] for index in range(0, min(len(rendered), 48000), 8000)]
    summaries: list[RetrievalHit] = []
    harness = registry.require("recursive-context")
    for index, chunk in enumerate(chunks, 1):
        prompt = json.dumps(
            {"query": comprehension.resolved_query, "chunk": chunk, "instruction": "Retain only relevant supported facts and source labels."},
            sort_keys=True,
        )
        reply = await provider.call(harness, prompt, effort=comprehension.plan.effort, calls=calls, max_tokens=1000)
        text = reply.content.strip()
        if text:
            summaries.append(
                RetrievalHit(
                    source_id="recursive-context",
                    locator=f"derived-chunk-{index}",
                    text=text,
                    score=1.0,
                    content_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                )
            )
    return RetrievalBundle(
        mode=f"{bundle.mode}_condensed",
        hits=tuple((*summaries, *bundle.hits)) if summaries else bundle.hits,
        connected_sources=bundle.connected_sources,
        notes=(*bundle.notes, "recursive_context_applied"),
    )
