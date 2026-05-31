"""Small JSON file helper shared across ETL phases.

Atomic writes (temp file + ``os.replace``) mean a crash mid-write never leaves a
half-written file behind — important for landing files that downstream steps read.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def write_json_atomic(obj: Any, path: Path, *, indent: int = 2) -> None:
    """Write ``obj`` as UTF-8 JSON to ``path`` atomically, creating parents."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=indent)
    os.replace(tmp, path)
