# SPDX-License-Identifier: MPL-2.0
from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from dataclasses import replace
from typing import Any

from app.config import Settings
from app.connectors.registry import ConnectorRegistry
from app.cognitive_loop.comprehension import ComprehensionPass
from app.cognitive_loop.discourse import DiscourseUpdate, render_state
from app.cognitive_loop.provider import ProviderClient
from app.cognitive_loop.recursive_context import condense_retrieval
from app.cognitive_loop.routing import LaneRouter
from app.cognitive_loop.structured_synthesis import (
    run_structured_synthesis,
    should_use_structured_synthesis,
)
from app.cognitive_loop.types import (
    EvidencePlan,
    LoopResult,
    ModelCall,
    RetrievalBundle,
    VerificationResult,
    VerificationStatus,
)
from app.cognitive_loop.verification import VerificationGate, label_unverified
from app.harness_registry import HarnessRegistry
from app.store import RuntimeStore


def stable_session_id(messages: list[dict[str, Any]]) -> str:
    seed = ""
    for message in messages:
        if message.get("role") == "user":
            seed = str(message.get("content") or "")
            break
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]
    return f"session_{digest}"


def _latest_user(messages: list[dict[str, Any]]) -> str:
    for message in reversed(messages):
        if message.get("role") == "user":
            content = message.get("content", "")
            if isinstance(content, str):
                return content.strip()
            return json.dumps(content, sort_keys=True)
    raise ValueError("at least one user message is required")


def _client_system(messages: list[dict[str, Any]]) -> str:
    return "\n\n".join(
        str(message.get("content") or "") for message in messages if message.get("role") == "system"
    )


def ensure_focused_branch_close(content: str) -> str:
    """Normalize the focused aperture's visible close without another model call."""
    if len(re.findall(r"(?m)^\s*[-*]\s+\S", content)) >= 2:
        return content
    close = (
        "Possible next directions:\n"
        "- Examine the mechanism through a concrete example.\n"
        "- Compare its behavior under different evidence conditions.\n"
        "- Expand the same question into a structured report."
    )
    return f"{content.rstrip()}\n\n{close}".strip()


class CognitiveLoop:
    def __init__(
        self,
        settings: Settings,
        registry: HarnessRegistry,
        store: RuntimeStore,
        router: LaneRouter,
        connectors: ConnectorRegistry,
    ) -> None:
        self._settings = settings
        self._registry = registry
        self._store = store
        self._router = router
        self._connectors = connectors
        self._provider = ProviderClient(settings.gateway_url, settings.gateway_token, router)
        self._comprehension = ComprehensionPass(registry, self._provider)
        self._verification = VerificationGate(registry, self._provider)

    async def run(
        self,
        messages: list[dict[str, Any]],
        model: str,
        harness_name: str,
        *,
        session_id: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: Any = None,
    ) -> LoopResult:
        harness = self._registry.require(harness_name)
        if harness.role != "synthesis":
            raise ValueError("the public endpoint requires a synthesis harness")
        session_id = session_id or stable_session_id(messages)
        query = _latest_user(messages)
        turn_id = f"turn_{uuid.uuid4().hex}"
        started = time.monotonic()
        calls: list[ModelCall] = []

        spine_before = await self._store.discourse(session_id)
        resolution = await self._comprehension.resolve(query, spine_before, calls)
        comprehension = await self._comprehension.compose(
            query,
            resolution,
            spine_before,
            self._connectors.active_ids(),
            calls,
        )

        retrieval = RetrievalBundle(
            mode="model_knowledge_only",
            connected_sources=self._connectors.active_ids(),
            notes=("retrieval_not_selected",),
        )
        if comprehension.plan.evidence == EvidencePlan.CONNECTED:
            normalized_query = comprehension.resolved_query.casefold()
            source_ids: tuple[str, ...] | None = None
            if "search the web" in normalized_query or "web-grounded" in normalized_query:
                source_ids = ("operator-web",)
            elif comprehension.subject.casefold() == "grnd0":
                source_ids = ("grnd0-public",)
            retrieval = await self._connectors.search(comprehension.resolved_query, source_ids=source_ids)
            retrieval = await condense_retrieval(
                retrieval,
                comprehension,
                self._registry,
                self._provider,
                calls,
                threshold_chars=self._settings.rlm_threshold_chars,
            )

        aperture = comprehension.plan.aperture.value
        answer_contract = {
            "focused": (
                "Give a direct, compact answer. Close with two or three specific branches the "
                "reader may pursue next. Do not introduce report sections."
            ),
            "extended": (
                "Develop the requested dimensions with compact visible structure. Omit internal "
                "review notes, evidence-validation prompts, epistemic-status sections, and process narration."
            ),
            "report": (
                "Cover every requested dimension in a reader-facing report. Omit internal review "
                "notes, evidence-validation prompts, epistemic-status sections, and process narration."
            ),
        }[aperture]
        working_set = {
            "resolved_query": comprehension.resolved_query,
            "subject": comprehension.subject,
            "relation": comprehension.relation,
            "composition_plan": comprehension.plan.to_dict(),
            "conversation_spine": render_state(spine_before),
            "connected_evidence": retrieval.render(),
            "evidence_mode": retrieval.mode,
            "client_system": _client_system(messages),
            "instruction": (
                "Answer the resolved query, preserve source labels, and obey this answer contract: "
                + answer_contract
            ),
        }
        synthesis_messages = [
            {"role": "user", "content": "Bounded working set:\n" + json.dumps(working_set, sort_keys=True)},
            *[message for message in messages if message.get("role") != "system"],
        ]
        synthesis_mode = "single"
        synthesis_detail: dict[str, Any] = {}
        synthesis = None
        if not tools and should_use_structured_synthesis(comprehension):
            structured = await run_structured_synthesis(
                working_set=working_set,
                comprehension=comprehension,
                registry=self._registry,
                provider=self._provider,
                calls=calls,
            )
            synthesis_detail = {
                "planned_sections": structured.planned_sections,
                "authored_sections": structured.authored_sections,
            }
            if structured.reply is not None:
                synthesis = structured.reply
                synthesis_mode = "structured"
            else:
                synthesis_mode = "single_fallback"
                synthesis_detail["fallback_reason"] = structured.fallback_reason
        if synthesis is None:
            synthesis = await self._provider.call(
                harness,
                comprehension.resolved_query,
                effort=comprehension.plan.effort,
                calls=calls,
                messages=synthesis_messages,
                tools=tools,
                tool_choice=tool_choice,
                max_tokens={"focused": 2048, "extended": 4096, "report": 6144}[aperture],
            )
        if not synthesis.content.strip() and not synthesis.tool_calls:
            synthesis = await self._provider.call(
                harness,
                "Return the final answer only. Internal reasoning is omitted.",
                effort=comprehension.plan.effort,
                calls=calls,
                messages=[*synthesis_messages, {"role": "user", "content": "Return the final answer now without internal reasoning."}],
                tools=tools,
                tool_choice=tool_choice,
                max_tokens={"focused": 2048, "extended": 4096, "report": 6144}[aperture],
            )
        if aperture == "focused" and not synthesis.tool_calls:
            synthesis = replace(synthesis, content=ensure_focused_branch_close(synthesis.content))

        if synthesis.tool_calls:
            verification = VerificationResult(
                status=VerificationStatus.TOOL_CALL,
                passed=True,
                note="External tool execution remains with the calling client.",
                gate="structured_tool_call",
            )
            content = synthesis.content
        else:
            verification = await self._verification.judge(
                synthesis.content, comprehension, retrieval, calls
            )
            if verification.status == VerificationStatus.ABSTAINED:
                content = await self._verification.abstention(comprehension, verification, calls)
            elif verification.status == VerificationStatus.UNVERIFIED:
                content = label_unverified(synthesis.content, verification)
            else:
                content = synthesis.content

        summary = content.strip().replace("\n", " ")[:800] or "Structured tool call emitted."
        state_after = await self._store.commit_discourse(
            DiscourseUpdate(
                session_id=session_id,
                turn_id=turn_id,
                query=query,
                subject=comprehension.subject,
                topic=comprehension.topic,
                relation=comprehension.relation,
                answer_summary=summary,
                verification=verification.status.value,
                entities=tuple(resolution.referents.values()),
                sources=tuple(dict.fromkeys(hit.source_id for hit in retrieval.hits)),
            )
        )
        receipt = {
            "schema": "grnd0.receipt.v1",
            "turn_id": turn_id,
            "session_id": session_id,
            "harness": harness.name,
            "harness_contract": harness.contract,
            "requested_model": model,
            "resolved_model": synthesis.model,
            "plan": comprehension.plan.to_dict(),
            "comprehension": {
                "intent": comprehension.intent,
                "resolved_query": comprehension.resolved_query,
                "subject": comprehension.subject,
                "topic": comprehension.topic,
                "relation": comprehension.relation,
                "confidence": comprehension.confidence,
                "requires_grounding": comprehension.requires_grounding,
            },
            "retrieval": {
                "mode": retrieval.mode,
                "connected_sources": list(retrieval.connected_sources),
                "hits": [hit.to_dict() for hit in retrieval.hits],
                "notes": list(retrieval.notes),
            },
            "verification": verification.to_dict(),
            "synthesis": {"mode": synthesis_mode, **synthesis_detail},
            "route": [
                {
                    "harness": call.harness,
                    "lane": call.lane,
                    "backend": call.backend,
                    "backend_kind": call.backend_kind,
                    "model": call.model,
                    "duration_ms": call.duration_ms,
                }
                for call in calls
            ],
            "capabilities": {
                "web_granted": self._settings.allow_web,
                "git_granted": self._settings.allow_git,
                "external_tools_offered": bool(tools),
            },
            "discourse": {"prior_turn": spine_before.current_turn, "committed_turn": state_after.current_turn, "commit_count": 1},
            "duration_ms": round((time.monotonic() - started) * 1000),
        }
        await self._store.write_turn(turn_id, session_id, receipt)
        return LoopResult(
            turn_id=turn_id,
            session_id=session_id,
            model=synthesis.model,
            content=content,
            receipt=receipt,
            tool_calls=synthesis.tool_calls,
        )
