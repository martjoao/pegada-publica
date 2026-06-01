"""Build step: turn the canonical SQLite DB into static deputy JSON.

Reads ``etl/data/pegada.db`` (the schema is the only contract — no ``etl``
imports) and emits, under ``build/output/deputados/``:

- ``{id}.json`` — full per-deputy detail (identity + current-state fields +
  party / office / name timelines) that drives the deputy page;
- ``index.json`` — a slim, name-sorted array of cards for the directory page and
  in-browser search.

Identifiers/values are canonical English (see ``docs/glossario.md``); the site's
display layer maps them to Portuguese.

Run with:

    python build/deputados.py
"""
from __future__ import annotations

import json
import sqlite3
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = REPO_ROOT / "etl" / "data" / "pegada.db"
DEFAULT_OUT = REPO_ROOT / "build" / "output"


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def _sort_key(name: str) -> str:
    """Accent-insensitive, case-insensitive key so ordering is a sensible A–Z."""
    stripped = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return stripped.casefold()


def _current(intervals: List[Dict[str, Any]], field: str) -> Optional[Any]:
    """The value of ``field`` on the open interval if any, else the most recent."""
    for iv in reversed(intervals):  # intervals are ordered by start
        if iv["end"] is None:
            return iv[field]
    return intervals[-1][field] if intervals else None


def build_deputy(
    dep: sqlite3.Row,
    mandates: List[sqlite3.Row],
    parties: List[sqlite3.Row],
    office_periods: List[sqlite3.Row],
    names: List[sqlite3.Row],
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Assemble one deputy's (detail dict, index-card dict) from their rows."""
    parties_out = [
        {"party": p["party"], "start": p["start_at"], "end": p["end_at"],
         "legislature": p["legislature"]}
        for p in parties
    ]
    office_out = [
        {"condition": o["condition"], "start": o["start_at"], "end": o["end_at"],
         "legislature": o["legislature"]}
        for o in office_periods
    ]
    names_out = [
        {"name": n["name"], "start": n["start_at"], "end": n["end_at"]} for n in names
    ]

    current_status = dep["current_status"]
    in_office = current_status == "in_office"
    current_party = _current(parties_out, "party")
    current_condition = _current(office_out, "condition")
    legislatures = [m["legislature"] for m in mandates]  # ordered asc
    state = mandates[-1]["state"] if mandates else None

    detail = {
        "id": dep["id"],
        "name": dep["name"],
        "photo_url": dep["photo_url"],
        "state": state,
        "current_party": current_party,
        "current_condition": current_condition,
        "current_status": current_status,
        "in_office": in_office,
        "legislatures": legislatures,
        "mandates": [{"legislature": m["legislature"], "state": m["state"]} for m in mandates],
        "parties": parties_out,
        "office_periods": office_out,
        "names": names_out,
    }
    card = {
        "id": dep["id"],
        "name": dep["name"],
        "photo_url": dep["photo_url"],
        "party": current_party,
        "state": state,
        "status": current_status,
        "condition": current_condition,
        "in_office": in_office,
        "legislatures": legislatures,
    }
    return detail, card


def _write_json(obj: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def run(db_path: Path = DEFAULT_DB, out_dir: Path = DEFAULT_OUT) -> Dict[str, int]:
    """Generate per-deputy detail files and the directory index."""
    conn = _connect(db_path)
    dep_dir = Path(out_dir) / "deputados"
    cards: List[Dict[str, Any]] = []
    try:
        for dep in conn.execute(
                "SELECT id, name, photo_url, current_status FROM deputy").fetchall():
            dep_id = dep["id"]
            mandates = conn.execute(
                "SELECT legislature, state FROM mandate WHERE deputy_id=? ORDER BY legislature",
                (dep_id,)).fetchall()
            parties = conn.execute(
                "SELECT party, start_at, end_at, legislature FROM party_affiliation "
                "WHERE deputy_id=? ORDER BY start_at", (dep_id,)).fetchall()
            office_periods = conn.execute(
                "SELECT condition, start_at, end_at, legislature FROM office_period "
                "WHERE deputy_id=? ORDER BY start_at", (dep_id,)).fetchall()
            names = conn.execute(
                "SELECT name, start_at, end_at FROM name_history "
                "WHERE deputy_id=? ORDER BY start_at", (dep_id,)).fetchall()

            detail, card = build_deputy(dep, mandates, parties, office_periods, names)
            _write_json(detail, dep_dir / f"{dep_id}.json")
            cards.append(card)
    finally:
        conn.close()

    cards.sort(key=lambda c: _sort_key(c["name"]))
    _write_json(cards, dep_dir / "index.json")

    counts = {
        "deputies": len(cards),
        "in_office": sum(1 for c in cards if c["in_office"]),
        "no_status": sum(1 for c in cards if c["status"] is None),
    }
    print("build complete:", ", ".join(f"{k}={v}" for k, v in counts.items()))
    print(f"-> {dep_dir}")
    return counts


if __name__ == "__main__":
    run()
