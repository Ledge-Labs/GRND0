# Architecture

## Turn lifecycle

```text
compatible request
  -> authenticated endpoint
  -> committed discourse-state read
  -> subject resolution
  -> typed comprehension plan
  -> effort-aware lane and backend routing
  -> bundled local inference or explicitly granted cloud backend
  -> granted-source retrieval when selected
  -> recursive context reduction when oversized
  -> focused single-pass or outline/section/fold synthesis
  -> structured external tool call when supplied by the client
  -> verification / typed abstention
  -> one atomic discourse commit
  -> durable execution receipt
  -> compatible response
```

The discourse read occurs before internal model work. The discourse write occurs once, after the candidate has passed through the emit gate. Duplicate update identifiers are idempotent, and each session has an independent commit lock.

## Runtime map

| Location | Responsibility |
| --- | --- |
| `services/orchestrator_daemon/app/api/` | Authentication, compatible request translation, health and knowledge routes |
| `services/orchestrator_daemon/app/cognitive_loop/` | Typed plan, routing, retrieval orchestration, synthesis, verification, discourse reducer |
| `services/orchestrator_daemon/app/connectors/` | Operator-granted local, vector, web, git, and indexed knowledge adapters |
| `services/orchestrator_daemon/app/store.py` | SQLite receipts, atomic discourse state, and local knowledge index |
| `services/inference_gateway/` | Per-lane backend validation, credential boundary, and local/cloud forwarding |
| `local_inference` Compose service | On-demand model processes behind llama-swap's compatible endpoint |
| `tools/start-local-inference-gpu.ps1` | Native Windows llama-swap launch with a Vulkan-enabled llama-server and generated public-pack configuration |
| `tools/start-wsl-model.ps1` | Persistent WSL process boundary for Linux-only OpenAI-compatible model servers |
| `models/` | Untracked operator model artifacts, mounted read-only |
| `tools/grnd0_models.py` | Pack download, digest verification, and deterministic serving-config generation |
| `services/web_research/` | Public-origin validation, search, bounded fetch, and browser-backed reading |
| `configs/` | Operator lane, connector, and empty internal tool-connection configuration |
| `data/harness_templates/` | Minimal named inner-harness contracts |
| `data/self_knowledge/` | Public project facts available as connected evidence |
| `packs/` | Frozen public recipe and evaluation contract |
| `evals/public/` | Machine-readable result schema; no private evaluation corpus |

## Service dependencies

| Profile | Required services | Purpose |
| --- | --- | --- |
| `core` (default) | llama-swap and embedded SQLite | On-demand local model serving; conversation state, receipts, and optional local text indexing |
| `web` | Core plus browser harness and web-research | Explicitly granted public-web search and rendered-page reading |
| `git` | Core plus Gitea | Explicitly granted local repository storage and retrieval |
| `full` | Core plus web, git, and Qdrant | Every shipped capability service, including an operator-configured vector-store attachment point |

Core answering has exactly two service dependencies: llama-swap and embedded
SQLite. Every other service is an opt-in capability or scaling point. The
orchestrator and inference gateway are GRND0 processes in the core stack, not
external infrastructure dependencies. No Postgres, NATS, Qdrant, Valkey, or
Jaeger service is required by core.

## Request and model boundaries

The orchestrator exposes the public API and never sends backend credentials to clients. The lane router selects a model and backend for every named harness call. The inference gateway validates that selection against `configs/lanes.example.json`, then forwards to bundled local inference or an explicitly enabled cloud endpoint. A single local model satisfies every default role. Multiple lanes can assign planning, synthesis, retrieval reduction, and verification to different local or cloud models.

The `inference_config` one-shot service reads the public catalog and reference
pack and writes generated llama-swap YAML to a named volume. `local_inference`
reads that volume and the read-only `models/` mount. A request naming a model
causes llama-swap to start its declared server command and unload an
incompatible resident model as required. No private residency scheduler is
present.

The optional native GPU path uses the same generated contract with resolved
host paths and an operator-supplied Vulkan server binary. Enabling
`GRND0_ENABLE_HOST_GPU` activates higher-priority local lanes whose backend is
`host.docker.internal`; it does not introduce a cloud route or a second routing
algorithm. The bundled CPU lanes remain the default when that grant is absent.

Linux-only runtimes use the same routing boundary without passing through the
bundled inference container. The extracted WSL launcher keeps the server in a
dedicated foreground WSL process; the `operator-local-inference` backend makes
its Windows-forwarded port available to named lanes. Model-specific setup and
assignment remain operator configuration.

Every internal call resolves through `HarnessRegistry.require`. A missing harness or lane is a startup or request failure rather than an anonymous fallback.

## Synthesis boundary

The bounded working set contains the resolved query, subject, typed composition
plan, prior discourse render, connected evidence, evidence mode, and client
system contract. Focused aperture sends that set through the named synthesis
harness once and closes with specific follow-up branches. Report aperture first
produces a typed outline, then authors each section against a byte-identical
canonical working-set prefix. Code folds the thesis and surviving sections in
outline order; no final model pass recompresses the answer. Extended aperture
uses the same structured path when deliberate depth or three or more answer
requirements warrant it.

An invalid outline, failed section set, or other structured-path error returns
to the original single synthesis call. The receipt records `structured`,
`single`, or `single_fallback` and the planned and authored section counts.
Tool-bearing requests remain on the single-call path so structured tool calls
retain the compatible endpoint contract.

## Evidence boundary

The connector registry exposes availability without exposing credentials or host paths. Retrieval results carry a public source identifier, relative locator or public URL, relevance score, and content digest. Raw absolute paths are not written to receipts.

The core profile has one connected source: the shipped public self-description. Other facts may be answered from stable trained knowledge when the plan permits it. Source-bound, private, volatile, or explicitly evidentiary claims require grounding and abstain when no connected source supplies it.

## Tool boundary

OpenAI function definitions and Anthropic tool definitions enter the synthesis call. Structured tool requests return to the calling client or agent for execution. Tool results re-enter as ordinary compatible messages on a later call. Internal model-wide tool connections are declared in `configs/mcp/connections.yaml` and are empty by default.

## Capability profiles

Compose profiles add mechanisms, not hidden policy. `core` is the default and includes local inference. `web` adds the browser and web-research services. `git` adds local Gitea and its generated administrator bootstrap. `full` adds every shipped service, including the vector-store container. Runtime grants remain separately disabled until their environment flags are set.

The browser harness attaches only to the dedicated `web_egress` bridge. The
web-research service spans that bridge and the core network, validates public
origins, and exposes only authenticated search and fetch operations. Public web
content therefore has no browser-network route to the orchestrator, inference
gateway, repository service, or vector store.
