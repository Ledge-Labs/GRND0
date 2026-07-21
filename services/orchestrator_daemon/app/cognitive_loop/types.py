# SPDX-License-Identifier: MPL-2.0
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class Deliverable(str, Enum):
    ANSWER = "answer"
    ANALYSIS = "analysis"
    STRATEGY = "strategy"
    ARTIFACT = "artifact"
    QUESTION = "question"
    ACT = "act"


class EvidencePlan(str, Enum):
    SESSION = "session"
    CONNECTED = "connected"
    MODEL = "model"
    NONE = "none"


class ThinkingDepth(str, Enum):
    REFLEXIVE = "reflexive"
    GROUNDED = "grounded"
    DELIBERATE = "deliberate"
    DEEP = "deep"


class Aperture(str, Enum):
    FOCUSED = "focused"
    EXTENDED = "extended"
    REPORT = "report"


class VerificationFrame(str, Enum):
    GROUNDED = "grounded"
    DELIBERATION = "deliberation"
    DERIVABLE = "derivable"
    NONE = "none"


class VerificationStatus(str, Enum):
    VERIFIED = "verified"
    UNVERIFIED = "unverified"
    ABSTAINED = "abstained"
    TOOL_CALL = "tool_call_requested"


@dataclass(frozen=True)
class CompositionPlan:
    deliverable: Deliverable
    evidence: EvidencePlan
    depth: ThinkingDepth
    aperture: Aperture
    verification: VerificationFrame
    answer_needs: tuple[str, ...] = ()

    @property
    def effort(self) -> int:
        return {
            ThinkingDepth.REFLEXIVE: 0,
            ThinkingDepth.GROUNDED: 1,
            ThinkingDepth.DELIBERATE: 2,
            ThinkingDepth.DEEP: 3,
        }[self.depth]

    def to_dict(self) -> dict[str, Any]:
        return {
            "deliverable": self.deliverable.value,
            "evidence": self.evidence.value,
            "depth": self.depth.value,
            "aperture": self.aperture.value,
            "verification": self.verification.value,
            "answer_needs": list(self.answer_needs),
            "effort": self.effort,
        }


@dataclass(frozen=True)
class Resolution:
    resolved_query: str
    subject: str
    topic: str
    relation: str
    referents: dict[str, str] = field(default_factory=dict)
    confidence: float = 0.0


@dataclass(frozen=True)
class Comprehension:
    query: str
    resolved_query: str
    intent: str
    subject: str
    topic: str
    relation: str
    plan: CompositionPlan
    confidence: float
    requires_grounding: bool = False


@dataclass(frozen=True)
class RetrievalHit:
    source_id: str
    locator: str
    text: str
    score: float
    content_sha256: str

    def to_dict(self, *, include_text: bool = False) -> dict[str, Any]:
        value = {
            "source_id": self.source_id,
            "locator": self.locator,
            "score": round(self.score, 6),
            "content_sha256": self.content_sha256,
        }
        if include_text:
            value["text"] = self.text
        return value


@dataclass(frozen=True)
class RetrievalBundle:
    mode: str
    hits: tuple[RetrievalHit, ...] = ()
    connected_sources: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    def render(self, *, max_chars: int = 12000) -> str:
        remaining = max_chars
        blocks: list[str] = []
        for index, hit in enumerate(self.hits, 1):
            block = f"[source {index}: {hit.source_id} | {hit.locator}]\n{hit.text}".strip()
            if len(block) > remaining:
                block = block[:remaining]
            if block:
                blocks.append(block)
                remaining -= len(block)
            if remaining <= 0:
                break
        return "\n\n".join(blocks)


@dataclass(frozen=True)
class ModelCall:
    harness: str
    lane: str
    model: str
    backend: str
    backend_kind: str
    duration_ms: int


@dataclass(frozen=True)
class ModelReply:
    content: str
    model: str
    tool_calls: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class VerificationResult:
    status: VerificationStatus
    passed: bool
    failure_kind: str = ""
    note: str = ""
    issues: tuple[str, ...] = ()
    gate: str = "model"

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["status"] = self.status.value
        value["issues"] = list(self.issues)
        return value


@dataclass(frozen=True)
class LoopResult:
    turn_id: str
    session_id: str
    model: str
    content: str
    receipt: dict[str, Any]
    tool_calls: tuple[dict[str, Any], ...] = ()
