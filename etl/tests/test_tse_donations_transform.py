"""Tests for transform.tse.donations — helpers, pipeline steps, and integration."""
import csv
import io
import sqlite3
import zipfile
from pathlib import Path
from typing import Dict, List

import pytest

from transform.tse.donations import (
    canonicalize_election_result,
    canonicalize_funding_source,
    canonicalize_office,
    infer_donor_type,
    parse_br_decimal,
)


# ── Helper tests ──────────────────────────────────────────────────────────────

def test_canonicalize_office_known_values():
    assert canonicalize_office("DEPUTADO FEDERAL") == "federal_deputy"
    assert canonicalize_office("SENADOR") == "senator"
    assert canonicalize_office("PRESIDENTE") == "president"


def test_canonicalize_office_case_insensitive():
    assert canonicalize_office("deputado federal") == "federal_deputy"


def test_canonicalize_office_unknown_raises():
    with pytest.raises(ValueError, match="Unknown"):
        canonicalize_office("GOVERNADOR")


def test_canonicalize_election_result_elected_variants():
    assert canonicalize_election_result("ELEITO") == "elected"
    assert canonicalize_election_result("ELEITO POR QP") == "elected"
    assert canonicalize_election_result("ELEITO POR MÉDIA") == "elected"
    assert canonicalize_election_result("ELEITO NO 2º TURNO") == "elected"


def test_canonicalize_election_result_other_values():
    assert canonicalize_election_result("NÃO ELEITO") == "not_elected"
    assert canonicalize_election_result("SUPLENTE") == "alternate"
    assert canonicalize_election_result("CASSADO") == "invalidated"
    assert canonicalize_election_result("RENÚNCIA") == "withdrew"
    assert canonicalize_election_result("2º TURNO") == "pending"


def test_canonicalize_election_result_unknown_returns_none():
    assert canonicalize_election_result("RESULTADO DESCONHECIDO") is None


def test_canonicalize_funding_source_known_values():
    assert canonicalize_funding_source("Doações de pessoas físicas") == "individual_donation"
    assert canonicalize_funding_source("Recursos do próprio candidato") == "self_funding"
    assert canonicalize_funding_source("Doações de partido") == "party_transfer"
    assert canonicalize_funding_source("Transferências do partido") == "party_transfer"
    assert canonicalize_funding_source("Fundo Especial de Financiamento de Campanha") == "electoral_fund"
    assert canonicalize_funding_source("Fundo Partidário") == "party_fund"
    assert canonicalize_funding_source("Recursos de outros candidatos") == "candidate_transfer"


def test_canonicalize_funding_source_unknown_returns_other():
    result = canonicalize_funding_source("Fonte desconhecida qualquer")
    assert result == "other"


def test_parse_br_decimal():
    assert parse_br_decimal("1.234,56") == pytest.approx(1234.56)
    assert parse_br_decimal("0,00") == pytest.approx(0.0)
    assert parse_br_decimal("50000,00") == pytest.approx(50000.0)
    assert parse_br_decimal("  100,50  ") == pytest.approx(100.50)


def test_infer_donor_type():
    assert infer_donor_type("12345678901") == "individual"       # 11 digits
    assert infer_donor_type("12345678000195") == "company"       # 14 digits
    assert infer_donor_type(None) == "party"
    assert infer_donor_type("") == "party"
    assert infer_donor_type("123") == "unknown"                  # other length
