"""Transform step: raw Câmara landing files -> canonical deputy rows in SQLite.

Reads the roster (`extract.camara.deputados`) and per-deputy history
(`extract.camara.historico`) landing files, resolves identity (one row per
Câmara id, deduplicated across the duplicate roster rows and across terms),
folds each deputy's history into dated party / exercise / name intervals, and
writes the six canonical tables.

Run with:

    python -m transform.camara.deputados
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from common import paths
from transform import db as txdb
from transform import intervals

LEGISLATURAS = (56, 57)

_TABLES_CHILD_FIRST = (
    "name_history",
    "party_membership",
    "exercicio",
    "mandato",
    "source_meta",
    "deputado",
)


def _read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_roster(
    raw_base: Optional[Path] = None,
    legislaturas: Sequence[int] = LEGISLATURAS,
) -> Tuple[Dict[int, Dict[str, Any]], Dict[Tuple[int, int], str], List[Dict[str, Any]]]:
    """Return (deputados-by-id, mandato-by-(id,leg)-uf, roster source metas).

    Collapses the duplicate roster rows (one per party / name variant) by id.
    """
    deputados: Dict[int, Dict[str, Any]] = {}
    mandatos: Dict[Tuple[int, int], str] = {}
    metas: List[Dict[str, Any]] = []
    for legislatura in legislaturas:
        path = paths.camara_deputados_path(legislatura, base=raw_base)
        if not path.exists():
            continue
        payload = _read_json(path)
        metas.append(payload.get("_meta", {}))
        for row in payload.get("dados", []) or []:
            dep_id = row["id"]
            deputados.setdefault(dep_id, {"nome": row.get("nome"), "foto_url": row.get("urlFoto")})
            mandatos[(dep_id, row["idLegislatura"])] = row.get("siglaUf")
    return deputados, mandatos, metas


def transform(
    conn: sqlite3.Connection,
    raw_base: Optional[Path] = None,
    legislaturas: Sequence[int] = LEGISLATURAS,
) -> Dict[str, int]:
    """Full rebuild of the canonical tables from the raw landing files."""
    for table in _TABLES_CHILD_FIRST:
        conn.execute(f"DELETE FROM {table}")

    deputados, mandatos, roster_metas = load_roster(raw_base, legislaturas)

    exercicio_rows: List[tuple] = []
    party_rows: List[tuple] = []
    name_rows: List[tuple] = []
    source_metas: List[Dict[str, Any]] = list(roster_metas)

    for dep_id in deputados:
        hist_path = paths.camara_historico_path(dep_id, base=raw_base)
        if not hist_path.exists():
            continue
        payload = _read_json(hist_path)
        source_metas.append(payload.get("_meta", {}))
        entries = payload.get("dados", []) or []

        names = intervals.name_intervals(entries)
        if names:
            deputados[dep_id]["nome"] = names[-1]["nome"]  # latest is current

        for iv in intervals.exercise_intervals(entries):
            exercicio_rows.append(
                (dep_id, iv["legislatura"], iv["condicao"], iv["start_at"], iv["end_at"]))
        for iv in intervals.party_intervals(entries):
            party_rows.append(
                (dep_id, iv["sigla_partido"], iv["start_at"], iv["end_at"],
                 iv["legislatura"], iv["descricao_origem"]))
        for iv in names:
            name_rows.append((dep_id, iv["nome"], iv["start_at"], iv["end_at"]))

    # parents before children (foreign keys are enforced)
    conn.executemany(
        "INSERT INTO deputado (id, nome, foto_url) VALUES (?, ?, ?)",
        [(dep_id, d["nome"], d["foto_url"]) for dep_id, d in deputados.items()],
    )
    conn.executemany(
        "INSERT INTO mandato (deputy_id, legislatura, uf) VALUES (?, ?, ?)",
        [(dep_id, leg, uf) for (dep_id, leg), uf in mandatos.items()],
    )
    conn.executemany(
        "INSERT INTO exercicio (deputy_id, legislatura, condicao, start_at, end_at) "
        "VALUES (?, ?, ?, ?, ?)",
        exercicio_rows,
    )
    conn.executemany(
        "INSERT INTO party_membership "
        "(deputy_id, sigla_partido, start_at, end_at, legislatura, descricao_origem) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        party_rows,
    )
    conn.executemany(
        "INSERT INTO name_history (deputy_id, nome, start_at, end_at) VALUES (?, ?, ?, ?)",
        name_rows,
    )
    conn.executemany(
        "INSERT INTO source_meta (source, endpoint, legislatura, fetched_at, record_count) "
        "VALUES (?, ?, ?, ?, ?)",
        [(m.get("source"), m.get("endpoint"), m.get("legislatura"),
          m.get("fetched_at"), m.get("record_count")) for m in source_metas],
    )
    conn.commit()

    return {
        "deputado": len(deputados),
        "mandato": len(mandatos),
        "exercicio": len(exercicio_rows),
        "party_membership": len(party_rows),
        "name_history": len(name_rows),
    }


def run(db_path: Optional[Path] = None, raw_base: Optional[Path] = None) -> Dict[str, int]:
    """Connect, (re)create the schema, and transform. Returns row counts."""
    db_path = db_path or paths.db_path()
    conn = txdb.connect(db_path)
    try:
        txdb.create_schema(conn)
        counts = transform(conn, raw_base=raw_base)
    finally:
        conn.close()
    print("transform complete:", ", ".join(f"{k}={v}" for k, v in counts.items()))
    print(f"-> {db_path}")
    return counts


if __name__ == "__main__":
    run()
