# Releasing

Releases are produced from a source manifest and pass a fail-closed gate
before publication.

- Tests must pass.
- A dependency SBOM and third-party notices are generated from the locked
  environment.
- The tree is scanned for secrets, credentials, absolute paths, and
  disallowed binaries, and every published file is traceable to the manifest.
- Source files carry SPDX identifiers.
- Evaluation claims require reproducible, machine-readable evidence with
  redacted receipts before publication.

Releases are tagged, and large media and proof records are attached to the
corresponding GitHub Release rather than committed to the tree.
