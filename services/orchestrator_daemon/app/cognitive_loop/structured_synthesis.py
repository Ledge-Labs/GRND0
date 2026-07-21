# SPDX-License-Identifier: MPL-2.0
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from app.cognitive_loop.provider import ProviderClient, parse_json_object
from app.cognitive_loop.types import Aperture, Comprehension, ModelCall, ModelReply, ThinkingDepth
from app.harness_registry import HarnessRegistry


logger = logging.getLogger("grnd0.cognitive_loop.structured_synthesis")

_MIN_SECTIONS = 3
_MAX_SECTIONS = 4
_ALLOWED_KINDS = frozenset(
    {"position", "context", "comparison", "mechanism", "implications", "options", "recommendation"}
)
_INTERNAL_REVIEW_TERMS = (
    "epistemic status",
    "what evidence would validate",
    "evidence validation",
    "internal review",
    "verification plan",
    "confidence score",
)


@dataclass(frozen=True)
class StructuredSynthesisResult:
    reply: ModelReply | None
    planned_sections: int = 0
    authored_sections: int = 0
    fallback_reason: str = ""


def should_use_structured_synthesis(comprehension: Comprehension) -> bool:
    """Select the multi-call path only when the answer contract warrants it."""
    plan = comprehension.plan
    if plan.aperture == Aperture.REPORT:
        return True
    return plan.aperture == Aperture.EXTENDED and (
        plan.depth in {ThinkingDepth.DELIBERATE, ThinkingDepth.DEEP}
        or len(plan.answer_needs) >= 3
    )


def _contains_internal_review(value: str) -> bool:
    normalized = re.sub(r"[\s_-]+", " ", value.casefold())
    return any(term in normalized for term in _INTERNAL_REVIEW_TERMS)


def _validate_outline(value: Any, aperture: Aperture) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    thesis = str(value.get("thesis") or "").strip()
    raw_sections = value.get("sections")
    if not thesis or _contains_internal_review(thesis) or not isinstance(raw_sections, list):
        return None

    limit = 4 if aperture == Aperture.EXTENDED else _MAX_SECTIONS
    sections: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw_sections[:limit]:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()[:120]
        covers = str(item.get("covers") or "").strip()[:500]
        if not title or not covers or _contains_internal_review(f"{title} {covers}"):
            continue
        key = title.casefold()
        if key in seen:
            continue
        seen.add(key)
        kind = str(item.get("kind") or "context").strip().casefold()
        sections.append(
            {
                "title": title,
                "covers": covers,
                "kind": kind if kind in _ALLOWED_KINDS else "context",
                "wants_table": bool(item.get("wants_table")),
            }
        )
    if len(sections) < _MIN_SECTIONS:
        return None
    return {"thesis": thesis[:700], "sections": sections}


def _outline_overview(outline: dict[str, Any]) -> str:
    lines = [f"Thesis: {outline['thesis']}", "Sections, in order:"]
    for index, section in enumerate(outline["sections"], 1):
        table = "; include a comparison table" if section["wants_table"] else ""
        lines.append(f"{index}. {section['title']} - {section['covers']}{table}")
    return "\n".join(lines)


def _section_body(text: str) -> str:
    body = text.strip()
    lines = body.splitlines()
    if lines and re.match(r"^#{1,6}\s+", lines[0].strip()):
        body = "\n".join(lines[1:]).strip()
    return body


async def run_structured_synthesis(
    *,
    working_set: dict[str, Any],
    comprehension: Comprehension,
    registry: HarnessRegistry,
    provider: ProviderClient,
    calls: list[ModelCall],
) -> StructuredSynthesisResult:
    """Author an outline and sections over one immutable working-set prefix.

    Failure is a normal degradation signal. The caller retains responsibility
    for the existing single-call synthesis path.
    """
    canonical_prefix = "Bounded working set:\n" + json.dumps(
        working_set, sort_keys=True, separators=(",", ":")
    )
    outline_harness = registry.require("synthesis-outline")
    section_harness = registry.require("synthesis-section")
    outline_prompt = (
        "Plan the visible final answer. Return only the contracted JSON. "
        f"The selected aperture is {comprehension.plan.aperture.value}."
    )
    try:
        outline_reply = await provider.call(
            outline_harness,
            comprehension.resolved_query,
            effort=comprehension.plan.effort,
            calls=calls,
            messages=[
                {"role": "user", "content": canonical_prefix},
                {"role": "user", "content": outline_prompt},
            ],
            max_tokens=1000,
        )
    except Exception as exc:
        logger.warning("structured outline failed: %s", type(exc).__name__)
        return StructuredSynthesisResult(None, fallback_reason="outline_call_failed")

    outline = _validate_outline(
        parse_json_object(outline_reply.content), comprehension.plan.aperture
    )
    if outline is None:
        return StructuredSynthesisResult(None, fallback_reason="outline_contract_failed")

    overview = _outline_overview(outline)
    authored: list[tuple[dict[str, Any], str, str]] = []
    for index, section in enumerate(outline["sections"]):
        prior_title = outline["sections"][index - 1]["title"] if index else "none"
        next_title = (
            outline["sections"][index + 1]["title"]
            if index + 1 < len(outline["sections"])
            else "none"
        )
        assignment = {
            "answer_outline": overview,
            "assigned_section": section,
            "prior_section": prior_title,
            "next_section": next_title,
            "instruction": (
                "Write only the assigned section body. Do not repeat its heading, the thesis, "
                "or neighboring sections. Never add internal-review, evidence-validation, "
                "epistemic-status, confidence-score, or process-narration material. Omit any "
                "implementation behavior, timing, number, or integration not explicitly supported "
                "by the bounded working set."
            ),
        }
        try:
            reply = await provider.call(
                section_harness,
                comprehension.resolved_query,
                effort=comprehension.plan.effort,
                calls=calls,
                messages=[
                    {"role": "user", "content": canonical_prefix},
                    {"role": "user", "content": json.dumps(assignment, sort_keys=True)},
                ],
                max_tokens=1400 if comprehension.plan.aperture == Aperture.REPORT else 1000,
            )
        except Exception as exc:
            logger.warning("structured section failed: %s", type(exc).__name__)
            continue
        body = _section_body(reply.content)
        if body and not _contains_internal_review(body):
            authored.append((section, body, reply.model))

    if len(authored) < _MIN_SECTIONS:
        return StructuredSynthesisResult(
            None,
            planned_sections=len(outline["sections"]),
            authored_sections=len(authored),
            fallback_reason="insufficient_sections",
        )

    parts = [outline["thesis"]]
    for section, body, _ in authored:
        parts.append(f"## {section['title']}\n\n{body}")
    content = "\n\n".join(parts).strip()
    return StructuredSynthesisResult(
        ModelReply(content=content, model=authored[-1][2]),
        planned_sections=len(outline["sections"]),
        authored_sections=len(authored),
    )
