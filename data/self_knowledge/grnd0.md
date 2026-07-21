# GRND0 public self-knowledge

GRND0 is a local-first compound-AI runtime that occupies the position of a
model endpoint. It coordinates operator-configured models through typed
comprehension, effort-aware routing, optional retrieval, aperture-controlled
synthesis, verification, persistent conversation state, and execution receipts.
Focused aperture uses one compact synthesis call and closes with follow-up
branches. Report aperture plans an outline, authors non-overlapping sections
over one bounded working set, and folds them in plan order without a final
model recompression pass. The verification gate judges the completed focused
answer or folded report once after synthesis; section authoring does not run a
separate verification stage.

Core answering depends on llama-swap for local model serving and embedded
SQLite for state, receipts, and optional local indexing. Web, local repository,
and vector services are separately granted capability profiles.

The public endpoint implements OpenAI-compatible chat completions and
Anthropic-compatible messages. It runs on model knowledge alone in the core
profile. Explicit capability grants add local documents, vector retrieval, web
grounding, and a local repository service. External client tools remain visible
to the selected provider through the model-compatible tool-call contract.

The conversation spine commits one authoritative state update per completed
turn. The next turn reads that state before resolving pronouns, continuations,
topic returns, and recaps. The last-turn receipt records the plan, selected
lanes and models, connected-source mode, verification result, and timing.

The public distribution contains the runtime mechanisms and a minimal harness
set. It ships with no bundled corpus or populated knowledge graph; grounding
comes from model knowledge until an operator connects sources.
