"""Build step: generate donors_ranking.json from pegada.db.

Ranks all donors by total campaign donation amount across all election years
and emits the top 500 with their full recipient list.

Run with:
    python build/doadores.py
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = REPO_ROOT / "etl" / "data" / "pegada.db"
DEFAULT_OUT = REPO_ROOT / "build" / "output"
TOP_N = 500


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def _write_json(obj: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def run(db_path: Path = DEFAULT_DB, out_dir: Path = DEFAULT_OUT) -> Dict[str, int]:
    """Generate donors_ranking.json."""
    conn = _connect(db_path)
    try:
        total_donors = conn.execute("SELECT COUNT(*) FROM donor").fetchone()[0]

        top_donors = conn.execute(
            """
            SELECT d.id, d.name, d.city, d.state, d.donor_type,
                   SUM(td.amount) AS total_amount
            FROM donor d
            JOIN tse_donation td ON td.donor_id = d.id
            GROUP BY d.id
            ORDER BY total_amount DESC
            LIMIT ?
            """,
            (TOP_N,),
        ).fetchall()

        donors_out: List[Dict[str, Any]] = []
        for rank, donor in enumerate(top_donors, 1):
            donations = conn.execute(
                """
                SELECT td.election_year, td.amount,
                       tc.name AS candidate_name, tc.party, tc.state,
                       tc.office, tc.election_result,
                       tc.deputy_id, tc.senator_id
                FROM tse_donation td
                JOIN tse_candidate tc ON tc.id = td.tse_candidate_id
                WHERE td.donor_id = ?
                ORDER BY td.amount DESC
                """,
                (donor["id"],),
            ).fetchall()

            donations_out = []
            for d in donations:
                entry: Dict[str, Any] = {
                    "election_year": d["election_year"],
                    "candidate_name": d["candidate_name"],
                    "party": d["party"],
                    "state": d["state"],
                    "office": d["office"],
                    "election_result": d["election_result"],
                    "amount": d["amount"],
                }
                if d["deputy_id"] is not None:
                    entry["deputy_id"] = d["deputy_id"]
                if d["senator_id"] is not None:
                    entry["senator_id"] = d["senator_id"]
                donations_out.append(entry)

            donors_out.append({
                "rank": rank,
                "name": donor["name"],
                "city": donor["city"],
                "state": donor["state"],
                "donor_type": donor["donor_type"],
                "total_amount": donor["total_amount"],
                "donations": donations_out,
            })

        result = {
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "total_donors": total_donors,
            "donors": donors_out,
        }
        _write_json(result, Path(out_dir) / "donors_ranking.json")
        print(f"build complete: donors={len(donors_out)}, total_donors={total_donors}")
        print(f"-> {Path(out_dir) / 'donors_ranking.json'}")
        return {"donors": len(donors_out), "total_donors": total_donors}
    finally:
        conn.close()


if __name__ == "__main__":
    run()
