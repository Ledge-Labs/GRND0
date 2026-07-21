# Development and provenance

GRND0 development includes AI-assisted implementation and review. All release
content remains subject to human ownership, provenance classification,
license review, tests, and fail-closed export gates. No automated tool is a
repository contributor or commit author.

The public runtime is extracted from GRND0's working conversation path and
cleaned at the release boundary. The extraction preserves the proven planning,
discourse, verification, retrieval, structured synthesis, and receipt
mechanisms while removing private data bindings and inactive branches. No
third-party source was copied into those modules. Adapted policy text and direct dependencies are classified
in the provenance ledger with upstream revisions, licenses, attribution
requirements, and modifications.

The local inference layer applies the same boundary. Public code defines a
generic engine catalog, pack download and digest verification, generated
llama-swap configuration, and per-lane backend routing. Private data bindings
and calibration are not inputs to the export. llama-swap and llama.cpp remain
attributed upstream components rather than first-party source.

Native Vulkan and WSL launchers are cleaned extractions of the development
serving boundary. They preserve host-process lifetime, health, and
container-to-host routing behavior. Model-specific setup and weight locations
remain operator input and are not release-source inputs.

The public tree is generated from `release-manifest.yaml`. Only named manifest
entries enter staging. Transform records define owner substitution, SPDX
injection, deterministic image generation, and approved renames. The leak gate
then verifies content, binary policy, manifest traceability, and release
invariants. Any finding aborts publication. The private development runtime is
not edited to manufacture the public tree; public cleanup lives in the release
source layer and deterministic transforms.
