# SPDX-License-Identifier: MPL-2.0
from __future__ import annotations

import json

from app.cognitive_loop.provider import ProviderClient, parse_json_object
from app.cognitive_loop.types import (
    Comprehension,
    ModelCall,
    RetrievalBundle,
    VerificationResult,
    VerificationStatus,
)
from app.harness_registry import HarnessRegistry


class VerificationGate:
    def __init__(self, registry: HarnessRegistry, provider: ProviderClient) -> None:
        self._registry = registry
        self._provider = provider

    async def judge(
        self,
        answer: str,
        comprehension: Comprehension,
        retrieval: RetrievalBundle,
        calls: list[ModelCall],
    ) -> VerificationResult:
        if comprehension.requires_grounding and not retrieval.hits:
            return VerificationResult(
                status=VerificationStatus.ABSTAINED,
                passed=False,
                failure_kind="missing_grounding",
                note="The requested claim lacks connected evidence.",
                gate="deterministic",
            )
        prompt = json.dumps(
            {
                "query": comprehension.resolved_query,
                "answer": answer,
                "verification_frame": comprehension.plan.verification.value,
                "requires_grounding": comprehension.requires_grounding,
                "evidence": [hit.to_dict(include_text=True) for hit in retrieval.hits],
            },
            sort_keys=True,
        )
        try:
            reply = await self._provider.call(
                self._registry.require("verification"), prompt, effort=comprehension.plan.effort, calls=calls
            )
        except Exception as exc:
            return VerificationResult(
                status=VerificationStatus.UNVERIFIED,
                passed=False,
                failure_kind="verifier_unavailable",
                note=f"Verification did not complete ({type(exc).__name__}).",
            )
        raw = parse_json_object(reply.content)
        if not raw:
            return VerificationResult(
                status=VerificationStatus.UNVERIFIED,
                passed=False,
                failure_kind="invalid_verdict",
                note="The verifier returned no typed verdict.",
            )
        passed = bool(raw.get("passed", False))
        status = VerificationStatus.VERIFIED if passed else VerificationStatus.UNVERIFIED
        return VerificationResult(
            status=status,
            passed=passed,
            failure_kind="" if passed else str(raw.get("failure_kind") or "verification_failed"),
            note=str(raw.get("note") or ""),
            issues=tuple(str(item) for item in raw.get("issues", []) if str(item).strip()),
        )

    async def abstention(
        self,
        comprehension: Comprehension,
        result: VerificationResult,
        calls: list[ModelCall],
    ) -> str:
        prompt = json.dumps(
            {
                "query": comprehension.resolved_query,
                "reason": result.failure_kind,
                "note": result.note,
                "connected_evidence_required": comprehension.requires_grounding,
            },
            sort_keys=True,
        )
        try:
            reply = await self._provider.call(
                self._registry.require("abstention"), prompt, effort=0, calls=calls, max_tokens=500
            )
            text = reply.content.strip()
        except Exception:
            text = ""
        return text or "I cannot answer that claim from the evidence currently available to this runtime."


def label_unverified(answer: str, result: VerificationResult) -> str:
    note = result.note or result.failure_kind or "the verification check did not pass"
    return f"{answer.rstrip()}\n\nVerification status: unverified — {note}"
