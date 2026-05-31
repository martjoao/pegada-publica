"""Single source of truth for where ETL raw landing files live on disk.

Resolving paths here (rather than scattering string joins across source
modules) keeps the ``data/raw/...`` layout consistent and lets scripts run
regardless of the current working directory.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

# etl/common/paths.py -> the etl/ stage dir is two parents up.
ETL_ROOT = Path(__file__).resolve().parent.parent
DATA_RAW = ETL_ROOT / "data" / "raw"


def camara_deputados_path(legislatura: int, base: Optional[Path] = None) -> Path:
    """Return the raw landing file path for a given legislatura's deputy roster."""
    base = base if base is not None else DATA_RAW
    return base / "camara" / "deputados" / f"legislatura-{legislatura}.json"
