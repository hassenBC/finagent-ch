"""On-disk JSON cache for LLM responses, keyed by a sha256 of the request."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any


def request_key(**request: Any) -> str:
    blob = json.dumps(request, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


class DiskCache:
    def __init__(self, root: str | Path):
        self.root = Path(root)

    def _path(self, key: str) -> Path:
        return self.root / key[:2] / f"{key}.json"

    def get(self, key: str) -> dict[str, Any] | None:
        path = self._path(key)
        if not path.exists():
            return None
        return json.loads(path.read_text())

    def set(self, key: str, value: dict[str, Any]) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(value, ensure_ascii=False))
        os.replace(tmp, path)  # atomic: parallel eval workers never read half a file
