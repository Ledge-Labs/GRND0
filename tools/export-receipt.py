# SPDX-License-Identifier: MPL-2.0
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any


SENSITIVE_KEY = re.compile(r"(?:api.?key|token|secret|password|authorization|credential)", re.IGNORECASE)
WINDOWS_PATH = re.compile(r"[A-Za-z]:[\\/][^\s\"']+")
POSIX_PRIVATE_PATH = re.compile(r"/(?:Users|home)/[^\s\"']+")
IP_ADDRESS = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")
EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)


def redact(value: Any, key: str = "") -> Any:
    if SENSITIVE_KEY.search(key):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {item_key: redact(item_value, str(item_key)) for item_key, item_value in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str):
        value = WINDOWS_PATH.sub("[REDACTED_PATH]", value)
        value = POSIX_PRIVATE_PATH.sub("[REDACTED_PATH]", value)
        value = IP_ADDRESS.sub("[REDACTED_ADDRESS]", value)
        value = EMAIL.sub("[REDACTED_EMAIL]", value)
    return value


def main() -> int:
    if len(sys.argv) != 3:
        raise SystemExit("usage: export-receipt.py INPUT OUTPUT")
    source = Path(sys.argv[1])
    destination = Path(sys.argv[2])
    payload = json.loads(source.read_text(encoding="utf-8"))
    rendered = json.dumps(redact(payload), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    destination.write_text(rendered, encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
