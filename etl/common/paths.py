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


def camara_bio_path(deputy_id: int, base: Optional[Path] = None) -> Path:
    """Return the raw landing file path for one deputy's bio detail."""
    base = base if base is not None else DATA_RAW
    return base / "camara" / "bio" / f"{deputy_id}.json"


def senado_bio_path(codigo: int, base: Optional[Path] = None) -> Path:
    """Return the raw landing file path for one senator's bio detail."""
    base = base if base is not None else DATA_RAW
    return base / "senado" / "bio" / f"{codigo}.json"


def db_path(base: Optional[Path] = None) -> Path:
    """Return the canonical SQLite DB path (the transform/load system-of-record)."""
    base = base if base is not None else DATA
    return base / "pegada.db"


def tse_receitas_zip_path(year: int, base: Optional[Path] = None) -> Path:
    """Return the raw landing file path for a given year's receitas_candidatos ZIP."""
    base = base if base is not None else DATA_RAW
    return base / "tse" / "receitas" / f"{year}.zip"


def tse_receitas_manifest_path(year: int, base: Optional[Path] = None) -> Path:
    """Return the manifest JSON path for a given year's receitas ZIP."""
    base = base if base is not None else DATA_RAW
    return base / "tse" / "receitas" / f"{year}_manifest.json"


def tse_candidatos_zip_path(year: int, base: Optional[Path] = None) -> Path:
    """Return the raw landing file path for a given year's consulta_cand ZIP."""
    base = base if base is not None else DATA_RAW
    return base / "tse" / "candidatos" / f"{year}.zip"


def tse_candidatos_manifest_path(year: int, base: Optional[Path] = None) -> Path:
    """Return the manifest JSON path for a given year's candidatos ZIP."""
    base = base if base is not None else DATA_RAW
    return base / "tse" / "candidatos" / f"{year}_manifest.json"
