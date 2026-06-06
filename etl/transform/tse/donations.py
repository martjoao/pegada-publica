"""Transform step: TSE candidates + donations -> canonical DB tables.

Reads locally-downloaded TSE bulk ZIPs (consulta_cand + receitas_candidatos
for 2018 and 2022) and writes tse_candidate, donor, and tse_donation tables
to pegada.db. Also backfills senator.cpf from TSE candidate data.

Run with:
    python -m transform.tse.donations
"""
from __future__ import annotations

import csv
import io
import logging
import re
import sqlite3
import unicodedata
import zipfile
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from common import paths
from transform import db as txdb

ELECTIONS = (2018, 2022)
FEDERAL_CARGOS = frozenset({"DEPUTADO FEDERAL", "SENADOR", "PRESIDENTE"})
ENCODING = "latin-1"

log = logging.getLogger(__name__)

# ── Canonicalization helpers ──────────────────────────────────────────────────

_OFFICE_MAP: Dict[str, str] = {
    "DEPUTADO FEDERAL": "federal_deputy",
    "SENADOR": "senator",
    "PRESIDENTE": "president",
}

_ELECTION_RESULT_MAP: Dict[str, str] = {
    "ELEITO": "elected",
    "ELEITO POR QP": "elected",
    "ELEITO POR MÉDIA": "elected",
    "ELEITO NO 2º TURNO": "elected",
    "NÃO ELEITO": "not_elected",
    "NÃO ELEITO (REJEIÇÃO DE CONTAS)": "not_elected",
    "SUPLENTE": "alternate",
    "CASSADO": "invalidated",
    "DIPLOMA CASSADO": "invalidated",
    "RENÚNCIA": "withdrew",
    "FALECIDO": "withdrew",
    "2º TURNO": "pending",
}

_FUNDING_SOURCE_MAP: Dict[str, str] = {
    "DOAÇÕES DE PESSOAS FÍSICAS": "individual_donation",
    "RECURSOS DO PRÓPRIO CANDIDATO": "self_funding",
    "DOAÇÕES DE PARTIDO": "party_transfer",
    "TRANSFERÊNCIAS DO PARTIDO": "party_transfer",
    "FUNDO ESPECIAL DE FINANCIAMENTO DE CAMPANHA": "electoral_fund",
    "FUNDO PARTIDÁRIO": "party_fund",
    "RECURSOS DE OUTROS CANDIDATOS": "candidate_transfer",
}

_BRASIL_RE = re.compile(r"receitas_candidatos_\d{4}_brasil\.csv", re.IGNORECASE)


def canonicalize_office(ds_cargo: str) -> str:
    key = ds_cargo.strip().upper()
    if key not in _OFFICE_MAP:
        raise ValueError(f"Unknown DS_CARGO: {ds_cargo!r}")
    return _OFFICE_MAP[key]


def canonicalize_election_result(ds_sit: str) -> Optional[str]:
    return _ELECTION_RESULT_MAP.get(ds_sit.strip().upper())


def canonicalize_funding_source(ds_fonte: str) -> str:
    key = ds_fonte.strip().upper()
    result = _FUNDING_SOURCE_MAP.get(key)
    if result is None:
        log.warning("Unknown DS_FONTE_RECEITA: %r — mapped to 'other'", ds_fonte)
        return "other"
    return result


def parse_br_decimal(value: str) -> float:
    """Convert Brazilian decimal string '1.234,56' to float 1234.56."""
    return float(value.strip().replace(".", "").replace(",", "."))


def infer_donor_type(cpf_cnpj: Optional[str]) -> str:
    if not cpf_cnpj:
        return "party"
    digits = re.sub(r"\D", "", cpf_cnpj)
    if len(digits) == 11:
        return "individual"
    if len(digits) == 14:
        return "company"
    return "unknown"


def _normalize_name(name: str) -> str:
    """Uppercase, strip accents and punctuation for name matching."""
    nfkd = unicodedata.normalize("NFKD", name.upper())
    ascii_str = nfkd.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^A-Z\s]", "", ascii_str).strip()


def _parse_br_date(date_str: str) -> Optional[str]:
    """Convert DD/MM/YYYY to ISO-8601 YYYY-MM-DD, or None if blank."""
    s = date_str.strip()
    if not s:
        return None
    parts = s.split("/")
    if len(parts) == 3:
        return f"{parts[2]}-{parts[1]}-{parts[0]}"
    return None


# ── Pipeline steps ────────────────────────────────────────────────────────────

def load_candidates(
    conn: sqlite3.Connection,
    years: Sequence[int] = ELECTIONS,
    base: Optional[Path] = None,
) -> None:
    """Load tse_candidate rows from consulta_cand ZIPs (one per year).

    Deduplicates to one row per (year, tse_seq) taking the highest NR_TURNO,
    so a presidential candidate who reaches round 2 gets their final result.
    """
    for year in years:
        zip_path = paths.tse_candidatos_zip_path(year, base=base)
        with zipfile.ZipFile(zip_path) as zf:
            csv_names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
            # Accumulate best-round row per tse_seq within this year
            best: Dict[int, dict] = {}
            for name in csv_names:
                with zf.open(name) as raw:
                    text = io.TextIOWrapper(raw, encoding=ENCODING)
                    reader = csv.DictReader(text, delimiter=";")
                    for row in reader:
                        if row["DS_CARGO"].strip().upper() not in FEDERAL_CARGOS:
                            continue
                        seq = int(row["SQ_CANDIDATO"])
                        turno = int(row["NR_TURNO"])
                        existing = best.get(seq)
                        if existing is None or turno > existing["_turno"]:
                            best[seq] = {**row, "_turno": turno}
                    text.detach()

            for row in best.values():
                conn.execute(
                    """INSERT OR REPLACE INTO tse_candidate
                       (election_year, office, tse_seq, cpf, name, party, state, election_result)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        year,
                        canonicalize_office(row["DS_CARGO"]),
                        int(row["SQ_CANDIDATO"]),
                        row.get("NR_CPF_CANDIDATO", "").strip() or None,
                        row["NM_CANDIDATO"].strip(),
                        row["SG_PARTIDO"].strip(),
                        row["SG_UF"].strip(),
                        canonicalize_election_result(row["DS_SIT_TOT_TURNO"]),
                    ),
                )
        conn.commit()


def backfill_senator_cpf(conn: sqlite3.Connection) -> None:
    """Update senator.cpf from tse_candidate for matched senators.

    Matches on normalized civil_name (uppercase, accents stripped). Senators
    with null civil_name are skipped. Unmatched tse_candidate senator rows
    produce a WARNING — expected for senators outside our 2018/2022 scope.
    """
    candidates = conn.execute(
        "SELECT cpf, name FROM tse_candidate "
        "WHERE office = 'senator' AND cpf IS NOT NULL"
    ).fetchall()

    senators = conn.execute(
        "SELECT id, civil_name FROM senator WHERE civil_name IS NOT NULL"
    ).fetchall()

    senator_lookup: Dict[str, int] = {
        _normalize_name(s["civil_name"]): s["id"] for s in senators
    }

    matched = 0
    for cand in candidates:
        normalized = _normalize_name(cand["name"])
        senator_id = senator_lookup.get(normalized)
        if senator_id is not None:
            conn.execute(
                "UPDATE senator SET cpf = ? WHERE id = ?",
                (cand["cpf"], senator_id),
            )
            matched += 1
        else:
            log.warning(
                "backfill_senator_cpf: no senator match for TSE name %r", cand["name"]
            )

    conn.commit()
    log.info("backfill_senator_cpf: matched %d / %d candidates", matched, len(candidates))


def resolve_candidate_fks(conn: sqlite3.Connection) -> None:
    """Populate tse_candidate.deputy_id / senator_id by matching CPFs."""
    conn.execute(
        "UPDATE tse_candidate SET deputy_id = ("
        "  SELECT id FROM deputy WHERE deputy.cpf = tse_candidate.cpf"
        ") WHERE office = 'federal_deputy' AND cpf IS NOT NULL"
    )
    conn.execute(
        "UPDATE tse_candidate SET senator_id = ("
        "  SELECT id FROM senator WHERE senator.cpf = tse_candidate.cpf"
        ") WHERE office = 'senator' AND cpf IS NOT NULL"
    )
    conn.commit()
    log.info("resolve_candidate_fks: done")
