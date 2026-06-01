"""Build step: turn the canonical SQLite DB into static deputy JSON.

Reads ``etl/data/pegada.db`` (the schema is the only contract — no ``etl``
imports) and emits, under ``build/output/deputados/``:

- ``{id}.json`` — full per-deputy detail (identity + current-state fields +
  party / exercise / name timelines) that drives the deputy page;
- ``index.json`` — a slim, name-sorted array of cards for the directory page and
  in-browser search.

Run with:

    python build/deputados.py        # or  python -m deputados  from inside build/
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


def _sort_key(nome: str) -> str:
    """Accent-insensitive, case-insensitive key so ordering is a sensible A–Z."""
    stripped = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode()
    return stripped.casefold()


def _current_party(partidos: List[Dict[str, Any]]) -> Optional[str]:
    """The open affiliation if any, else the most recent one."""
    for p in reversed(partidos):  # partidos are ordered by start_at
        if p["fim"] is None:
            return p["sigla"]
    return partidos[-1]["sigla"] if partidos else None


def _current_status(exercicios: List[Dict[str, Any]]) -> Tuple[bool, Optional[str], Optional[str]]:
    """Return (em_exercicio, condicao_atual, status_atual) from exercise intervals."""
    open_intervals = [e for e in exercicios if e["fim"] is None]
    if open_intervals:
        return True, open_intervals[-1]["condicao"], "em_exercicio"
    if not exercicios:
        return False, None, None
    last_condicao = exercicios[-1]["condicao"]  # ordered by start_at
    status = {"Titular": "licenciado", "Suplente": "suplente"}.get(last_condicao)
    return False, None, status


def build_deputy(
    dep: sqlite3.Row,
    mandatos: List[sqlite3.Row],
    partidos: List[sqlite3.Row],
    exercicios: List[sqlite3.Row],
    nomes: List[sqlite3.Row],
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Assemble one deputy's (detail dict, index-card dict) from their rows."""
    partidos_out = [
        {"sigla": p["sigla_partido"], "inicio": p["start_at"], "fim": p["end_at"],
         "legislatura": p["legislatura"]}
        for p in partidos
    ]
    exercicio_out = [
        {"condicao": e["condicao"], "inicio": e["start_at"], "fim": e["end_at"],
         "legislatura": e["legislatura"]}
        for e in exercicios
    ]
    nomes_out = [
        {"nome": n["nome"], "inicio": n["start_at"], "fim": n["end_at"]} for n in nomes
    ]

    em_exercicio, condicao_atual, status_atual = _current_status(exercicio_out)
    partido_atual = _current_party(partidos_out)
    legislaturas = [m["legislatura"] for m in mandatos]  # ordered asc
    uf = mandatos[-1]["uf"] if mandatos else None

    detail = {
        "id": dep["id"],
        "nome": dep["nome"],
        "foto_url": dep["foto_url"],
        "uf": uf,
        "partido_atual": partido_atual,
        "condicao_atual": condicao_atual,
        "status_atual": status_atual,
        "em_exercicio": em_exercicio,
        "legislaturas": legislaturas,
        "mandatos": [{"legislatura": m["legislatura"], "uf": m["uf"]} for m in mandatos],
        "partidos": partidos_out,
        "exercicio": exercicio_out,
        "nomes": nomes_out,
    }
    card = {
        "id": dep["id"],
        "nome": dep["nome"],
        "partido": partido_atual,
        "uf": uf,
        "status": status_atual,
        "condicao": condicao_atual,
        "em_exercicio": em_exercicio,
        "legislaturas": legislaturas,
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
        for dep in conn.execute("SELECT id, nome, foto_url FROM deputado").fetchall():
            dep_id = dep["id"]
            mandatos = conn.execute(
                "SELECT legislatura, uf FROM mandato WHERE deputy_id=? ORDER BY legislatura",
                (dep_id,)).fetchall()
            partidos = conn.execute(
                "SELECT sigla_partido, start_at, end_at, legislatura FROM party_membership "
                "WHERE deputy_id=? ORDER BY start_at", (dep_id,)).fetchall()
            exercicios = conn.execute(
                "SELECT condicao, start_at, end_at, legislatura FROM exercicio "
                "WHERE deputy_id=? ORDER BY start_at", (dep_id,)).fetchall()
            nomes = conn.execute(
                "SELECT nome, start_at, end_at FROM name_history "
                "WHERE deputy_id=? ORDER BY start_at", (dep_id,)).fetchall()

            detail, card = build_deputy(dep, mandatos, partidos, exercicios, nomes)
            _write_json(detail, dep_dir / f"{dep_id}.json")
            cards.append(card)
    finally:
        conn.close()

    cards.sort(key=lambda c: _sort_key(c["nome"]))
    _write_json(cards, dep_dir / "index.json")

    counts = {
        "deputados": len(cards),
        "em_exercicio": sum(1 for c in cards if c["em_exercicio"]),
        "sem_historico": sum(1 for c in cards if c["status"] is None),
    }
    print("build complete:", ", ".join(f"{k}={v}" for k, v in counts.items()))
    print(f"-> {dep_dir}")
    return counts


if __name__ == "__main__":
    run()
