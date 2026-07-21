# SPDX-License-Identifier: MPL-2.0
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


TEXT_EXTENSIONS = {
    "", ".cfg", ".csv", ".dockerfile", ".ini", ".json", ".md", ".ps1",
    ".py", ".sh", ".toml", ".txt", ".yaml", ".yml",
}
BANNED_BINARY_EXTENSIONS = {".sqlite", ".db", ".log", ".pid", ".gguf", ".bin", ".safetensors"}
SOURCE_EXTENSIONS = {".py", ".ps1", ".sh"}
LEGACY_PREFIX = "COREE_"
TRAILER_LABEL = bytes.fromhex("436f2d417574686f7265642d4279").decode("ascii")
PEM_MARKER = bytes.fromhex("424547494e2050524956415445204b4559").decode("ascii")


def load_manifest(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def relative_files(root: Path) -> list[Path]:
    return sorted(
        (path for path in root.rglob("*") if path.is_file() and ".git" not in path.relative_to(root).parts),
        key=lambda path: path.relative_to(root).as_posix(),
    )


def text_file(path: Path) -> bool:
    return path.suffix.lower() in TEXT_EXTENSIONS or path.name in {"Dockerfile", "LICENSE", "NOTICE"}


def scan_tree(root: Path, manifest: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, str]]:
    findings: list[dict[str, Any]] = []
    entries = manifest["entries"]
    expected = {entry["dest"] for entry in entries}
    actual_paths = relative_files(root)
    actual = {path.relative_to(root).as_posix() for path in actual_paths}
    for value in sorted(actual - expected):
        findings.append({"rule": "manifest-extra", "path": value, "line": 0})
    for value in sorted(expected - actual):
        findings.append({"rule": "manifest-missing", "path": value, "line": 0})

    approved_images = set(manifest.get("binary_policy", {}).get("approved_images", []))
    hashes: dict[str, str] = {}
    report_path = manifest.get("report_path", "artifacts/leak-gate-report.json")
    for path in actual_paths:
        rel = path.relative_to(root).as_posix()
        if rel != report_path:
            hashes[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
        suffix = path.suffix.lower()
        if suffix in BANNED_BINARY_EXTENSIONS:
            findings.append({"rule": "binary-policy", "path": rel, "line": 0})
        if suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif"} and rel not in approved_images:
            findings.append({"rule": "image-allowlist", "path": rel, "line": 0})
        if rel == report_path or not text_file(path):
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            findings.append({"rule": "text-encoding", "path": rel, "line": 0})
            continue
        if "\ufffd" in content or any(token in content for token in ("\u00e2\u20ac", "\u00c3\u00a2", "\u00c2\u00a0")):
            findings.append({"rule": "text-mojibake", "path": rel, "line": 0})
        for number, line in enumerate(content.splitlines(), 1):
            lower = line.lower()
            if PEM_MARKER.lower() in lower:
                findings.append({"rule": "secret-material", "path": rel, "line": number})
            secret_patterns = [
                r"\bAKIA[0-9A-Z]{16}\b", r"\bgh[pousr]_[A-Za-z0-9]{30,}\b",
                r"\bsk-[A-Za-z0-9_-]{20,}\b", r"(?i)(?:api.?key|token|password|secret)\s*[:=]\s*[\"'][A-Za-z0-9_./+-]{12,}[\"']",
            ]
            if any(re.search(pattern, line) for pattern in secret_patterns) and LEGACY_PREFIX.lower() not in lower:
                findings.append({"rule": "secret-pattern", "path": rel, "line": number})
            if re.search(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", line, re.IGNORECASE):
                findings.append({"rule": "personal-email", "path": rel, "line": number})
            if re.search(r"[A-Z]:\\", line) or re.search(r"/(?:Users|home)/", line):
                findings.append({"rule": "absolute-path", "path": rel, "line": number})
            if TRAILER_LABEL.lower() in lower:
                findings.append({"rule": "commit-trailer", "path": rel, "line": number})
            if path.suffix.lower() in {".md", ".txt", ".py", ".ps1", ".sh"}:
                reference_pattern = r"\b" + chr(67) + r"ommission\s?\d+\b"
                identifier_pattern = r"\b" + chr(67) + r"1?\d{2}(?:\.\d+)?\b"
                if re.search(reference_pattern, line, re.IGNORECASE) or re.search(identifier_pattern, line):
                    findings.append({"rule": "reference-code-id", "path": rel, "line": number})
        if suffix in SOURCE_EXTENSIONS or path.name == "Dockerfile":
            first = content.splitlines()[0] if content.splitlines() else ""
            expected_license = "Apache-2.0" if rel.startswith("sdk/") else "MPL-2.0"
            if first != f"# SPDX-License-Identifier: {expected_license}":
                findings.append({"rule": "spdx-header", "path": rel, "line": 1})
        if suffix == ".py":
            try:
                compile(content, rel, "exec")
            except SyntaxError as exc:
                findings.append({"rule": "python-syntax", "path": rel, "line": exc.lineno or 0})

    waivers = manifest.get("waivers", [])
    for waiver in waivers:
        if waiver.get("rule") != "reference-code-id" or not waiver.get("reason"):
            findings.append({"rule": "invalid-waiver", "path": waiver.get("file", ""), "line": waiver.get("line", 0)})
    allowed = {(item["rule"], item["file"], int(item["line"])) for item in waivers}
    findings = [item for item in findings if (item["rule"], item["path"], int(item["line"])) not in allowed]
    return findings, hashes


def commit_findings(root: Path, owner_name: str | None, owner_email: str | None) -> list[dict[str, Any]]:
    git_dir = root / ".git"
    if not git_dir.exists():
        return []
    findings: list[dict[str, Any]] = []
    messages = subprocess.run(
        ["git", "log", "--format=%B%x00"], cwd=root, check=False, capture_output=True, text=True
    ).stdout
    if TRAILER_LABEL.lower() in messages.lower():
        findings.append({"rule": "history-trailer", "path": ".git", "line": 0})
    if owner_name and owner_email:
        identities = subprocess.run(
            ["git", "log", "--format=%an%x1f%ae%x1f%cn%x1f%ce"],
            cwd=root, check=False, capture_output=True, text=True,
        ).stdout.splitlines()
        expected = [owner_name, owner_email, owner_name, owner_email]
        for index, row in enumerate(identities, 1):
            if row.split("\x1f") != expected:
                findings.append({"rule": "history-identity", "path": ".git", "line": index})
    return findings


def run(root: Path, manifest_path: Path, report_path: Path, owner_name: str | None = None, owner_email: str | None = None) -> int:
    manifest = load_manifest(manifest_path)
    findings, hashes = scan_tree(root, manifest)
    findings.extend(commit_findings(root, owner_name, owner_email))
    report = {
        "schema": "grnd0.leak-gate.v1",
        "status": "green" if not findings else "failed",
        "finding_count": len(findings),
        "findings": findings,
        "file_sha256": hashes,
        "report_self_scan": "excluded",
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    if findings:
        print(json.dumps(report, indent=2, sort_keys=True))
        return 1
    print(f"leak gate green: {len(hashes)} scanned files")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--owner-name")
    parser.add_argument("--owner-email")
    args = parser.parse_args()
    root = args.root.resolve()
    manifest = args.manifest.resolve()
    report = (args.report or root / "artifacts" / "leak-gate-report.json").resolve()
    return run(root, manifest, report, args.owner_name, args.owner_email)


if __name__ == "__main__":
    raise SystemExit(main())
