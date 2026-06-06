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
