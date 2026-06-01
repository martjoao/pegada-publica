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
DATA = ETL_ROOT / "data"
DATA_RAW = DATA / "raw"
DB_PATH = DATA / "pegada.db"


def camara_deputados_path(legislatura: int, base: Optional[Path] = None) -> Path:
    """Return the raw landing file path for a given legislatura's deputy roster."""
    base = base if base is not None else DATA_RAW
    return base / "camara" / "deputados" / f"legislatura-{legislatura}.json"


def camara_historico_path(deputy_id: int, base: Optional[Path] = None) -> Path:
    """Return the raw landing file path for one deputy's full history."""
    base = base if base is not None else DATA_RAW
    return base / "camara" / "historico" / f"{deputy_id}.json"


def senado_lista_path(legislatura: int, base: Optional[Path] = None) -> Path:
    """Return the raw landing file path for a legislatura's senator roster."""
    base = base if base is not None else DATA_RAW
    return base / "senado" / "lista" / f"legislatura-{legislatura}.json"


def senado_mandatos_path(codigo: int, base: Optional[Path] = None) -> Path:
    """Return the raw landing file path for one senator's mandates."""
    base = base if base is not None else DATA_RAW
    return base / "senado" / "mandatos" / f"{codigo}.json"


def senado_filiacoes_path(codigo: int, base: Optional[Path] = None) -> Path:
    """Return the raw landing file path for one senator's party affiliations."""
    base = base if base is not None else DATA_RAW
    return base / "senado" / "filiacoes" / f"{codigo}.json"


def db_path(base: Optional[Path] = None) -> Path:
    """Return the canonical SQLite DB path (the transform/load system-of-record)."""
    base = base if base is not None else DATA
    return base / "pegada.db"
