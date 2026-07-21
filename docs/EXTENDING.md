# Extending GRND0

GRND0 has two extension surfaces.

## Build on the endpoint

Model-compatible clients, agents, and user interfaces connect to `/v1/chat/completions` or `/v1/messages`. Client tool definitions pass through the synthesis lane. The client remains the executor and returns tool results in a subsequent message. Session continuity is explicit through `X-GRND0-Session-ID`.

This surface preserves the runtime as a model-shaped component beneath existing agent systems. No connector or harness modification is required.

## Extend the substrate

Substrate extensions alter the internal composition mechanisms:

- A lane entry maps a role and effort range to a named local or cloud backend and model in `configs/lanes.example.json`.
- An engine entry in `configs/GRND0_MODEL_CATALOG.json` defines a generic serve command; a pack selects it from `models.yaml`.
- A harness JSON document adds a named contract, role, prompt, lane class, and knowledge scope under `data/harness_templates/`.
- A knowledge adapter implements `KnowledgeSource` or `VectorStoreSource` from `app/connectors/base.py` and registers through `ConnectorRegistry`.
- An internal tool connection is declared in `configs/mcp/connections.yaml` and requires an explicit capability grant before use.
- A pack binds model references, routing, hardware, and evaluations without changing the endpoint.

Every internal model call remains named and receipted. Every data connection remains bounded by an explicit grant. New source locators remain relative or public, and secrets never enter receipts.

Custom inference images contain any non-default engine executable referenced by
an engine entry. Serve commands receive the generated model path and
llama-swap port. The public runtime does not infer device flags or scheduling
policy.

Native Windows GPU serving uses the extracted host launcher and the public
`llama.cpp-vulkan` engine. An operator-provided server binary replaces the
catalog executable at generation time; the pack continues to supply the model
identity. The host backend is activated only by `GRND0_ENABLE_HOST_GPU`.

## Harness contract

Required harness fields are `name`, `contract`, `role`, `system_prompt`, `lane`, and `knowledge_scope`. Typed judgments also declare `response_schema`. The registry fails closed on missing fields, duplicate names, and unknown harness selection.

## Connector contract

`search(query, limit)` returns immutable `RetrievalHit` values. Each hit contains a stable source identifier, non-secret locator, bounded text, score, and SHA-256 content digest. `status()` reports kind and availability without credentials. Connector errors are isolated and recorded as receipt notes.

## Pack boundary

The pack format and loader are open. Model combinations, prompts, policies, and collected calibration data distributed as premium packs remain separate artifacts. Public pack results use the schema in `evals/public/result.schema.json`.
