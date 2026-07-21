<div align="center">

# GRND0

**A local-first compound-AI runtime.**
*Pronounced "ground zero." A project of Ledge AI Research.*

[![Version](https://img.shields.io/badge/version-0.0.1-informational)](CHANGELOG.md)
[![License](https://img.shields.io/badge/license-MPL--2.0%20%7C%20Apache--2.0-blue)](LICENSING.md)
[![Status](https://img.shields.io/badge/status-research%20preview-orange)](#versioning)
[![API](https://img.shields.io/badge/API-OpenAI%20%7C%20Anthropic-black)](#what-grnd0-is)
[![Inference](https://img.shields.io/badge/inference-local--first%20%7C%20engine--agnostic-lightgrey)](#local-inference)

</div>

## The problem

The capability frontier in open models tracks parameter count, and leading systems are now measured in the hundreds of billions of parameters, with each generation larger than the last. Hardware available to an individual — including systems built for on-device inference — cannot serve a model at that scale. Frontier capability and personally owned hardware have diverged, and the distance between them grows with every model release.

## Approach

GRND0 is built on a hypothesis: that a frontier-level result need not come from a single frontier-scale model, but from capable component models coordinated under structure, memory, and verification. GRND0 composes many model calls — and, where configured, routes them across several models a single machine can serve — into one endpoint, and adds capability to the runtime rather than to a fixed set of weights.

Model systems advanced through conversation, tool use, and agency, and scaled those capabilities by enlarging the model. GRND0 pursues the same progression along a different axis: composition and scheduling in place of parameter growth. The design objective is frontier-level output from hardware an individual owns — a 128 GB system at present, with progressively smaller targets as the approach matures. This first release is conversation; further capabilities follow.

It rests on an established observation: on a sufficiently bounded task, a small model matches or exceeds a much larger one. Complex requests decompose into bounded operations — reference resolution, planning, scoped retrieval, individual judgments, and verification — each within the reach of a small, appropriately directed model. The quality of a completed turn then depends on how those operations are composed, routed, and checked, not only on any single model's parameter count. The distance this composition closes to frontier-scale monolithic models, and the hardware on which it closes, is what GRND0 tests: it records a structured receipt for every turn and publishes comparative results against a fixed reference configuration rather than asserting them. [RESULTS.md](RESULTS.md) defines that evaluation.

## What GRND0 is

GRND0 is a local-first compound-AI runtime that occupies the position of a model. It presents OpenAI- and Anthropic-compatible chat endpoints, so many existing clients, agent frameworks, and applications work against it with little or no modification.

A model is not a single kind of component: it can reason, act as an agent, classify, or serve as a probabilistic decision inside a larger process. GRND0 composes these uses — and the software that wraps models — behind one endpoint intended to remain viable across the range of AI use cases.

It is model-agnostic: it operates over any model exposing an OpenAI- or Anthropic-compatible API, local or remote, and coordinates several concurrently. It is machine-agnostic by design; no part of the runtime is bound to a specific processor. A bundled inference layer serves local models on available hardware, and cloud models may be attached for fallback or acceleration.

The runtime operates on model knowledge alone and gains capability as operator-owned data, tools, repositories, and vector stores are connected, and as additional lanes and harnesses are configured.

## How a turn works

GRND0 arranges model calls and the software around them into a typed turn:

1. **Subject resolution** binds references against the committed conversation spine.
2. **Comprehension** produces a plan: deliverable, evidence, depth, aperture, and verification frame.
3. **Effort-aware routing** selects a lane and its local or cloud backend for each named harness.
4. **Retrieval** reads only connected and granted sources, and only when the plan selects connected evidence.
5. **Recursive reduction** condenses long evidence into a bounded working set before synthesis.
6. **Synthesis** follows a focused, extended, or report aperture. Focused answers use one composition call; report answers use an outline, bounded per-section authoring, and deterministic assembly over the same working set. The synthesis lane may also emit client-controlled tool calls.
7. **Verification** judges the candidate before emission. Missing grounding produces a typed abstention; any other failed check remains visibly labeled.
8. **Commit and receipt.** One authoritative discourse update commits after the turn, followed by a durable execution receipt.

This lifecycle is implemented in `services/orchestrator_daemon/app/cognitive_loop/`; the connector boundary in `services/orchestrator_daemon/app/connectors/`. [Architecture](docs/ARCHITECTURE.md) maps the complete request path.

## Local inference

GRND0 is engine-agnostic. The bundled inference layer uses llama-swap to coordinate model processes on a single device — starting, stopping, and proxying them on demand — so several models share the machine, each served by the software best suited to it. The default distribution serves llama.cpp; the same mechanism drives llama.cpp compiled for Vulkan, ROCm, CUDA, or Metal, and other OpenAI-compatible local servers such as vLLM.

GRND0 was developed and measured on a Strix Halo-class system with 128 GB of unified memory; its present target is prosumer and high-end consumer hardware. The reference model is approximately 26 GB and runs on substantially less than the development machine's memory — the 128 GB figure is the development hardware, not a minimum for the reference pack; larger memory enables more concurrent lanes, longer context, and additional capabilities. Output quality, latency, and capacity vary with the machine and the models in use. The runtime is identical across systems; the ceiling is set by hardware and configuration.

Core answering has two service dependencies: llama-swap for on-demand model serving, and embedded SQLite for conversation state, receipts, and the optional local knowledge index. No external database, message bus, cache, vector store, or tracing service is required.

## Current capability surface

- OpenAI-compatible `/v1/chat/completions` and Anthropic-compatible `/v1/messages` endpoints.
- Bundled llama-swap integration with generated configuration and on-demand GGUF serving.
- Native Vulkan and persistent WSL serving seams for operator-supplied local runtimes that cannot use the portable CPU container.
- Typed comprehension and per-lane local or cloud backend routing.
- Conversation-complete synthesis: compact focused answers and multi-section report authoring over one bounded evidence set.
- Public self-knowledge, read-only folder retrieval, an ingestible local knowledge index, and an HTTP vector-store adapter.
- Optional web search and browser-backed reading, disabled until `GRND0_ALLOW_WEB=1`.
- Optional local Gitea repository retrieval, disabled until `GRND0_ALLOW_GIT=1`.
- Client-supplied OpenAI and Anthropic tool definitions passed through to the selected model lane.
- Stateful topic return, pronoun resolution, recap context, typed verification, and inspectable receipts.

## Quickstart

Requirements: Docker with Compose, Python 3.12, and `uv`. The reference GGUF is approximately 26.3 GB; local execution requires additional memory for context and runtime overhead.

```powershell
./tools/bootstrap-env.ps1
uv sync --frozen
.\grnd0.ps1 models pull reference-chat
```

The POSIX model command is equivalent:

```sh
uv sync --frozen
sh ./grnd0 models pull reference-chat
```

Core startup generates the llama-swap configuration from the public catalog and pack, mounts `models/` read-only, and starts the local inference service:

```powershell
docker compose up --build -d --wait
```

```powershell
$key = ((Get-Content .env | Where-Object { $_ -match '^GRND0_API_KEY=' }) -split '=',2)[1]
$headers = @{ Authorization = "Bearer $key"; 'X-GRND0-Session-ID' = 'example-session' }
$body = @{ model='reference-chat'; messages=@(@{role='user'; content='What is GRND0?'}) } | ConvertTo-Json -Depth 8
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/v1/chat/completions -Headers $headers -ContentType application/json -Body $body
```

The generated `.env` contains API, internal capability, and Gitea credentials. All published ports bind to `127.0.0.1` by default; a public bind requires authentication. Core persists through SQLite and does not require Postgres, NATS, Qdrant, Valkey, or Jaeger.

The pinned portable inference image is CPU-only. The native Windows GPU path uses the same host llama-swap and Vulkan llama-server mechanism as the development stack, reduced to pack generation and process launch. It is an explicit local grant; lane routing and receipts are unchanged. Setup and its hardware-proof boundary are defined in [Inference](docs/INFERENCE.md).

`GET /health/lanes` reports each enabled lane, backend kind, and model. Turn receipts record the same backend identity for every internal call.

## Cloud fallback or acceleration

Cloud inference is disabled by default. An explicit cloud lane requires `GRND0_ENABLE_CLOUD_ACCELERATOR=1`, a provider URL, a provider model, an optional key, and a lane role assignment in `configs/lanes.example.json`.

```dotenv
GRND0_ENABLE_CLOUD_ACCELERATOR=1
GRND0_PROVIDER_BASE_URL=https://provider.example/v1
GRND0_PROVIDER_MODEL=provider-model
GRND0_PROVIDER_API_KEY=
```

GRND0 is designed for local inference. Routing whole sessions to cloud can be expensive and is largely redundant with capable local lanes. Cloud service is intended for unavailable local lanes or isolated hard-lane acceleration, not as the default path. [Inference](docs/INFERENCE.md) defines the model store, generator, engine contract, lane wiring, and hardware boundary.

## Capability profiles

| Profile | Added mechanism | Required grant |
| --- | --- | --- |
| `core` (default) | llama-swap local inference, per-lane gateway, conversation loop, SQLite state, registry, public self-knowledge | None |
| `web` | Browser harness and web-research service | `GRND0_ALLOW_WEB=1` |
| `git` | Local Gitea service and repository connector | `GRND0_ALLOW_GIT=1` |
| `full` | Web, git, and bundled vector-store service | Grants for each connected mechanism |

```powershell
docker compose --profile web up --build -d --wait
docker compose --profile git up -d --wait
docker compose --profile full up --build -d --wait
```

Folder, vault, vector, web, git, and local-index configuration is defined in [Connecting data](docs/CONNECTING-DATA.md). GRND0 is designed to sit beneath external AI tools and agents; those tools may also be attached to it directly. [Extending](docs/EXTENDING.md) documents both surfaces.

## Showcase

`assets/showcase/` contains a complete, unedited conversation with a live GRND0 endpoint: factual questions, follow-ups across topic changes and returns, an in-depth comparison, a creative request, a self-description, a web-grounded lookup, and a full-conversation summary — including one answer the system flagged as failing its own verification and subsequently corrected.

The showcase was produced on a specific developer configuration. Output on another installation will differ; it depends on the models served, the tools and repositories connected, the harnesses configured, and the data present in the system, including knowledge stores and vector indexes. The showcase demonstrates runtime behavior and does not characterize the output of any particular installation.

## State and receipts

`GET /api/v1/health/discourse-state?session_id=...` exposes the committed conversation spine. `GET /api/v1/health/last-turn?session_id=...` exposes each lane, backend kind, resolved model, typed plan, retrieval provenance, verification result, timing, and state commit count. Both routes require endpoint authentication.

## Limitations

The repository contains no model weights and no private corpus. The reference model is a substantial download and the portable default image is CPU-only; accelerator images and device grants are operator choices. Folder retrieval is lexical; operator-connected vector services provide semantic retrieval. Web search depends on the configured public search origin and network availability. Model quality, latency, and tool-call reliability are properties of the configured lanes. Multimodal and speculative generation loops are not part of this release.

This preview is single-operator: when a client does not supply a session identifier, session state is keyed deterministically, so a shared multi-user endpoint is not yet supported. Streaming responses currently return a single chunk after the turn completes; token-usage counters may report zero; and standard generation parameters such as temperature and maximum tokens are accepted but not yet forwarded through the public loop — full provider conformance is not claimed. The bundled reference pack uses a single model and demonstrates multi-call composition; multi-model lane configurations are operator-defined. The default Docker stack binds to loopback; the native GPU and WSL launchers are advanced paths whose network exposure is documented in [Inference](docs/INFERENCE.md).

Evaluation results remain structured-pending in [RESULTS.md](RESULTS.md). No score is implied by the release version.

## Versioning

`0.0.x` denotes research previews. `0.1.0` denotes the first documented endpoint and pack-contract stability boundary. Semantic versions track public API stability. Outcome gates and cloud comparisons are recorded in `RESULTS.md` independently of version numbers.

## License and acknowledgments

GRND0 is distributed under MPL-2.0; the Python SDK under Apache-2.0. Trademark terms are in [TRADEMARKS.md](TRADEMARKS.md). GRND0 coordinates several open-source projects, including llama-swap and llama.cpp for local inference, each credited in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
