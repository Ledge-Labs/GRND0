# Third-party notices

This register is generated from the locked Python environment and pinned
container references. The machine-readable SBOM is `artifacts/sbom.spdx.json`.
No dependency is represented as first-party source.

## Python distributions

| Distribution | Version | License | Upstream |
|---|---:|---|---|
| annotated-types | 0.7.0 | MIT | https://github.com/annotated-types/annotated-types |
| anyio | 4.14.2 | MIT | https://anyio.readthedocs.io/en/stable/versionhistory.html |
| certifi | 2026.6.17 | MPL-2.0 | https://github.com/certifi/python-certifi |
| click | 8.4.2 | BSD-3-Clause | https://github.com/pallets/click/ |
| colorama | 0.4.6 | BSD-3-Clause | https://github.com/tartley/colorama |
| fastapi | 0.116.1 | MIT | https://github.com/fastapi/fastapi |
| h11 | 0.16.0 | MIT | https://github.com/python-hyper/h11 |
| httpcore | 1.0.9 | BSD-3-Clause | https://www.encode.io/httpcore/ |
| httptools | 0.8.0 | MIT | https://github.com/MagicStack/httptools |
| httpx | 0.28.1 | BSD-3-Clause | https://github.com/encode/httpx |
| idna | 3.18 | BSD-3-Clause | https://github.com/kjd/idna |
| iniconfig | 2.3.0 | MIT | https://github.com/pytest-dev/iniconfig |
| packaging | 26.2 | Apache-2.0 OR BSD-2-Clause | https://github.com/pypa/packaging |
| pluggy | 1.6.0 | MIT | Recorded in package metadata |
| pydantic | 2.11.7 | MIT | https://github.com/pydantic/pydantic |
| pydantic_core | 2.33.2 | MIT | https://github.com/pydantic/pydantic-core |
| Pygments | 2.20.0 | BSD-2-Clause | https://pygments.org |
| pytest | 8.4.1 | MIT | https://docs.pytest.org/en/latest/ |
| pytest-asyncio | 1.1.0 | Apache-2.0 | https://github.com/pytest-dev/pytest-asyncio |
| python-dotenv | 1.2.2 | BSD-3-Clause | https://github.com/theskumar/python-dotenv |
| PyYAML | 6.0.2 | MIT | https://pyyaml.org/ |
| starlette | 0.47.3 | BSD-3-Clause | https://github.com/encode/starlette |
| typing-inspection | 0.4.2 | MIT | https://github.com/pydantic/typing-inspection |
| typing_extensions | 4.16.0 | PSF-2.0 | https://github.com/python/typing_extensions |
| uvicorn | 0.35.0 | BSD-3-Clause | https://www.uvicorn.org/ |
| watchfiles | 1.2.0 | MIT | https://github.com/samuelcolvin/watchfiles |
| websockets | 16.1.1 | BSD-3-Clause | https://github.com/python-websockets/websockets |

## Container images

| Reference | Digest | License register |
|---|---|---|
| python:3.12-slim | `sha256:57cd7c3a7a273101a6485ba99423ee568157882804b1124b4dd04266317710de` | PSF-2.0 and bundled component licenses |
| chromedp/headless-shell:stable | `sha256:88359186a9024c4de0b0245c7001e39d5609e0aa0dafab3a0914e9419f258e28` | BSD-3-Clause and bundled component licenses |
| qdrant/qdrant:latest | `sha256:0bd98fa7977f1e75694779359ca4e212822e5a71334e28421182f72f209d5286` | Apache-2.0 |
| gitea/gitea:latest | `sha256:7dff60d7ea6df9d0bdf78971cdb1350e9b7df3fda5f115c77afe12122887bd64` | MIT |
| ghcr.io/mostlygeek/llama-swap:v173-cpu-b7151 | `sha256:5675b9cc658dcb9fb5eecbaa36a0ae480d7eeed01ef6299d4a9349dbefca158e` | MIT and bundled component licenses |

Container images retain their own notices and bundled component licenses.
Project names and trademarks identify their respective upstream projects.

## Local inference components

GRND0 integrates [llama-swap](https://github.com/mostlygeek/llama-swap)
under the MIT License for on-demand process management and proxying.
The pinned llama-swap image bundles [llama.cpp](https://github.com/ggml-org/llama.cpp)
under the MIT License as its default GGUF serving engine. GRND0 authorship
covers the catalog, generator, lane wiring, and receipt integration; it does
not cover llama-swap or llama.cpp.

## Adapted policy text

`CODE_OF_CONDUCT.md` is adapted from Contributor Covenant 2.1. The file
contains the required source attribution and one modification: the enforcement
contact is the repository security-advisory channel.
