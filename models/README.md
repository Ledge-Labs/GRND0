# Local model artifacts

This directory is the operator-controlled model store mounted read-only at
`/models` inside the GRND0 inference service. Model weights are not part of the
repository.

`./grnd0 models pull reference-chat` on POSIX systems or
`.\grnd0.ps1 models pull reference-chat` on Windows places the reference GGUF
under `models/reference-chat-0.0.1/` after verifying its SHA-256 digest.

Generated serving configuration refers only to paths below `/models`. A custom
engine command remains confined to the operator-selected inference image and
receives no host filesystem mount beyond this read-only directory.
