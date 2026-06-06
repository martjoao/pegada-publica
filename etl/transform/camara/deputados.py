"""Transform step: raw Câmara landing files -> canonical deputy rows in SQLite.

Reads the roster (`extract.camara.deputados`) and per-deputy history
(`extract.camara.historico`) landing files, resolves identity (one row per
Câmara id, deduplicated across the duplicate roster rows and across terms),
folds each deputy's history into dated party_affiliation / office_period /
name_history intervals plus a current_status, and writes the canonical tables.

Identifiers are canonical English (see ``docs/glossario.md``); the PT->EN
translation happens here, at the DB-write boundary.

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

LEGISLATURES = (56, 57)

_TABLES_CHILD_FIRST = (
    "name_history",
    "party_affiliation",
    "office_period",
    "mandate",
    "source",
    "deputy",
)


def _read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_bio(
    deputy_ids: List[int],
    raw_base: Optional[Path] = None,
) -> Dict[int, Dict[str, Any]]:
    """Read raw bio landing files and return canonical bio fields keyed by deputy id.

    Deputies whose bio file does not exist are simply absent from the result;
    no exception is raised and no None entry is inserted.
    """
    result: Dict[int, Dict[str, Any]] = {}
    for dep_id in deputy_ids:
        path = paths.camara_bio_path(dep_id, base=raw_base)
        if not path.exists():
            continue
        dados = _read_json(path).get("dados", {}) or {}
        social_raw = dados.get("redeSocial") or []
        dod = dados.get("dataFalecimento") or None
        result[dep_id] = {
            "cpf": dados.get("cpf"),
            "civil_name": dados.get("nomeCivil"),
            "date_of_birth": dados.get("dataNascimento"),
            "date_of_death": dod if dod else None,
            "sex": dados.get("sexo"),
            "birth_state": dados.get("ufNascimento"),
            "birth_city": dados.get("municipioNascimento"),
            "education": dados.get("escolaridade"),
            "social_media": json.dumps(social_raw, ensure_ascii=False),
            "website": dados.get("urlWebsite"),
        }
    return result


def load_roster(
    raw_base: Optional[Path] = None,
    legislatures: Sequence[int] = LEGISLATURES,
) -> Tuple[Dict[int, Dict[str, Any]], Dict[Tuple[int, int], str], List[Dict[str, Any]]]:
    """Return (deputies-by-id, mandate-by-(id,legislature)->state, roster source metas).

    Collapses the duplicate roster rows (one per party / name variant) by id.
    """
    deputies: Dict[int, Dict[str, Any]] = {}
    mandates: Dict[Tuple[int, int], str] = {}
    metas: List[Dict[str, Any]] = []
    for legislature in legislatures:
        path = paths.camara_deputados_path(legislature, base=raw_base)
        if not path.exists():
            continue
        payload = _read_json(path)
        metas.append(payload.get("_meta", {}))
        for row in payload.get("dados", []) or []:
            dep_id = row["id"]
            deputies.setdefault(
                dep_id,
                {"name": row.get("nome"), "photo_url": row.get("urlFoto"),
                 "current_status": None},
            )
            mandates[(dep_id, row["idLegislatura"])] = row.get("siglaUf")
    return deputies, mandates, metas


def transform(
    conn: sqlite3.Connection,
    raw_base: Optional[Path] = None,
    legislatures: Sequence[int] = LEGISLATURES,
) -> Dict[str, int]:
    """Full rebuild of the canonical tables from the raw landing files."""
    for table in _TABLES_CHILD_FIRST:
        conn.execute(f"DELETE FROM {table}")

    deputies, mandates, roster_metas = load_roster(raw_base, legislatures)
    bios = load_bio(list(deputies.keys()), raw_base)

    office_rows: List[tuple] = []
    party_rows: List[tuple] = []
    name_rows: List[tuple] = []
    source_metas: List[Dict[str, Any]] = list(roster_metas)

    for dep_id in deputies:
        hist_path = paths.camara_historico_path(dep_id, base=raw_base)
        if not hist_path.exists():
            continue
        payload = _read_json(hist_path)
        source_metas.append(payload.get("_meta", {}))
        entries = payload.get("dados", []) or []

        names = intervals.name_history(entries)
        if names:
            deputies[dep_id]["name"] = names[-1]["name"]  # latest is current
        deputies[dep_id]["current_status"] = intervals.current_status(entries)

        for iv in intervals.office_periods(entries):
            office_rows.append(
                (dep_id, iv["legislature"], iv["condition"], iv["start"], iv["end"]))
        for iv in intervals.party_affiliations(entries):
            party_rows.append(
                (dep_id, iv["party"], iv["start"], iv["end"], iv["legislature"],
                 iv["source_note"]))
        for iv in names:
            name_rows.append((dep_id, iv["name"], iv["start"], iv["end"]))

    # parents before children (foreign keys are enforced)
    conn.executemany(
        "INSERT INTO deputy "
        "(id, name, photo_url, current_status, "
        " cpf, civil_name, date_of_birth, date_of_death, sex, "
        " birth_state, birth_city, education, social_media, website) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                dep_id, d["name"], d["photo_url"], d["current_status"],
                bios.get(dep_id, {}).get("cpf"),
                bios.get(dep_id, {}).get("civil_name"),
                bios.get(dep_id, {}).get("date_of_birth"),
                bios.get(dep_id, {}).get("date_of_death"),
                bios.get(dep_id, {}).get("sex"),
                bios.get(dep_id, {}).get("birth_state"),
                bios.get(dep_id, {}).get("birth_city"),
                bios.get(dep_id, {}).get("education"),
                bios.get(dep_id, {}).get("social_media"),
                bios.get(dep_id, {}).get("website"),
            )
            for dep_id, d in deputies.items()
        ],
    )
    conn.executemany(
        "INSERT INTO mandate (deputy_id, legislature, state) VALUES (?, ?, ?)",
        [(dep_id, leg, state) for (dep_id, leg), state in mandates.items()],
    )
    conn.executemany(
        "INSERT INTO office_period (deputy_id, legislature, condition, start_at, end_at) "
        "VALUES (?, ?, ?, ?, ?)",
        office_rows,
    )
    conn.executemany(
        "INSERT INTO party_affiliation "
        "(deputy_id, party, start_at, end_at, legislature, source_note) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        party_rows,
    )
    conn.executemany(
        "INSERT INTO name_history (deputy_id, name, start_at, end_at) VALUES (?, ?, ?, ?)",
        name_rows,
    )
    conn.executemany(
        "INSERT INTO source (source, endpoint, legislature, fetched_at, record_count) "
        "VALUES (?, ?, ?, ?, ?)",
        [(m.get("source"), m.get("endpoint"), m.get("legislatura"),
          m.get("fetched_at"), m.get("record_count")) for m in source_metas],
    )
    conn.commit()

    return {
        "deputy": len(deputies),
        "mandate": len(mandates),
        "office_period": len(office_rows),
        "party_affiliation": len(party_rows),
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
