# SPDX-License-Identifier: MPL-2.0
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class ModelToolError(RuntimeError):
    pass


def _mapping(path: Path) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ModelToolError(f"cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ModelToolError(f"{path} must contain a mapping")
    return value


def _pack_dir(name: str, packs_root: Path) -> Path:
    if not SAFE_NAME.fullmatch(name):
        raise ModelToolError("pack name contains unsupported characters")
    direct = packs_root / name
    candidates = [direct] if direct.is_dir() else []
    candidates.extend(sorted(path for path in packs_root.glob(f"{name}-*") if path.is_dir()))
    matches: list[Path] = []
    for candidate in candidates:
        descriptor = candidate / "pack.yaml"
        if descriptor.is_file() and str(_mapping(descriptor).get("name") or "") == name:
            matches.append(candidate)
    if not matches:
        raise ModelToolError(f"pack {name!r} was not found under {packs_root}")
    return matches[-1]


def _models(pack_dir: Path) -> list[tuple[str, dict[str, Any]]]:
    descriptor = _mapping(pack_dir / "pack.yaml")
    model_file = str(descriptor.get("models") or "models.yaml")
    path = (pack_dir / model_file).resolve()
    if pack_dir.resolve() not in path.parents:
        raise ModelToolError("pack model path escapes the pack directory")
    raw = _mapping(path).get("models")
    if not isinstance(raw, dict) or not raw:
        raise ModelToolError(f"{path} must declare at least one model")
    result: list[tuple[str, dict[str, Any]]] = []
    for key, value in raw.items():
        if not isinstance(value, dict):
            raise ModelToolError(f"model {key!r} must be a mapping")
        model_id = str(value.get("logical_name") or key).strip()
        artifact = str(value.get("artifact") or "").strip()
        if not SAFE_NAME.fullmatch(model_id) or not SAFE_NAME.fullmatch(artifact):
            raise ModelToolError(f"model {key!r} has an unsafe identifier or artifact name")
        result.append((model_id, value))
    return result


def _artifact_path(models_root: Path, pack_dir: Path, artifact: str) -> Path:
    target = (models_root / pack_dir.name / artifact).resolve()
    root = models_root.resolve()
    if root not in target.parents:
        raise ModelToolError("artifact path escapes the models directory")
    return target


def _engine_command(
    model: dict[str, Any],
    catalog: dict[str, Any],
    model_path: str,
    *,
    engine_override: str = "",
    command_override: str = "",
    windows_command: bool = False,
) -> tuple[str, int, str]:
    engine_name = engine_override or str(model.get("engine") or "llama.cpp")
    engines = catalog.get("engines")
    if not isinstance(engines, dict) or engine_name not in engines:
        raise ModelToolError(f"engine {engine_name!r} is absent from the model catalog")
    template = engines[engine_name]
    if not isinstance(template, dict):
        raise ModelToolError(f"engine {engine_name!r} must be a mapping")
    serve = model.get("serve") if isinstance(model.get("serve"), dict) else {}
    command = command_override or str(serve.get("command") or template.get("command") or "").strip()
    args = serve.get("args", template.get("args", []))
    if not command or not isinstance(args, list) or not all(isinstance(item, str) for item in args):
        raise ModelToolError(f"engine {engine_name!r} has an invalid command contract")
    replacements = {"{model_path}": model_path, "{model_id}": str(model.get("logical_name") or "")}
    tokens = [command, *args]
    rendered: list[str] = []
    for token in tokens:
        value = token
        for marker, replacement in replacements.items():
            value = value.replace(marker, replacement)
        rendered.append(value)
    ttl = int(serve.get("idle_ttl_seconds", template.get("idle_ttl_seconds", 300)))
    check = str(serve.get("check_endpoint", template.get("check_endpoint", "/health")))
    rendered_command = subprocess.list2cmdline(rendered) if windows_command else shlex.join(rendered)
    return rendered_command, max(0, ttl), check


def generate(
    pack: str,
    output: Path,
    models_root: Path,
    catalog_path: Path,
    require_models: bool,
    packs_root: Path,
    runtime: str = "container",
    engine_override: str = "",
    command_override: str = "",
) -> None:
    if runtime not in {"container", "windows-host"}:
        raise ModelToolError("runtime must be container or windows-host")
    pack_dir = _pack_dir(pack, packs_root)
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    rendered_models: dict[str, dict[str, Any]] = {}
    missing: list[str] = []
    for model_id, model in _models(pack_dir):
        artifact = str(model["artifact"])
        host_path = _artifact_path(models_root, pack_dir, artifact)
        if not host_path.is_file():
            missing.append(str(host_path.relative_to(models_root.resolve())))
        model_path = str(host_path) if runtime == "windows-host" else f"/models/{pack_dir.name}/{artifact}"
        command, ttl, check = _engine_command(
            model,
            catalog,
            model_path,
            engine_override=engine_override,
            command_override=command_override,
            windows_command=runtime == "windows-host",
        )
        rendered_models[model_id] = {
            "cmd": command,
            "ttl": ttl,
            "checkEndpoint": check,
        }
    if require_models and missing:
        raise ModelToolError("required model artifacts are absent: " + ", ".join(missing))
    document = {
        "healthCheckTimeout": 600,
        "logLevel": os.getenv("GRND0_INFERENCE_LOG_LEVEL", "info"),
        "models": rendered_models,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    text = "# Generated by tools/grnd0_models.py; do not edit.\n" + yaml.safe_dump(
        document, sort_keys=False, allow_unicode=False
    )
    output.write_text(text, encoding="utf-8", newline="\n")
    print(json.dumps({"status": "generated", "output": str(output), "models": sorted(rendered_models), "missing": missing}, sort_keys=True))


def pull(pack: str, models_root: Path, force: bool, packs_root: Path) -> None:
    pack_dir = _pack_dir(pack, packs_root)
    completed: list[dict[str, Any]] = []
    for model_id, model in _models(pack_dir):
        url = str(model.get("download") or "").strip()
        if not url.startswith("https://"):
            raise ModelToolError(f"model {model_id!r} requires an HTTPS download URL")
        expected = str(model.get("sha256") or "").lower()
        if not re.fullmatch(r"[0-9a-f]{64}", expected):
            raise ModelToolError(f"model {model_id!r} requires a SHA-256 digest")
        target = _artifact_path(models_root, pack_dir, str(model["artifact"]))
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and not force:
            digest = hashlib.sha256()
            with target.open("rb") as source:
                while chunk := source.read(8 * 1024 * 1024):
                    digest.update(chunk)
            actual = digest.hexdigest()
            if actual != expected:
                raise ModelToolError(f"existing artifact failed checksum: {target.name}")
            completed.append({"model": model_id, "artifact": str(target), "status": "present"})
            continue
        request = urllib.request.Request(url, headers={"User-Agent": "GRND0/0.0.1 model-pull"})
        digest = hashlib.sha256()
        fd, temporary_name = tempfile.mkstemp(prefix=target.name + ".", suffix=".part", dir=target.parent)
        try:
            with os.fdopen(fd, "wb") as sink, urllib.request.urlopen(request, timeout=60) as source:
                while chunk := source.read(8 * 1024 * 1024):
                    sink.write(chunk)
                    digest.update(chunk)
            if digest.hexdigest() != expected:
                raise ModelToolError(f"downloaded artifact failed checksum: {target.name}")
            os.replace(temporary_name, target)
        except Exception:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass
            raise
        completed.append({"model": model_id, "artifact": str(target), "status": "downloaded"})
    print(json.dumps({"status": "ok", "pack": pack, "artifacts": completed}, indent=2, sort_keys=True))


def status(pack: str, models_root: Path, packs_root: Path) -> None:
    pack_dir = _pack_dir(pack, packs_root)
    values = []
    for model_id, model in _models(pack_dir):
        target = _artifact_path(models_root, pack_dir, str(model["artifact"]))
        values.append({"model": model_id, "artifact": str(target), "present": target.is_file(), "bytes": target.stat().st_size if target.is_file() else 0})
    print(json.dumps({"pack": pack, "models": values}, indent=2, sort_keys=True))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="grnd0 models", description="Manage public GRND0 model packs and generated inference configuration.")
    parser.add_argument("action", choices=("pull", "generate", "status"))
    parser.add_argument("pack")
    parser.add_argument("--models-root", type=Path, default=REPO_ROOT / "models")
    parser.add_argument("--catalog", type=Path, default=REPO_ROOT / "configs" / "GRND0_MODEL_CATALOG.json")
    parser.add_argument("--packs-root", type=Path, default=REPO_ROOT / "packs")
    parser.add_argument("--output", type=Path, default=REPO_ROOT / ".grnd0" / "llama-swap.yaml")
    parser.add_argument("--require-models", action="store_true")
    parser.add_argument("--runtime", choices=("container", "windows-host"), default="container")
    parser.add_argument("--engine", default="", help="Override the pack engine for generated serving configuration.")
    parser.add_argument("--server-command", default="", help="Override the engine executable in generated serving configuration.")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    if args.action == "pull":
        pull(args.pack, args.models_root, args.force, args.packs_root)
    elif args.action == "generate":
        generate(
            args.pack,
            args.output,
            args.models_root,
            args.catalog,
            args.require_models,
            args.packs_root,
            args.runtime,
            args.engine,
            args.server_command,
        )
    else:
        status(args.pack, args.models_root, args.packs_root)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ModelToolError, OSError, ValueError, urllib.error.URLError) as exc:
        print(f"model operation failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
