"""Build step: turn the canonical SQLite DB into static senator JSON.

Reads ``etl/data/pegada.db`` (the schema is the only contract — no ``etl``
imports) and emits, under ``build/output/senadores/``:

- ``{id}.json`` — full per-senator detail (identity + current-state fields +
  party / office / name timelines) that drives the senator page;
- ``index.json`` — a slim, name-sorted array of cards for the directory page and
  in-browser search.

Mirrors ``build/deputados.py``. Identifiers/values are canonical English (see
``docs/glossario.md``); the site's display layer maps them to Portuguese.

Run with:

    python build/senadores.py
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


def build_senator(
    sen: sqlite3.Row,
    terms: List[sqlite3.Row],
    parties: List[sqlite3.Row],
    office_periods: List[sqlite3.Row],
    names: List[sqlite3.Row],
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Assemble one senator's (detail dict, index-card dict) from their rows."""
    parties_out = [
        {"party": p["party"], "start": p["start_at"], "end": p["end_at"]}
        for p in parties
    ]
    office_out = [
        {"condition": o["condition"], "start": o["start_at"], "end": o["end_at"],
         "legislature": o["legislature"], "cause": o["cause"]}
        for o in office_periods
    ]
    names_out = [
        {"name": n["name"], "start": n["start_at"], "end": n["end_at"]} for n in names
    ]

    current_status = sen["current_status"]
    in_office = current_status == "in_office"
    current_party = _current(parties_out, "party")
    # Condition: prefer the active office period, else fall back to the (latest) term
    # so a suplente who never assumed still shows as "alternate".
    current_condition = _current(office_out, "condition")
    if current_condition is None and terms:
        current_condition = terms[-1]["condition"]
    legislatures = [t["legislature"] for t in terms]  # ordered asc
    state = terms[-1]["state"] if terms else None

    detail = {
        "id": sen["id"],
        "name": sen["name"],
        "photo_url": sen["photo_url"],
        "state": state,
        "current_party": current_party,
        "current_condition": current_condition,
        "current_status": current_status,
        "in_office": in_office,
        "legislatures": legislatures,
        "terms": [{"legislature": t["legislature"], "state": t["state"],
                   "condition": t["condition"]} for t in terms],
        "parties": parties_out,
        "office_periods": office_out,
        "names": names_out,
    }
    card = {
        "id": sen["id"],
        "name": sen["name"],
        "photo_url": sen["photo_url"],
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
    """Generate per-senator detail files and the directory index."""
    conn = _connect(db_path)
    sen_dir = Path(out_dir) / "senadores"
    cards: List[Dict[str, Any]] = []
    try:
        for sen in conn.execute(
                "SELECT id, name, photo_url, current_status FROM senator").fetchall():
            sid = sen["id"]
            terms = conn.execute(
                "SELECT legislature, state, condition FROM senate_term "
                "WHERE senator_id=? ORDER BY legislature", (sid,)).fetchall()
            parties = conn.execute(
                "SELECT party, start_at, end_at FROM senator_party_affiliation "
                "WHERE senator_id=? ORDER BY start_at", (sid,)).fetchall()
            office_periods = conn.execute(
                "SELECT condition, start_at, end_at, legislature, cause "
                "FROM senator_office_period WHERE senator_id=? ORDER BY start_at",
                (sid,)).fetchall()
            names = conn.execute(
                "SELECT name, start_at, end_at FROM senator_name_history "
                "WHERE senator_id=? ORDER BY start_at", (sid,)).fetchall()

            detail, card = build_senator(sen, terms, parties, office_periods, names)
            _write_json(detail, sen_dir / f"{sid}.json")
            cards.append(card)
    finally:
        conn.close()

    cards.sort(key=lambda c: _sort_key(c["name"]))
    _write_json(cards, sen_dir / "index.json")

    counts = {
        "senators": len(cards),
        "in_office": sum(1 for c in cards if c["in_office"]),
        "no_status": sum(1 for c in cards if c["status"] is None),
    }
    print("build complete:", ", ".join(f"{k}={v}" for k, v in counts.items()))
    print(f"-> {sen_dir}")
    return counts


if __name__ == "__main__":
    run()
