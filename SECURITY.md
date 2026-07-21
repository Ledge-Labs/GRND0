# Security policy

## Supported release

Security fixes apply to the latest published research preview.

## Report channel

Private vulnerability reports use the repository security-advisory channel.
Public issues are not a vulnerability-report channel.

## Deployment invariants

- Host port mappings bind to loopback by default.
- Public binding requires endpoint authentication.
- Endpoint and gateway credentials are generated independently.
- Debug routes are disabled by default and remain authenticated when enabled.
- Core and capability profiles contain no writable host mounts.
- Local model weights are mounted read-only; generated inference configuration
  resides in a named volume and contains no credential.
- Local document access is limited to read-only mounts and
  `GRND0_AUTHORIZED_READ_ROOTS`.
- Web and local-git connectors remain disabled until separate runtime grants
  are present.
- Web fetches reject non-public destinations and validate redirect hops.
- The browser harness is isolated from the core service network on a dedicated
  egress bridge.
- Autonomous remediation is absent from the public runtime.
- Provider credentials remain runtime environment values and never enter packs,
  receipts, or repository files.
- Cloud backends remain disabled until an explicit enable flag, endpoint,
  model, and lane-role assignment are present.

## Receipt handling

Only redacted receipts are valid public issue attachments. The
`tools/export-receipt.py` transform removes credentials, absolute paths, network
identifiers, and operator-defined sensitive keys before output.
