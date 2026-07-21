# SPDX-License-Identifier: MPL-2.0
from __future__ import annotations

import json
import re
from typing import Any, TypeVar

from app.cognitive_loop.discourse import DiscourseState, subject_menu
from app.cognitive_loop.provider import ProviderClient, parse_json_object
from app.cognitive_loop.types import (
    Aperture,
    CompositionPlan,
    Comprehension,
    Deliverable,
    EvidencePlan,
    ModelCall,
    Resolution,
    ThinkingDepth,
    VerificationFrame,
)
from app.harness_registry import HarnessRegistry


EnumValue = TypeVar("EnumValue")


def _enum(enum_type: type[EnumValue], value: Any, fallback: EnumValue) -> EnumValue:
    try:
        return enum_type(str(value))
    except (ValueError, TypeError):
        return fallback


def _confidence(value: Any, fallback: float = 0.0) -> float:
    try:
        return max(0.0, min(float(value), 1.0))
    except (TypeError, ValueError):
        return fallback


def _explicit_subject(query: str) -> str:
    match = re.search(
        r"\bwhat\s+is\s+(?:the\s+)?([A-Za-z0-9][A-Za-z0-9_.-]*(?:\s+[A-Za-z0-9][A-Za-z0-9_.-]*){0,5})(?:\?|$)",
        query,
        re.IGNORECASE,
    )
    if match:
        return match.group(1)
    tokens = re.findall(r"[A-Za-z0-9][A-Za-z0-9_.-]*", query)
    return " ".join(tokens[:8]) or "current request"


class ComprehensionPass:
    def __init__(self, registry: HarnessRegistry, provider: ProviderClient) -> None:
        self._registry = registry
        self._provider = provider

    async def resolve(
        self,
        query: str,
        state: DiscourseState,
        calls: list[ModelCall],
    ) -> Resolution:
        menu = subject_menu(state)
        prompt = json.dumps(
            {
                "current_message": query,
                "active_subject": state.active_subject or None,
                "allowed_referents": list(menu),
                "instruction": "Resolve references only to an allowed referent. Preserve exact numeric values.",
            },
            sort_keys=True,
        )
        reply = await self._provider.call(
            self._registry.require("subject-resolution"), prompt, effort=0, calls=calls, max_tokens=600
        )
        raw = parse_json_object(reply.content) or {}
        selected = str(raw.get("subject") or raw.get("topic") or "unresolved").strip()
        allowed = {item.casefold(): item for item in menu}
        topic = str(raw.get("topic") or "").strip()
        resolved_query = str(raw.get("resolved_query") or query).strip()
        relation = str(raw.get("relation") or "shift").strip().casefold()
        if relation not in {"continue", "return", "shift", "meta"}:
            relation = "shift"
        return_match = re.search(r"\breturn\s+to\s+([A-Za-z0-9_.-]+)", query, re.IGNORECASE)
        if return_match and return_match.group(1).casefold() in allowed:
            relation = "return"
            subject = allowed[return_match.group(1).casefold()]
            resolved_query = re.sub(r"\bits\b", f"{subject}'s", query, flags=re.IGNORECASE)
        elif re.search(r"\b(recap|summari[sz]e\s+(?:this|the)\s+conversation)\b", query, re.IGNORECASE):
            relation = "meta"
            subject = "conversation"
            resolved_query = query
        elif relation in {"shift", "meta"}:
            resolved_query = query
            subject = _explicit_subject(query)
        else:
            subject = selected or _explicit_subject(query)
        if selected.casefold() == "unresolved" and relation == "shift":
            selected = topic if topic and topic.casefold() != "unresolved" else _explicit_subject(query)
            subject = selected
        referents: dict[str, str] = {}
        for item in raw.get("referents", []):
            if not isinstance(item, dict):
                continue
            value = str(item.get("entity") or "")
            if value.casefold() in allowed:
                referents[str(item.get("surface") or value)] = allowed[value.casefold()]
        return Resolution(
            resolved_query=resolved_query,
            subject=subject,
            topic=topic or subject,
            relation=relation,
            referents=referents,
            confidence=_confidence(raw.get("confidence")),
        )

    async def compose(
        self,
        query: str,
        resolution: Resolution,
        state: DiscourseState,
        connected_sources: tuple[str, ...],
        calls: list[ModelCall],
    ) -> Comprehension:
        prompt = json.dumps(
            {
                "query": query,
                "resolved_query": resolution.resolved_query,
                "resolved_subject": resolution.subject,
                "topic": resolution.topic,
                "relation": resolution.relation,
                "prior_turn_count": state.current_turn,
                "connected_sources": list(connected_sources),
            },
            sort_keys=True,
        )
        reply = await self._provider.call(
            self._registry.require("comprehension"), prompt, effort=0, calls=calls, max_tokens=800
        )
        raw = parse_json_object(reply.content) or {}
        plan_raw = raw.get("plan") if isinstance(raw.get("plan"), dict) else raw
        normalized_query = query.casefold()
        explicit_connected = bool(
            connected_sources
            and (
                "grnd0" in normalized_query
                or "connected evidence" in normalized_query
                or "connected source" in normalized_query
                or "grounded in" in normalized_query
            )
        )
        recap = bool(re.search(r"\b(recap|summari[sz]e\s+(?:this|the)\s+conversation)\b", normalized_query))
        evidence = _enum(EvidencePlan, plan_raw.get("evidence"), EvidencePlan.MODEL)
        if explicit_connected:
            evidence = EvidencePlan.CONNECTED
        elif recap:
            evidence = EvidencePlan.SESSION
        requires_grounding = bool(raw.get("requires_grounding", evidence == EvidencePlan.CONNECTED)) or explicit_connected
        aperture = _enum(Aperture, plan_raw.get("aperture"), Aperture.FOCUSED)
        if re.search(r"\b(comprehensive report|full report|deep report)\b", normalized_query):
            aperture = Aperture.REPORT
        elif re.search(r"\bfocused\b", normalized_query):
            aperture = Aperture.FOCUSED
        plan = CompositionPlan(
            deliverable=_enum(Deliverable, plan_raw.get("deliverable"), Deliverable.ANSWER),
            evidence=evidence,
            depth=_enum(ThinkingDepth, plan_raw.get("depth"), ThinkingDepth.GROUNDED),
            aperture=aperture,
            verification=_enum(
                VerificationFrame,
                plan_raw.get("verification"),
                VerificationFrame.GROUNDED if requires_grounding else VerificationFrame.DELIBERATION,
            ),
            answer_needs=tuple(str(item) for item in plan_raw.get("answer_needs", []) if str(item).strip()),
        )
        return Comprehension(
            query=query,
            resolved_query=resolution.resolved_query,
            intent=str(raw.get("intent") or "respond").strip(),
            subject=resolution.subject,
            topic=resolution.topic,
            relation=resolution.relation,
            plan=plan,
            confidence=_confidence(raw.get("confidence"), resolution.confidence),
            requires_grounding=requires_grounding,
        )
