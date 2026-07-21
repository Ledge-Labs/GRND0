# Contributing

Contributions preserve the endpoint, pack, licensing, and release-generation
contracts.

Required checks:

- `uv sync --frozen`
- `uv run pytest`
- `python tools/leak-gate.py --root . --manifest release-manifest.yaml`
- `docker compose config`

Public issue attachments may contain only redacted receipts produced by:

```powershell
python tools/export-receipt.py input.json output.redacted.json
```

Unredacted receipts, credentials, absolute paths, host identifiers, private
model locations, and internal benchmark corpora are invalid public artifacts.

Contributions are accepted under the license governing the modified directory.
The Code of Conduct applies to all project spaces.
