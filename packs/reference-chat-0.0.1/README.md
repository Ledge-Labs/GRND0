# Reference chat pack 0.0.1

This directory is an immutable implementation of `grnd0.pack.chat.v1`.
`models.yaml` fixes the model artifact, engine family, digest, and upstream
revisions. `routing.yaml` maps the public endpoint alias to the bundled local
inference service. The hardware profile records the publication environment.
Eval configurations fix dataset revisions, selection rules, and scoring
contracts.

No credential, host file location, generated runtime configuration, or private
serving calibration is present in the pack.
