# SPDX-License-Identifier: MPL-2.0
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
import re
from pathlib import Path
from typing import Any

import httpx


class DriveFailure(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise DriveFailure(message)


def receipt(body: dict[str, Any]) -> dict[str, Any]:
    value = body.get("grnd0_receipt")
    if not isinstance(value, dict):
        raise DriveFailure("response lacks a structured receipt")
    return value


def answer(body: dict[str, Any]) -> str:
    try:
        return str(body["choices"][0]["message"].get("content") or "")
    except (KeyError, IndexError, TypeError) as exc:
        raise DriveFailure("response lacks assistant content") from exc


def post_turn(
    client: httpx.Client,
    base_url: str,
    headers: dict[str, str],
    messages: list[dict[str, str]],
) -> dict[str, Any]:
    response = client.post(
        f"{base_url}/v1/chat/completions",
        headers=headers,
        json={"model": "reference-chat", "messages": messages},
    )
    response.raise_for_status()
    return response.json()


def public_copy(value: Any, sensitive_terms: tuple[str, ...], key: str = "") -> Any:
    if key in {"model", "requested_model", "resolved_model"}:
        return "[operator-model]"
    if isinstance(value, dict):
        return {item_key: public_copy(item_value, sensitive_terms, str(item_key)) for item_key, item_value in value.items()}
    if isinstance(value, list):
        return [public_copy(item, sensitive_terms, key) for item in value]
    if isinstance(value, str):
        for term in sensitive_terms:
            value = re.sub(re.escape(term), "[unknown-private-entity]", value, flags=re.IGNORECASE)
        return value
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description="Drive the conversation-grade public contract against a real provider.")
    parser.add_argument("--base-url", default=os.getenv("GRND0_BASE_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--api-key", default=os.getenv("GRND0_API_KEY", ""))
    parser.add_argument("--timeout-seconds", type=float, default=1200.0)
    parser.add_argument("--unknown-entity", required=True, help="A private or otherwise ungrounded entity absent from public self-knowledge.")
    parser.add_argument("--expect-web", action="store_true")
    parser.add_argument("--web-entity", help="A public entity expected to be discoverable through the granted web connector.")
    parser.add_argument("--require-backend-kind", action="append", choices=("local", "cloud"), default=[])
    parser.add_argument("--require-backend-id", action="append", default=[])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    require(bool(args.api_key), "an endpoint API key is required")
    require(args.unknown_entity.casefold() != "grnd0", "the unknown entity must differ from the public self subject")
    if args.expect_web:
        require(bool(args.web_entity), "a public web entity is required for the web-granted drive")

    session_id = f"drive-{uuid.uuid4().hex}"
    headers = {"Authorization": f"Bearer {args.api_key}", "X-GRND0-Session-ID": session_id}
    messages: list[dict[str, str]] = []
    transcript: list[dict[str, Any]] = []
    started = time.time()

    require(args.timeout_seconds >= 300, "the drive timeout must cover cold local model turns")
    with httpx.Client(timeout=args.timeout_seconds) as client:
        capabilities = client.get(f"{args.base_url.rstrip('/')}/api/v1/capabilities", headers=headers)
        capabilities.raise_for_status()
        capability_body = capabilities.json()

        def drive(prompt: str) -> tuple[str, dict[str, Any]]:
            messages.append({"role": "user", "content": prompt})
            body = post_turn(client, args.base_url.rstrip("/"), headers, messages)
            text = answer(body)
            messages.append({"role": "assistant", "content": text})
            turn_receipt = receipt(body)
            transcript.append({"user": prompt, "assistant": text, "receipt": turn_receipt})
            return text, turn_receipt

        self_answer, self_receipt = drive("What is GRND0? Answer from connected public self-knowledge and label the source.")
        self_sources = {item.get("source_id") for item in self_receipt["retrieval"]["hits"]}
        require("grnd0-public" in self_sources, "public self-knowledge did not enter retrieval")
        require(self_receipt["verification"]["status"] == "verified", "public self-knowledge answer was not verified")

        _, binding_receipt = drive("How does it preserve context between turns?")
        require(binding_receipt["comprehension"]["relation"] in {"continue", "return"}, "dependent subject was not bound to prior discourse")
        require(binding_receipt["discourse"]["prior_turn"] == 1, "second turn did not read the first committed turn")

        focused_answer, focused_receipt = drive("Give a focused explanation of its verification gate.")
        require(focused_receipt["plan"]["aperture"] == "focused", "focused aperture was not selected")
        require(focused_receipt["synthesis"]["mode"] == "single", "focused aperture did not remain single-pass")
        focused_branches = re.findall(r"(?m)^\s*[-*]\s+\S", focused_answer)
        require(len(focused_branches) >= 2, "focused answer lacks the branch-offer close")

        report_answer, report_receipt = drive(
            "Produce a comprehensive report comparing GRND0's focused and report apertures in depth. "
            "Cover planning, synthesis shape, verification behavior, and latency tradeoffs."
        )
        require(report_receipt["plan"]["aperture"] == "report", "explicit report aperture was not selected")
        require(report_receipt["synthesis"]["mode"] == "structured", "report did not use structured synthesis")
        require(report_receipt["synthesis"]["planned_sections"] >= 3, "report outline planned fewer than three sections")
        require(report_receipt["synthesis"]["authored_sections"] >= 3, "report authored fewer than three sections")
        report_headings = re.findall(r"(?m)^##\s+\S.*$", report_answer)
        require(len(report_headings) >= 3, "report answer is not visibly multi-section")
        report_route = {call.get("harness") for call in report_receipt.get("route", [])}
        require("synthesis-outline" in report_route, "report receipt lacks the outline call")
        require("synthesis-section" in report_route, "report receipt lacks section-author calls")
        forbidden_review = ("epistemic status", "what evidence would validate", "evidence validation", "internal review")
        require(not any(term in report_answer.casefold() for term in forbidden_review), "report leaked internal-review material")
        unsupported_implementation = ("per-section verification", "verification is applied sequentially")
        require(
            not any(term in report_answer.casefold() for term in unsupported_implementation),
            "report invented a verification stage that is not present in the runtime",
        )
        require(
            re.search(r"\b\d+(?:\s*[-–]\s*\d+)?\s*(?:ms|milliseconds?|seconds?|minutes?)\b", report_answer.casefold()) is None,
            "report invented a quantitative latency claim not present in the working set",
        )
        require(len(report_answer) > len(focused_answer), "report aperture did not expand the answer")

        evidence_entity = args.web_entity if args.expect_web else args.unknown_entity
        web_instruction = " Search the web and retain web provenance." if args.expect_web else ""
        unknown_prompt = f"What is {evidence_entity}? Use only connected evidence and abstain if none supports the answer.{web_instruction}"
        unknown_answer, unknown_receipt = drive(unknown_prompt)
        if args.expect_web:
            web_sources = {item.get("source_id") for item in unknown_receipt["retrieval"]["hits"]}
            require(capability_body.get("web_granted") is True, "web expectation lacks a runtime grant")
            require("operator-web" in web_sources, "web grant produced no web-grounded evidence")
            require(
                unknown_receipt["verification"]["status"] in {"verified", "unverified"},
                "web-grounded answer was replaced by an abstention",
            )
            require(bool(unknown_answer.strip()), "web-grounded answer contained no response")
        else:
            require(capability_body.get("web_granted") is False, "no-web drive requires the web grant to be off")
            require(unknown_receipt["verification"]["status"] == "abstained", "ungrounded private entity did not produce typed abstention")
            require(bool(unknown_answer.strip()), "typed abstention contained no explanation")

        _, return_receipt = drive("Return to GRND0: what does its last-turn receipt expose?")
        require(return_receipt["comprehension"]["relation"] == "return", "explicit topic return was not resolved")
        require(return_receipt["comprehension"]["subject"].casefold() == "grnd0", "topic return bound the wrong subject")

        recap_answer, recap_receipt = drive("Recap the conversation by topic and preserve the order of the main shifts.")
        require(recap_receipt["discourse"]["prior_turn"] == 6, "recap did not read all prior committed turns")
        require(len(recap_answer) >= 80, "recap is not conversation-grade")

        state_response = client.get(
            f"{args.base_url.rstrip('/')}/api/v1/health/discourse-state",
            headers=headers,
            params={"session_id": session_id},
        )
        state_response.raise_for_status()
        state = state_response.json()
        require(state.get("current_turn") == 7, "conversation spine does not contain seven committed turns")
        require(all(item["receipt"]["discourse"]["commit_count"] == 1 for item in transcript), "a turn reported more than one discourse commit")

        backend_kinds = {
            str(call.get("backend_kind"))
            for item in transcript
            for call in item["receipt"].get("route", [])
        }
        backend_ids = {
            str(call.get("backend"))
            for item in transcript
            for call in item["receipt"].get("route", [])
        }
        for expected_kind in args.require_backend_kind:
            require(expected_kind in backend_kinds, f"no receipt route used the required {expected_kind} backend")
        for expected_id in args.require_backend_id:
            require(expected_id in backend_ids, f"no receipt route used the required {expected_id} backend")
        if args.require_backend_kind == ["local"]:
            require(backend_kinds == {"local"}, "local-only drive crossed a non-local backend")

    result = {
        "schema": "grnd0.drive-showcase.v1",
        "status": "green",
        "provider_mode": "mixed" if {"local", "cloud"}.issubset(backend_kinds) else "local-only" if backend_kinds == {"local"} else "real",
        "session_id": session_id,
        "duration_ms": round((time.time() - started) * 1000),
        "checks": [
            "public_self_knowledge",
            "dependent_subject_binding",
            "focused_aperture",
            "focused_branch_offer",
            "structured_report_aperture",
            "grounding_abstention" if not args.expect_web else "web_grounding",
            "explicit_topic_return",
            "ordered_recap",
            "single_state_commit",
            *[f"backend_{kind}" for kind in args.require_backend_kind],
            *[f"backend_id_{backend_id}" for backend_id in args.require_backend_id],
        ],
        "transcript": public_copy(transcript, (args.unknown_entity,)),
    }
    if args.output:
        args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "transcript"}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (DriveFailure, httpx.HTTPError) as exc:
        print(f"drive failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
