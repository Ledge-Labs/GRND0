# Local inference

## Runtime boundary

The default Compose stack includes `local_inference`, a digest-pinned
llama-swap service. GRND0 supplies the model-store convention, public catalog,
pack reader, generated configuration, lane wiring, health surfaces, and
receipt fields. llama-swap supplies on-demand process management and proxying;
llama.cpp supplies the reference GGUF server. Their licenses and upstream
ownership are recorded in `THIRD_PARTY_NOTICES.md`.

`models/` is the only model-weight mount. The mount is read-only inside the
inference service. Repository ignore rules exclude all contents except
`models/README.md`.

## Reference model installation

The public reference pack identifies one revision-pinned GGUF and SHA-256
digest. The model helper downloads to a temporary file, verifies the complete
digest, and atomically installs the artifact.

```powershell
uv sync --frozen
.\grnd0.ps1 models pull reference-chat
.\grnd0.ps1 models status reference-chat
```

```sh
uv sync --frozen
sh ./grnd0 models pull reference-chat
sh ./grnd0 models status reference-chat
```

The resulting location is
`models/reference-chat-0.0.1/Qwen3-30B-A3B-Thinking-2507-UD-Q6_K_XL.gguf`.
No host-absolute path enters generated configuration or receipts.

## Configuration generation

`tools/grnd0_models.py` reads `configs/GRND0_MODEL_CATALOG.json` and the
selected pack's `models.yaml`. It emits deterministic llama-swap YAML into an
untracked location. Compose runs the same generator as a one-shot
`inference_config` service before local inference starts.

The same generator accepts `--runtime windows-host`, `--engine
llama.cpp-vulkan`, and `--server-command` from the native GPU launcher. Host
paths occur only in the generated untracked configuration; they never enter a
pack, receipt, or exported file.

The catalog defines engine command templates. A model selects an engine by
name. A pack can replace the template with a `serve.command` and `serve.args`
contract when the selected inference image contains another OpenAI-compatible
server executable. The process must bind the supplied `${PORT}` and expose the
configured health path. This contract supports llama.cpp and any serve command
available inside an operator-selected inference image.

The public generator produces a straightforward per-model configuration;
advanced scheduling and hardware tuning are operator-supplied. llama-swap
performs basic on-demand replacement and idle unloading.

## Lane and backend mapping

`configs/lanes.example.json` is shared by the orchestrator and inference
gateway. Every lane names a backend, model, harness roles, effort interval, and
priority. Every backend declares `kind: local` or `kind: cloud`.

The default tactical and reasoning lanes both use `local-inference`. Different
local model identifiers can be assigned after corresponding catalog and pack
entries exist. A cloud backend resolves its endpoint, key, and model from
named environment variables; secrets never appear in lane configuration.

The gateway accepts the lane selected by the cognitive loop, verifies that the
lane maps to the requested backend, and forwards only to that backend. A single
provider configuration remains available through the cloud-accelerator
backend and the `GRND0_PROVIDER_*` environment variables.

Cloud activation requires all of the following:

- `GRND0_ENABLE_CLOUD_ACCELERATOR=1`;
- `GRND0_PROVIDER_BASE_URL` and `GRND0_PROVIDER_MODEL`;
- `GRND0_PROVIDER_API_KEY` when required by the provider;
- an explicit harness-role assignment to the cloud lane.

GRND0 is designed for local inference. Whole-session cloud routing can be
expensive and is largely redundant with capable local models. Cloud lanes are
fallbacks for unavailable local service or accelerators for isolated hard
roles.

## Observability

`GET /health/lanes` and `GET /api/v1/health/lanes` expose enabled lane names,
backend identifiers, backend kinds, and configured model identifiers. Each
entry in `grnd0_receipt.route` records harness, lane, backend, backend kind,
resolved model, and duration. `GET /api/v1/health/last-turn` returns the durable
receipt.

## Hardware

The pinned portable image uses CPU inference. The reference artifact is
approximately 26.3 GB, and working memory for context and process overhead is
additional; at least 40 GB of available system memory is a practical floor for
this reference configuration. Smaller operator-authored packs can target
smaller systems.

The native Windows GPU path is extracted from the development inference
mechanism used for AMD unified-memory hardware. llama-swap runs on the host and
starts a Vulkan-enabled llama-server on demand; containers reach its loopback
listener through `host.docker.internal`. This avoids treating unsupported APU
device passthrough as a working container GPU path.

### Native GPU-backed local lanes

GPU placement is a serving property, not a different trust class. The enabled
`host-gpu-tactical` and `host-gpu-reasoning` lanes retain `kind: local`, select
the same logical pack model, and record `host-gpu-inference` in receipts.

A pinned Windows llama-swap binary and a compatible Vulkan-enabled
`llama-server.exe` are supplied by the operator. Model weights remain under
`models/`. The launcher validates both executables and the model, generates a
host-path llama-swap configuration from the pack, binds the proxy to loopback,
and waits for health:

```powershell
.\tools\start-local-inference-gpu.ps1 `
  -LlamaSwap .\operator-bin\llama-swap.exe `
  -LlamaServer .\operator-bin\llama-server.exe `
  -Background
```

The generated command uses the public `llama.cpp-vulkan` engine contract:
full GPU layer offload, Vulkan flash attention, the pack model, and the public
context default. Model-specific tuning is operator-supplied and is not part of
the release.

The host proxy occupies port `9292`. The bundled CPU service therefore uses a
different published status port when both mechanisms are present:

```dotenv
GRND0_ENABLE_HOST_GPU=1
GRND0_HOST_GPU_BASE_URL=http://host.docker.internal:9292/v1
GRND0_INFERENCE_PORT=9293
```

`docker compose up --build -d --wait` then retains the CPU service as an
available local mechanism while routing named harness lanes to the native GPU
backend by priority. Removing the GPU grant restores the bundled CPU lanes.

A GPU proof requires the Vulkan server startup log to identify the accelerator
and a local drive receipt to name `host-gpu-inference`. A healthy proxy alone
does not prove offload. Other GPU runtimes use the same pack engine and local
backend contracts with an operator-provided compatible serve command and
device boundary.

The release records those two observations in
`artifacts/gpu-runtime-proof.json` and the full conversation transcript in
`artifacts/drive-showcase-gpu.json`.

Hardware-specific layer splits, cache layouts, residency policy, and tuned
argument recipes remain outside the public runtime.

### WSL and Linux-only model servers

Some model formats require their upstream Linux runtime rather than the
bundled llama.cpp build. The public WSL launcher preserves the proven process
boundary without embedding a model recipe: a dedicated `wsl.exe` process owns
the Linux server, the server binds `0.0.0.0` inside WSL, Windows forwards its
port, and Docker reaches it through `host.docker.internal`.

The operator supplies an already-installed Linux server, model, and arguments:

```powershell
.\tools\start-wsl-model.ps1 `
  -WslServerPath /opt/operator-runtime/llama-server `
  -WslModelPath /opt/operator-models/model.gguf `
  -Port 9300 `
  -ServerArguments @('--parallel','1','--ctx-size','8192')
```

The launcher validates shell-safe absolute paths, starts the server in the
foreground of a hidden persistent WSL process, and waits for `/health`.
Connection to the conversation loop is explicit:

```dotenv
GRND0_ENABLE_OPERATOR_LOCAL=1
GRND0_OPERATOR_LOCAL_BASE_URL=http://host.docker.internal:9300/v1
```

The enabled `operator-local-tactical` and `operator-local-reasoning` entries
then route named harness calls to that local endpoint. Duplicate backend and
lane entries allow different Linux services to cover different harness roles.
Receipts preserve the selected local backend and returned model identity.

The release-time Linux route observation is recorded in
`artifacts/wsl-routing-proof.json`.

Model-specific repositories, build commands, weight locations, context sizes,
parallelism, and assignment policy belong to operator-authored packs and lane
configuration. The release carries the working WSL lifecycle and routing seam;
the specific model configuration is operator-supplied.
