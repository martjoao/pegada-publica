"""Transform step: raw Senado landing files -> canonical senator rows in SQLite.

Reads the roster (`extract.senado.lista`) and per-senator mandates + party
affiliations (`extract.senado.detalhe`) landing files, resolves identity (one row
per CodigoParlamentar, deduplicated across the two overlapping legislature rosters),
maps each senator's mandates/exercicios/filiacoes into dated
senator_party_affiliation / senator_office_period / senate_term intervals plus a
derived current_status, and writes the canonical senator tables.

Identifiers/values are canonical English (see ``docs/glossario.md``); the PT->EN
translation happens here, at the DB-write boundary. The deputy tables are not
touched (parallel-tables design, decision 019).

Run with:

    python -m transform.senado.senadores
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from common import paths
from common.senado_json import as_list, unwrap
from transform import db as txdb
from transform import senado_intervals as si

LEGISLATURES = (56, 57)

_TABLES_CHILD_FIRST = (
    "senator_name_history",
    "senator_party_affiliation",
    "senator_office_period",
    "senate_term",
    "senator",
)


def _read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_roster(
    raw_base: Optional[Path] = None,
    legislatures: Sequence[int] = LEGISLATURES,
):
    """Return (senators-by-id, roster source metas).

    Collapses the overlapping legislature rosters by CodigoParlamentar (a senate
    mandate appears in both its legislatures' lists).
    """
    senators: Dict[int, Dict[str, Any]] = {}
    metas: List[Dict[str, Any]] = []
    for legislature in legislatures:
        path = paths.senado_lista_path(legislature, base=raw_base)
        if not path.exists():
            continue
        payload = _read_json(path)
        metas.append(payload.get("_meta", {}))
        for row in payload.get("dados", []) or []:
            ident = row["IdentificacaoParlamentar"]
            sid = int(ident["CodigoParlamentar"])
            senators.setdefault(sid, {
                "name": ident.get("NomeParlamentar"),
                "photo_url": ident.get("UrlFotoParlamentar"),
                "current_status": None,
            })
    return senators, metas


def _mandatos_for(sid: int, raw_base: Optional[Path]) -> List[Dict[str, Any]]:
    path = paths.senado_mandatos_path(sid, base=raw_base)
    if not path.exists():
        return []
    payload = _read_json(path)
    node = unwrap(payload, "dados", "MandatoParlamentar", "Parlamentar", "Mandatos", "Mandato")
    return as_list(node)


def _filiacoes_for(sid: int, raw_base: Optional[Path]) -> List[Dict[str, Any]]:
    path = paths.senado_filiacoes_path(sid, base=raw_base)
    if not path.exists():
        return []
    payload = _read_json(path)
    node = unwrap(payload, "dados", "FiliacaoParlamentar", "Parlamentar", "Filiacoes", "Filiacao")
    return as_list(node)


def transform(
    conn: sqlite3.Connection,
    raw_base: Optional[Path] = None,
    legislatures: Sequence[int] = LEGISLATURES,
    today: Optional[str] = None,
) -> Dict[str, int]:
    """Full rebuild of the canonical senator tables from the raw landing files."""
    for table in _TABLES_CHILD_FIRST:
        conn.execute(f"DELETE FROM {table}")

    senators, roster_metas = load_roster(raw_base, legislatures)

    term_rows: List[tuple] = []
    office_rows: List[tuple] = []
    party_rows: List[tuple] = []
    name_rows: List[tuple] = []
    source_metas: List[Dict[str, Any]] = list(roster_metas)

    for sid, sen in senators.items():
        mandatos = _mandatos_for(sid, raw_base)
        filiacoes = _filiacoes_for(sid, raw_base)

        sen["current_status"] = si.current_status(mandatos, today=today)

        for t in si.senate_terms(mandatos):
            term_rows.append((sid, t["legislature"], t["state"], t["condition"]))
        for iv in si.office_periods(mandatos, today=today):
            office_rows.append(
                (sid, iv["legislature"], iv["condition"], iv["start"], iv["end"], iv["cause"]))
        for iv in si.party_affiliations(filiacoes):
            party_rows.append((sid, iv["party"], iv["start"], iv["end"], iv["source_note"]))
        # Name history degenerates to a single open interval from the roster name
        # (the Senado does not expose dated parliamentary-name changes here).
        name_rows.append((sid, sen["name"], "1900-01-01", None))

    conn.executemany(
        "INSERT INTO senator (id, name, photo_url, current_status) VALUES (?, ?, ?, ?)",
        [(sid, s["name"], s["photo_url"], s["current_status"]) for sid, s in senators.items()],
    )
    conn.executemany(
        "INSERT INTO senate_term (senator_id, legislature, state, condition) "
        "VALUES (?, ?, ?, ?)", term_rows,
    )
    conn.executemany(
        "INSERT INTO senator_office_period "
        "(senator_id, legislature, condition, start_at, end_at, cause) "
        "VALUES (?, ?, ?, ?, ?, ?)", office_rows,
    )
    conn.executemany(
        "INSERT INTO senator_party_affiliation "
        "(senator_id, party, start_at, end_at, source_note) VALUES (?, ?, ?, ?, ?)",
        party_rows,
    )
    conn.executemany(
        "INSERT INTO senator_name_history (senator_id, name, start_at, end_at) "
        "VALUES (?, ?, ?, ?)", name_rows,
    )
    conn.executemany(
        "INSERT INTO source (source, endpoint, legislature, fetched_at, record_count) "
        "VALUES (?, ?, ?, ?, ?)",
        [(m.get("source"), m.get("endpoint"), m.get("legislatura"),
          m.get("fetched_at"), m.get("record_count")) for m in source_metas],
    )
    conn.commit()

    return {
        "senator": len(senators),
        "senate_term": len(term_rows),
        "senator_office_period": len(office_rows),
        "senator_party_affiliation": len(party_rows),
        "senator_name_history": len(name_rows),
    }


def run(db_path: Optional[Path] = None, raw_base: Optional[Path] = None) -> Dict[str, int]:
    """Connect, transform senators (deputy tables untouched). Returns row counts.

    NOTE: unlike the deputy orchestrator this does **not** recreate the schema, so it
    can run after the deputy transform without dropping deputy data. Run the deputy
    transform first (it creates all tables); then this fills the senator tables.
    """
    db_path = db_path or paths.db_path()
    conn = txdb.connect(db_path)
    try:
        counts = transform(conn, raw_base=raw_base)
    finally:
        conn.close()
    print("senator transform complete:", ", ".join(f"{k}={v}" for k, v in counts.items()))
    print(f"-> {db_path}")
    return counts


if __name__ == "__main__":
    run()
