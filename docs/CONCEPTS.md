# Concepts

## Endpoint

The endpoint is the model-compatible public boundary. OpenAI request handling and Anthropic translation live in `services/orchestrator_daemon/app/api/routes.py`.

## Cognitive loop

The cognitive loop is the ordered turn transaction: comprehension, routing, retrieval, synthesis, verification, discourse commit, and receipt persistence. Its coordinator lives in `services/orchestrator_daemon/app/cognitive_loop/loop.py`.

## Composition plan

A composition plan is the typed control surface for a turn. It declares deliverable, evidence source, thinking depth, answer aperture, verification frame, and answer requirements. Its types live in `services/orchestrator_daemon/app/cognitive_loop/types.py`; its production lives in `comprehension.py`.

## Inference service

The inference service is the bundled llama-swap process that starts and stops
model servers on demand. It reads generated configuration and read-only GGUFs
from `models/`. The Compose service is `local_inference`; configuration
generation lives in `tools/grnd0_models.py`.

The optional native GPU form runs llama-swap and a Vulkan-enabled llama-server
on the Windows host through `tools/start-local-inference-gpu.ps1`. It uses the
same model identifiers and remains a local backend.

Linux-only model runtimes remain local through `tools/start-wsl-model.ps1` and
the explicitly granted `operator-local-inference` backend. WSL owns the model
process; the lane router sees an ordinary compatible local endpoint.

## Inference gateway

The inference gateway is the credential and backend membrane between the
cognitive loop and model servers. It verifies the selected lane-to-backend
mapping and forwards each call to that lane's local or cloud endpoint. Its
implementation lives in `services/inference_gateway/app/main.py`.

## Backend

A backend is a local or cloud OpenAI-compatible endpoint declared in
`configs/lanes.example.json`. Local is the default. Cloud backends remain
disabled until their grant, endpoint, and model are present.

## Model store

The model store is the untracked `models/` directory. Pack artifacts occupy a
versioned subdirectory and are mounted read-only into local inference.

## Lane

A lane maps a harness role and effort range to a backend and model. Deterministic selection lives in `cognitive_loop/routing.py`; public configuration lives in `configs/lanes.example.json`. One local model can satisfy every role. Additional local or explicitly granted cloud lanes scale separate internal roles without changing the endpoint contract.

## Harness

A harness is a named, receipted internal model role with a contract, system prompt, lane class, and knowledge scope. Anonymous internal model calls are invalid. The registry lives in `app/harness_registry.py`; the minimal templates live in `data/harness_templates/`.

## Model-transistor role

An individual model call supplies a bounded judgment or transformation inside the turn transaction. Subject resolution, planning, synthesis, context reduction, verification, and abstention are distinct calls because their inputs, contracts, and receipts differ.

## Answer aperture

Answer aperture is the planned output shape. `focused` produces one compact synthesis call with a branch-offer close. `extended` permits structured depth when the plan warrants it. `report` produces an outline, per-section authoring calls over one frozen working set, and a deterministic fold. Aperture is selected during comprehension and enforced in `cognitive_loop/loop.py` and `cognitive_loop/structured_synthesis.py`.

## Structured synthesis

Structured synthesis is the report-scale composition strategy. The named
`synthesis-outline` harness plans the thesis and section contract. The named
`synthesis-section` harness authors each non-overlapping section from the same
canonical working-set prefix. `cognitive_loop/structured_synthesis.py` validates
the outline and assembles the visible answer without a model recompression
pass. A failed structured attempt degrades to the single synthesis harness.

## Conversation spine

The conversation spine is the authoritative compact state across turns: active subject, topic stack, recent turns, source references, and verification state. The reducer in `cognitive_loop/discourse.py` is pure and idempotent. `app/store.py` serializes one update per session after answer judgment.

## Verification and abstention

Verification is the pre-emission judgment over the resolved request, candidate answer, plan, and evidence. Grounding-required requests with no evidence abstain deterministically. Other failed checks remain in the response with an unverified label. The gate lives in `cognitive_loop/verification.py`.

## Receipt

A receipt is the durable machine-readable account of one turn. It records the plan, lanes, backend kinds, models, retrieval mode and source hashes, verification result, capability grants, timing, and discourse commit. Receipt storage lives in `app/store.py`; inspection is exposed by `/api/v1/health/last-turn`.

## Capability grant

A capability grant is an explicit operator authorization represented by configuration and runtime flags. File reads require an authorized root. Web and local-git connectors require separate enable flags and generated credentials. External tools remain under the calling client's execution authority.

## Knowledge source

A knowledge source implements the typed search contract in `app/connectors/base.py`. Bundled adapters cover read-only local files, an HTTP vector query endpoint, browser-backed web research, local Gitea, and the runtime's SQLite knowledge index. The public self-description in `data/self_knowledge/grnd0.md` is an ordinary trusted source.

## Recursive context

Recursive context reduction bounds oversized retrieval without removing source identity. `cognitive_loop/recursive_context.py` divides evidence into bounded chunks and invokes the named `recursive-context` harness. Its derived notes retain source labels and content hashes in the receipt path.

## Pack

A pack is a versioned model, routing, hardware, and evaluation contract. The loader and format are public. `packs/reference-chat-0.0.1/` is the sole bundled recipe and is intentionally one generation behind private calibration.
