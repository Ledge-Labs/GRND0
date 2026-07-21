# SPDX-License-Identifier: MPL-2.0
from __future__ import annotations

import json
import hashlib
import io
import re
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.api.routes import create_router
from app.config import Settings
from app.connectors.local_files import LocalFilesSource
from app.cognitive_loop.discourse import DiscourseState, DiscourseUpdate, fold_updates, reduce_state
from app.cognitive_loop.loop import ensure_focused_branch_close
from app.cognitive_loop.routing import LaneRouter
from app.cognitive_loop.structured_synthesis import (
    run_structured_synthesis,
    should_use_structured_synthesis,
)
from app.cognitive_loop.types import (
    Aperture,
    CompositionPlan,
    Comprehension,
    Deliverable,
    EvidencePlan,
    LoopResult,
    ModelReply,
    ThinkingDepth,
    VerificationFrame,
)
from app.harness_registry import HarnessRegistry
from app.store import RuntimeStore
from tools.grnd0_models import generate, pull


ROOT = Path(__file__).parents[1]


def settings(tmp_path: Path, roots: tuple[Path, ...] = ()) -> Settings:
    return Settings(
        api_key="test-key",
        gateway_url="http://gateway",
        gateway_token="gateway-key",
        database_path=tmp_path / "state.sqlite",
        harness_path=ROOT / "data" / "harness_templates",
        lanes_path=ROOT / "configs" / "lanes.example.json",
        sources_path=ROOT / "configs" / "knowledge-sources.example.json",
        auth_required=True,
        debug_routes=False,
        authorized_read_roots=roots,
    )


def update(turn_id: str, subject: str) -> DiscourseUpdate:
    return DiscourseUpdate(
        session_id="session-test",
        turn_id=turn_id,
        query=f"question {turn_id}",
        subject=subject,
        topic=subject,
        relation="shift",
        answer_summary=f"answer {turn_id}",
        verification="verified",
    )


def test_harness_registry_is_minimal_and_named() -> None:
    registry = HarnessRegistry(ROOT / "data" / "harness_templates")
    assert registry.names() == [
        "abstention",
        "comprehension",
        "recursive-context",
        "reference-chat",
        "subject-resolution",
        "synthesis-outline",
        "synthesis-section",
        "verification",
    ]
    assert all(registry.require(name).contract for name in registry.names())


def test_focused_close_is_single_pass_and_idempotent() -> None:
    answer = ensure_focused_branch_close("A compact answer.")
    assert len(re.findall(r"(?m)^\s*[-*]\s+\S", answer)) == 3
    assert ensure_focused_branch_close(answer) == answer


def comprehension(aperture: Aperture, depth: ThinkingDepth = ThinkingDepth.GROUNDED) -> Comprehension:
    return Comprehension(
        query="Compare alpha and beta.",
        resolved_query="Compare alpha and beta.",
        intent="compare",
        subject="alpha and beta",
        topic="comparison",
        relation="shift",
        plan=CompositionPlan(
            deliverable=Deliverable.ANALYSIS,
            evidence=EvidencePlan.MODEL,
            depth=depth,
            aperture=aperture,
            verification=VerificationFrame.DELIBERATION,
            answer_needs=("mechanism", "tradeoffs", "application"),
        ),
        confidence=0.9,
    )


@pytest.mark.asyncio
async def test_structured_synthesis_folds_sections_over_identical_prefix() -> None:
    class FakeProvider:
        def __init__(self) -> None:
            self.section_prefixes: list[str] = []

        async def call(self, harness, prompt, **kwargs):
            messages = kwargs["messages"]
            if harness.name == "synthesis-outline":
                return ModelReply(
                    model="local-model",
                    content=json.dumps(
                        {
                            "thesis": "Alpha and beta optimize different constraints.",
                            "sections": [
                                {"title": "Mechanism", "covers": "How each works", "kind": "mechanism", "wants_table": False},
                                {"title": "Tradeoffs", "covers": "Where each wins", "kind": "comparison", "wants_table": True},
                                {"title": "Application", "covers": "When to choose each", "kind": "recommendation", "wants_table": False},
                            ],
                        }
                    ),
                )
            self.section_prefixes.append(messages[0]["content"])
            assignment = json.loads(messages[1]["content"])
            title = assignment["assigned_section"]["title"]
            return ModelReply(model="local-model", content=f"### {title}\nDetailed {title.lower()} analysis.")

    provider = FakeProvider()
    result = await run_structured_synthesis(
        working_set={"resolved_query": "Compare alpha and beta.", "connected_evidence": ""},
        comprehension=comprehension(Aperture.REPORT, ThinkingDepth.DEEP),
        registry=HarnessRegistry(ROOT / "data" / "harness_templates"),
        provider=provider,
        calls=[],
    )
    assert result.reply is not None
    assert result.planned_sections == result.authored_sections == 3
    assert result.reply.content.count("\n## ") == 3
    assert len(set(provider.section_prefixes)) == 1
    assert result.reply.content.index("## Mechanism") < result.reply.content.index("## Tradeoffs")
    assert "###" not in result.reply.content


@pytest.mark.asyncio
async def test_structured_synthesis_degrades_on_invalid_outline() -> None:
    class InvalidOutlineProvider:
        async def call(self, harness, prompt, **kwargs):
            return ModelReply(model="local-model", content='{"thesis":"thin","sections":[]}')

    result = await run_structured_synthesis(
        working_set={"resolved_query": "Compare alpha and beta."},
        comprehension=comprehension(Aperture.REPORT),
        registry=HarnessRegistry(ROOT / "data" / "harness_templates"),
        provider=InvalidOutlineProvider(),
        calls=[],
    )
    assert result.reply is None
    assert result.fallback_reason == "outline_contract_failed"
    assert should_use_structured_synthesis(comprehension(Aperture.FOCUSED)) is False
    assert should_use_structured_synthesis(comprehension(Aperture.EXTENDED, ThinkingDepth.DEEP)) is True


def test_discourse_reducer_is_idempotent_and_batching_invariant() -> None:
    initial = DiscourseState(session_id="session-test")
    first = update("turn-1", "alpha")
    second = update("turn-2", "beta")
    once = reduce_state(initial, first)
    assert reduce_state(once, first) == once
    sequential = reduce_state(reduce_state(initial, first), second)
    assert fold_updates(initial, (first, second)) == sequential
    assert sequential.current_turn == 2
    assert sequential.active_subject == "beta"
    assert [item.status for item in sequential.topic_stack] == ["active", "background"]


@pytest.mark.asyncio
async def test_local_files_require_grant_and_return_relative_locator(tmp_path: Path) -> None:
    root = tmp_path / "vault"
    root.mkdir()
    (root / "note.md").write_text("Saturn has visible rings.", encoding="utf-8")
    with pytest.raises(RuntimeError):
        LocalFilesSource("denied", root, authorized_roots=(), public_root=tmp_path)
    source = LocalFilesSource("vault", root, authorized_roots=(root.resolve(),), public_root=tmp_path)
    hits = await source.search("Saturn rings")
    assert hits[0].source_id == "vault"
    assert hits[0].locator == "note.md"
    assert str(root) not in hits[0].locator
    absent = await source.search("What is UnpublishedSaffronNode? Use only connected evidence and abstain if none supports the answer.")
    assert absent == ()


@pytest.mark.asyncio
async def test_store_commits_once_and_indexes_granted_content(tmp_path: Path) -> None:
    root = tmp_path / "documents"
    root.mkdir()
    (root / "facts.md").write_text("Orchid records are operator-owned.", encoding="utf-8")
    store = RuntimeStore(tmp_path / "runtime.sqlite", (root.resolve(),))
    state = await store.commit_discourse(update("turn-1", "orchid"))
    repeated = await store.commit_discourse(update("turn-1", "orchid"))
    assert state == repeated
    assert repeated.current_turn == 1
    indexed = await store.ingest_root("operator-docs", root)
    assert indexed["documents"] == 1
    hits = await store.search_knowledge("Orchid operator")
    assert hits[0].locator == "facts.md"
    with pytest.raises(ValueError):
        await store.ingest_root("denied", tmp_path)


@pytest.mark.asyncio
async def test_endpoint_contract_and_health_state(tmp_path: Path) -> None:
    class FakeLoop:
        _registry = HarnessRegistry(ROOT / "data" / "harness_templates")
        _router = LaneRouter(ROOT / "configs" / "lanes.example.json")

        async def run(self, messages, model, harness, **kwargs):
            assert harness == "reference-chat"
            return LoopResult(
                turn_id="turn-test",
                session_id="session-test",
                model="stub-lane",
                content="stub:hello",
                receipt={"schema": "grnd0.receipt.v1", "session_id": "session-test"},
            )

    class FakeConnectors:
        def status(self):
            return [{"id": "public", "kind": "local_files", "available": True}]

    store = RuntimeStore(tmp_path / "state.sqlite", ())
    await store.commit_discourse(update("state-turn", "hello"))
    await store.write_turn("state-turn", "session-test", {"schema": "grnd0.receipt.v1"})
    app = FastAPI()
    app.include_router(create_router(settings(tmp_path), FakeLoop(), store, FakeConnectors()))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        denied = await client.post("/v1/chat/completions", json={"messages": [{"role": "user", "content": "hello"}]})
        assert denied.status_code == 401
        headers = {"Authorization": "Bearer test-key", "X-GRND0-Session-ID": "session-test"}
        response = await client.post("/v1/chat/completions", headers=headers, json={"messages": [{"role": "user", "content": "hello"}]})
        assert response.status_code == 200
        assert response.json()["choices"][0]["message"]["content"] == "stub:hello"
        state_response = await client.get("/api/v1/health/discourse-state?session_id=session-test", headers=headers)
        assert state_response.json()["current_turn"] == 1
        turn_response = await client.get("/api/v1/health/last-turn?session_id=session-test", headers=headers)
        assert turn_response.json()["schema"] == "grnd0.receipt.v1"
        lane_response = await client.get("/health/lanes", headers=headers)
        assert lane_response.status_code == 200
        assert {item["backend_kind"] for item in lane_response.json()["lanes"]} == {"local"}


def test_lane_and_source_examples_are_local_first(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GRND0_ENABLE_HOST_GPU", raising=False)
    monkeypatch.delenv("GRND0_ENABLE_CLOUD_ACCELERATOR", raising=False)
    lanes = json.loads((ROOT / "configs" / "lanes.example.json").read_text(encoding="utf-8"))
    sources = json.loads((ROOT / "configs" / "knowledge-sources.example.json").read_text(encoding="utf-8"))
    assert lanes["backends"]["local-inference"]["kind"] == "local"
    assert lanes["backends"]["local-inference"]["enabled"] is True
    assert lanes["backends"]["cloud-accelerator"]["enabled"] is False
    active_lanes = [item for item in lanes["lanes"] if item.get("enabled", True)]
    assert all(item["backend"] == "local-inference" for item in active_lanes)
    inventory = LaneRouter(ROOT / "configs" / "lanes.example.json").public_inventory()
    assert {item["model"] for item in inventory} == {"reference-primary"}
    assert {item["backend_kind"] for item in inventory} == {"local"}
    assert any(item["id"] == "grnd0-public" and item["enabled"] for item in sources["sources"])
    assert not any(item["id"].startswith("operator-") and item["enabled"] for item in sources["sources"])


def test_reference_pack_generates_deterministic_local_config(tmp_path: Path) -> None:
    first = tmp_path / "first.yaml"
    second = tmp_path / "second.yaml"
    arguments = {
        "pack": "reference-chat",
        "models_root": tmp_path / "models",
        "catalog_path": ROOT / "configs" / "GRND0_MODEL_CATALOG.json",
        "require_models": False,
        "packs_root": ROOT / "packs",
    }
    generate(output=first, **arguments)
    generate(output=second, **arguments)
    assert first.read_bytes() == second.read_bytes()
    assert "reference-primary" in first.read_text(encoding="utf-8")
    assert "/models/reference-chat-0.0.1/" in first.read_text(encoding="utf-8")


def test_vulkan_engine_generates_a_local_lane_serve_command(tmp_path: Path) -> None:
    packs = tmp_path / "packs"
    pack = packs / "gpu-proof-0.0.0"
    pack.mkdir(parents=True)
    (pack / "pack.yaml").write_text("name: gpu-proof\nmodels: models.yaml\n", encoding="utf-8")
    (pack / "models.yaml").write_text(
        "models:\n  primary:\n    logical_name: reference-primary\n"
        "    artifact: operator-model.gguf\n    engine: llama.cpp-vulkan\n",
        encoding="utf-8",
    )
    output = tmp_path / "gpu.yaml"
    generate(
        "gpu-proof",
        output,
        tmp_path / "models",
        ROOT / "configs" / "GRND0_MODEL_CATALOG.json",
        False,
        packs,
        "windows-host",
        "llama.cpp-vulkan",
        str(tmp_path / "operator bin" / "llama-server.exe"),
    )
    generated = output.read_text(encoding="utf-8")
    assert "--n-gpu-layers 999" in generated
    assert "--flash-attn on" in generated
    assert "reference-primary" in generated
    assert "gpu-proof-0.0.0" in generated and "operator-model.gguf" in generated
    assert "llama-server.exe" in generated


def test_native_gpu_grant_selects_host_local_lanes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GRND0_ENABLE_OPERATOR_LOCAL", raising=False)
    monkeypatch.setenv("GRND0_ENABLE_HOST_GPU", "1")
    router = LaneRouter(ROOT / "configs" / "lanes.example.json")
    synthesis = router.select(HarnessRegistry(ROOT / "data" / "harness_templates").require("reference-chat"), 2)
    assert synthesis.name == "host-gpu-reasoning"
    assert synthesis.backend == "host-gpu-inference"
    assert synthesis.backend_kind == "local"


def test_wsl_local_grant_reaches_named_lanes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GRND0_ENABLE_HOST_GPU", raising=False)
    monkeypatch.setenv("GRND0_ENABLE_OPERATOR_LOCAL", "1")
    router = LaneRouter(ROOT / "configs" / "lanes.example.json")
    synthesis = router.select(HarnessRegistry(ROOT / "data" / "harness_templates").require("reference-chat"), 2)
    assert synthesis.name == "operator-local-reasoning"
    assert synthesis.backend == "operator-local-inference"
    assert synthesis.backend_kind == "local"

    launcher = (ROOT / "tools" / "start-wsl-model.ps1").read_text(encoding="utf-8")
    assert "Start-Process wsl.exe" in launcher
    assert '"--host", "0.0.0.0"' in launcher
    assert "/health" in launcher



def test_model_pull_verifies_digest_and_installs_atomically(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    content = b"small public test artifact"
    digest = hashlib.sha256(content).hexdigest()
    packs = tmp_path / "packs"
    pack = packs / "test-pack-0.0.0"
    pack.mkdir(parents=True)
    (pack / "pack.yaml").write_text("name: test-pack\nmodels: models.yaml\n", encoding="utf-8")
    (pack / "models.yaml").write_text(
        "models:\n  primary:\n    logical_name: test-model\n    artifact: test.gguf\n"
        f"    download: https://example.invalid/test.gguf\n    sha256: {digest}\n",
        encoding="utf-8",
    )

    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.close()

    monkeypatch.setattr("tools.grnd0_models.urllib.request.urlopen", lambda *args, **kwargs: Response(content))
    models_root = tmp_path / "models"
    pull("test-pack", models_root, False, packs)
    target = models_root / pack.name / "test.gguf"
    assert target.read_bytes() == content
    assert not list(target.parent.glob("*.part"))


def test_core_has_no_external_infrastructure_dependency() -> None:
    core = ROOT / "services" / "orchestrator_daemon"
    text = "\n".join(
        path.read_text(encoding="utf-8", errors="strict")
        for path in core.rglob("*.py")
    ).casefold()
    for dependency in ("postgres", "nats", "qdrant", "valkey", "jaeger"):
        assert dependency not in text


def test_document_links_resolve_and_environment_is_documented() -> None:
    for document in ROOT.rglob("*.md"):
        body = document.read_text(encoding="utf-8")
        for target in re.findall(r"(?<!!)\[[^]]+\]\(([^)]+)\)", body):
            relative = target.strip().split("#", 1)[0]
            if not relative or "://" in relative or relative.startswith("mailto:"):
                continue
            assert (document.parent / relative).resolve().exists(), f"dangling link in {document}: {target}"

    lines = (ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
    previous_content = ""
    for line in lines:
        if line and not line.startswith("#"):
            assert re.match(r"^GRND0_[A-Z0-9_]+=", line)
            assert previous_content.startswith("#"), f"undocumented environment variable: {line}"
        if line:
            previous_content = line
