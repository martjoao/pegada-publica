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
from transform import db as txdb
from transform.tse.donations import load_candidates
from transform.tse.donations import backfill_senator_cpf
from transform.tse.donations import resolve_candidate_fks
from transform.tse.donations import load_donations


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


# ── Fake ZIP helper ───────────────────────────────────────────────────────────

_CAND_COLUMNS = [
    "DT_GERACAO", "HH_GERACAO", "ANO_ELEICAO", "CD_TIPO_ELEICAO",
    "NM_TIPO_ELEICAO", "NR_TURNO", "CD_ELEICAO", "DS_ELEICAO",
    "DT_ELEICAO", "TP_ABRANGENCIA", "SG_UF", "SG_UE", "NM_UE",
    "CD_CARGO", "DS_CARGO", "SQ_CANDIDATO", "NR_CANDIDATO",
    "NM_CANDIDATO", "NM_URNA_CANDIDATO", "NM_SOCIAL_CANDIDATO",
    "NR_CPF_CANDIDATO", "DS_EMAIL", "CD_SITUACAO_CANDIDATURA",
    "DS_SITUACAO_CANDIDATURA", "TP_AGREMIACAO", "NR_PARTIDO",
    "SG_PARTIDO", "NM_PARTIDO", "NR_FEDERACAO", "NM_FEDERACAO",
    "SG_FEDERACAO", "DS_COMPOSICAO_FEDERACAO", "SQ_COLIGACAO",
    "NM_COLIGACAO", "DS_COMPOSICAO_COLIGACAO", "SG_UF_NASCIMENTO",
    "DT_NASCIMENTO", "NR_TITULO_ELEITORAL_CANDIDATO", "CD_GENERO",
    "DS_GENERO", "CD_GRAU_INSTRUCAO", "DS_GRAU_INSTRUCAO",
    "CD_ESTADO_CIVIL", "DS_ESTADO_CIVIL", "CD_COR_RACA",
    "DS_COR_RACA", "CD_OCUPACAO", "DS_OCUPACAO",
    "CD_SIT_TOT_TURNO", "DS_SIT_TOT_TURNO",
]

def _cand_row(**kwargs) -> List[str]:
    """Build a consulta_cand row with sensible defaults."""
    defaults = {c: "" for c in _CAND_COLUMNS}
    defaults.update({
        "ANO_ELEICAO": "2022",
        "NR_TURNO": "1",
        "SG_UF": "SP",
        "DS_CARGO": "DEPUTADO FEDERAL",
        "SQ_CANDIDATO": "100",
        "NM_CANDIDATO": "ANA SILVA",
        "SG_PARTIDO": "PT",
        "NR_CPF_CANDIDATO": "12345678901",
        "DS_SIT_TOT_TURNO": "ELEITO POR QP",
    })
    defaults.update(kwargs)
    return [defaults[c] for c in _CAND_COLUMNS]


def _make_candidatos_zip(rows_by_file: Dict[str, List[List[str]]]) -> bytes:
    """Build an in-memory consulta_cand ZIP with per-state CSVs."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_STORED) as zf:
        for filename, rows in rows_by_file.items():
            csv_buf = io.StringIO()
            writer = csv.writer(csv_buf, delimiter=";")
            writer.writerow(_CAND_COLUMNS)
            writer.writerows(rows)
            zf.writestr(filename, csv_buf.getvalue().encode("latin-1"))
    buf.seek(0)
    return buf.read()


def _db(tmp_path) -> sqlite3.Connection:
    conn = txdb.connect(tmp_path / "test.db")
    txdb.create_schema(conn)
    return conn


# ── load_candidates tests ─────────────────────────────────────────────────────

def test_load_candidates_inserts_federal_rows(tmp_path):
    rows = [
        _cand_row(DS_CARGO="DEPUTADO FEDERAL", SQ_CANDIDATO="100",
                  NM_CANDIDATO="ANA SILVA", SG_PARTIDO="PT", SG_UF="SP",
                  NR_CPF_CANDIDATO="12345678901", DS_SIT_TOT_TURNO="ELEITO POR QP"),
        _cand_row(DS_CARGO="SENADOR", SQ_CANDIDATO="200",
                  NM_CANDIDATO="BRUNO LIMA", SG_PARTIDO="PL", SG_UF="RJ",
                  NR_CPF_CANDIDATO="98765432100", DS_SIT_TOT_TURNO="ELEITO"),
    ]
    zip_bytes = _make_candidatos_zip({"consulta_cand_2022_SP.csv": rows})
    zip_path = tmp_path / "tse" / "candidatos" / "2022.zip"
    zip_path.parent.mkdir(parents=True)
    zip_path.write_bytes(zip_bytes)

    conn = _db(tmp_path)
    load_candidates(conn, years=(2022,), base=tmp_path)
    rows_db = conn.execute("SELECT * FROM tse_candidate ORDER BY tse_seq").fetchall()
    assert len(rows_db) == 2
    assert rows_db[0]["office"] == "federal_deputy"
    assert rows_db[0]["name"] == "ANA SILVA"
    assert rows_db[0]["election_result"] == "elected"
    assert rows_db[1]["office"] == "senator"


def test_load_candidates_filters_non_federal(tmp_path):
    rows = [
        _cand_row(DS_CARGO="DEPUTADO FEDERAL", SQ_CANDIDATO="100"),
        _cand_row(DS_CARGO="GOVERNADOR", SQ_CANDIDATO="200"),   # filtered out
    ]
    zip_bytes = _make_candidatos_zip({"consulta_cand_2022_SP.csv": rows})
    zip_path = tmp_path / "tse" / "candidatos" / "2022.zip"
    zip_path.parent.mkdir(parents=True)
    zip_path.write_bytes(zip_bytes)

    conn = _db(tmp_path)
    load_candidates(conn, years=(2022,), base=tmp_path)
    count = conn.execute("SELECT COUNT(*) FROM tse_candidate").fetchone()[0]
    assert count == 1


def test_load_candidates_deduplicates_by_highest_round(tmp_path):
    # Presidential candidate with two round rows — round 2 result should win
    rows = [
        _cand_row(DS_CARGO="PRESIDENTE", SQ_CANDIDATO="300",
                  NM_CANDIDATO="LULA", SG_PARTIDO="PT", SG_UF="BR",
                  NR_TURNO="1", DS_SIT_TOT_TURNO="2º TURNO"),
        _cand_row(DS_CARGO="PRESIDENTE", SQ_CANDIDATO="300",
                  NM_CANDIDATO="LULA", SG_PARTIDO="PT", SG_UF="BR",
                  NR_TURNO="2", DS_SIT_TOT_TURNO="ELEITO NO 2º TURNO"),
    ]
    zip_bytes = _make_candidatos_zip({"consulta_cand_2022_BR.csv": rows})
    zip_path = tmp_path / "tse" / "candidatos" / "2022.zip"
    zip_path.parent.mkdir(parents=True)
    zip_path.write_bytes(zip_bytes)

    conn = _db(tmp_path)
    load_candidates(conn, years=(2022,), base=tmp_path)
    rows_db = conn.execute("SELECT * FROM tse_candidate").fetchall()
    assert len(rows_db) == 1
    assert rows_db[0]["election_result"] == "elected"   # round-2 result wins


# ── backfill_senator_cpf tests ────────────────────────────────────────────────

def _insert_deputy(conn, deputy_id, cpf):
    conn.execute(
        "INSERT INTO deputy (id, name, cpf) VALUES (?, ?, ?)",
        (deputy_id, f"Dep {deputy_id}", cpf),
    )


def _insert_senator(conn, senator_id, civil_name, cpf=None):
    conn.execute(
        "INSERT INTO senator (id, name, civil_name, cpf) VALUES (?, ?, ?, ?)",
        (senator_id, f"Sen {senator_id}", civil_name, cpf),
    )


def test_backfill_senator_cpf_matches_by_normalized_name(tmp_path):
    conn = _db(tmp_path)
    _insert_senator(conn, 1, "João da Silva Pereira")
    conn.execute(
        "INSERT INTO tse_candidate (election_year, office, tse_seq, cpf, name, party, state) "
        "VALUES (2022, 'senator', 200, '98765432100', 'JOÃO DA SILVA PEREIRA', 'PT', 'SP')"
    )
    conn.commit()

    backfill_senator_cpf(conn)

    cpf = conn.execute("SELECT cpf FROM senator WHERE id = 1").fetchone()["cpf"]
    assert cpf == "98765432100"


def test_backfill_senator_cpf_handles_accents_and_case(tmp_path):
    conn = _db(tmp_path)
    _insert_senator(conn, 2, "Ângela Cristina Ünal")
    conn.execute(
        "INSERT INTO tse_candidate (election_year, office, tse_seq, cpf, name, party, state) "
        "VALUES (2022, 'senator', 201, '11122233344', 'ANGELA CRISTINA UNAL', 'PL', 'RJ')"
    )
    conn.commit()

    backfill_senator_cpf(conn)

    cpf = conn.execute("SELECT cpf FROM senator WHERE id = 2").fetchone()["cpf"]
    assert cpf == "11122233344"


def test_backfill_senator_cpf_skips_null_civil_name(tmp_path):
    conn = _db(tmp_path)
    _insert_senator(conn, 3, None)   # no civil_name
    conn.execute(
        "INSERT INTO tse_candidate (election_year, office, tse_seq, cpf, name, party, state) "
        "VALUES (2022, 'senator', 202, '55566677788', 'CARLOS NETO', 'MDB', 'MG')"
    )
    conn.commit()

    backfill_senator_cpf(conn)   # must not raise

    cpf = conn.execute("SELECT cpf FROM senator WHERE id = 3").fetchone()["cpf"]
    assert cpf is None   # not updated


def test_backfill_senator_cpf_logs_warning_on_no_match(tmp_path, caplog):
    import logging
    conn = _db(tmp_path)
    conn.execute(
        "INSERT INTO tse_candidate (election_year, office, tse_seq, cpf, name, party, state) "
        "VALUES (2022, 'senator', 203, '99988877766', 'NOME SEM CORRESPONDENTE', 'PT', 'SP')"
    )
    conn.commit()

    with caplog.at_level(logging.WARNING, logger="transform.tse.donations"):
        backfill_senator_cpf(conn)

    assert any("NOME SEM CORRESPONDENTE" in r.message for r in caplog.records)


def test_resolve_candidate_fks_links_deputy(tmp_path):
    conn = _db(tmp_path)
    _insert_deputy(conn, 10, "12345678901")
    conn.execute(
        "INSERT INTO tse_candidate (election_year, office, tse_seq, cpf, name, party, state) "
        "VALUES (2022, 'federal_deputy', 300, '12345678901', 'DEP A', 'PT', 'SP')"
    )
    conn.commit()

    resolve_candidate_fks(conn)

    row = conn.execute(
        "SELECT deputy_id, senator_id FROM tse_candidate WHERE tse_seq = 300"
    ).fetchone()
    assert row["deputy_id"] == 10
    assert row["senator_id"] is None


def test_resolve_candidate_fks_links_senator(tmp_path):
    conn = _db(tmp_path)
    _insert_senator(conn, 20, "Maria Souza", cpf="98765432100")
    conn.execute(
        "INSERT INTO tse_candidate (election_year, office, tse_seq, cpf, name, party, state) "
        "VALUES (2022, 'senator', 301, '98765432100', 'MARIA SOUZA', 'PL', 'RJ')"
    )
    conn.commit()

    resolve_candidate_fks(conn)

    row = conn.execute(
        "SELECT deputy_id, senator_id FROM tse_candidate WHERE tse_seq = 301"
    ).fetchone()
    assert row["senator_id"] == 20
    assert row["deputy_id"] is None


def test_resolve_candidate_fks_skips_null_cpf(tmp_path):
    conn = _db(tmp_path)
    conn.execute(
        "INSERT INTO tse_candidate (election_year, office, tse_seq, cpf, name, party, state) "
        "VALUES (2022, 'federal_deputy', 302, NULL, 'SEM CPF', 'MDB', 'MG')"
    )
    conn.commit()

    resolve_candidate_fks(conn)   # must not raise

    row = conn.execute(
        "SELECT deputy_id FROM tse_candidate WHERE tse_seq = 302"
    ).fetchone()
    assert row["deputy_id"] is None


def test_resolve_candidate_fks_leaves_presidential_null(tmp_path):
    conn = _db(tmp_path)
    conn.execute(
        "INSERT INTO tse_candidate (election_year, office, tse_seq, cpf, name, party, state) "
        "VALUES (2022, 'president', 303, '11122233344', 'CANDIDATO PRES', 'PT', 'BR')"
    )
    conn.commit()

    resolve_candidate_fks(conn)

    row = conn.execute(
        "SELECT deputy_id, senator_id FROM tse_candidate WHERE tse_seq = 303"
    ).fetchone()
    assert row["deputy_id"] is None
    assert row["senator_id"] is None


# ── load_donations helpers ────────────────────────────────────────────────────

_RECEITA_COLUMNS = [
    "DT_GERACAO", "HH_GERACAO", "AA_ELEICAO", "CD_TIPO_ELEICAO",
    "NM_TIPO_ELEICAO", "CD_ELEICAO", "DS_ELEICAO", "DT_ELEICAO",
    "ST_TURNO", "TP_PRESTACAO_CONTAS", "DT_PRESTACAO_CONTAS",
    "SQ_PRESTADOR_CONTAS", "SG_UF", "SG_UE", "NM_UE",
    "NR_CNPJ_PRESTADOR_CONTA", "CD_CARGO", "DS_CARGO",
    "SQ_CANDIDATO", "NR_CANDIDATO", "NM_CANDIDATO",
    "NR_CPF_CANDIDATO", "NR_CPF_VICE_CANDIDATO",
    "NR_PARTIDO", "SG_PARTIDO", "NM_PARTIDO",
    "CD_FONTE_RECEITA", "DS_FONTE_RECEITA",
    "CD_ORIGEM_RECEITA", "DS_ORIGEM_RECEITA",
    "CD_NATUREZA_RECEITA", "DS_NATUREZA_RECEITA",
    "CD_ESPECIE_RECEITA", "DS_ESPECIE_RECEITA",
    "CD_CNAE_DOADOR", "DS_CNAE_DOADOR",
    "NR_CPF_CNPJ_DOADOR", "NM_DOADOR", "NM_DOADOR_RFB",
    "CD_ESFERA_PARTIDARIA_DOADOR", "DS_ESFERA_PARTIDARIA_DOADOR",
    "SG_UF_DOADOR", "CD_MUNICIPIO_DOADOR", "NM_MUNICIPIO_DOADOR",
    "SQ_CANDIDATO_DOADOR", "NR_CANDIDATO_DOADOR",
    "CD_CARGO_CANDIDATO_DOADOR", "DS_CARGO_CANDIDATO_DOADOR",
    "NR_PARTIDO_DOADOR", "SG_PARTIDO_DOADOR", "NM_PARTIDO_DOADOR",
    "NR_RECIBO_DOACAO", "NR_DOCUMENTO_DOACAO", "SQ_RECEITA",
    "DT_RECEITA", "DS_RECEITA", "VR_RECEITA",
    "DS_NATUREZA_RECURSO_ESTIMAVEL", "DS_GENERO", "DS_COR_RACA",
]


def _receita_row(**kwargs) -> List[str]:
    defaults = {c: "" for c in _RECEITA_COLUMNS}
    defaults.update({
        "AA_ELEICAO": "2022",
        "DS_CARGO": "DEPUTADO FEDERAL",
        "SQ_CANDIDATO": "100",
        "NM_CANDIDATO": "ANA SILVA",
        "SG_PARTIDO": "PT",
        "NR_CPF_CNPJ_DOADOR": "12345678901",
        "NM_DOADOR": "JOAO SILVA",
        "NM_DOADOR_RFB": "JOAO SILVA SANTOS",
        "SG_UF_DOADOR": "SP",
        "NM_MUNICIPIO_DOADOR": "São Paulo",
        "DS_FONTE_RECEITA": "Doações de pessoas físicas",
        "NR_RECIBO_DOACAO": "R001",
        "DT_RECEITA": "10/09/2022",
        "VR_RECEITA": "50000,00",
    })
    defaults.update(kwargs)
    return [defaults[c] for c in _RECEITA_COLUMNS]


def _make_receitas_zip(rows: List[List[str]], year: int = 2022) -> bytes:
    """Build a receitas ZIP with only the BRASIL.csv (as in real TSE data)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_STORED) as zf:
        csv_buf = io.StringIO()
        writer = csv.writer(csv_buf, delimiter=";")
        writer.writerow(_RECEITA_COLUMNS)
        writer.writerows(rows)
        zf.writestr(
            f"receitas_candidatos_{year}_BRASIL.csv",
            csv_buf.getvalue().encode("latin-1"),
        )
    buf.seek(0)
    return buf.read()


def _setup_donation_db(tmp_path) -> sqlite3.Connection:
    """DB with one tse_candidate row ready to receive donations."""
    conn = _db(tmp_path)
    conn.execute(
        "INSERT INTO tse_candidate (id, election_year, office, tse_seq, name, party, state) "
        "VALUES (1, 2022, 'federal_deputy', 100, 'ANA SILVA', 'PT', 'SP')"
    )
    conn.commit()
    return conn


# ── load_donations tests ──────────────────────────────────────────────────────

def test_load_donations_creates_donor_and_donation(tmp_path):
    conn = _setup_donation_db(tmp_path)
    zip_path = tmp_path / "tse" / "receitas" / "2022.zip"
    zip_path.parent.mkdir(parents=True)
    zip_path.write_bytes(_make_receitas_zip([_receita_row()]))

    load_donations(conn, years=(2022,), base=tmp_path)

    donors = conn.execute("SELECT * FROM donor").fetchall()
    assert len(donors) == 1
    assert donors[0]["name"] == "JOAO SILVA SANTOS"   # NM_DOADOR_RFB preferred
    assert donors[0]["donor_type"] == "individual"

    donations = conn.execute("SELECT * FROM tse_donation").fetchall()
    assert len(donations) == 1
    assert donations[0]["amount"] == pytest.approx(50000.0)


def test_load_donations_deduplicates_donor_by_cpf(tmp_path):
    conn = _setup_donation_db(tmp_path)
    zip_path = tmp_path / "tse" / "receitas" / "2022.zip"
    zip_path.parent.mkdir(parents=True)
    # Same donor CPF, two separate donations
    zip_path.write_bytes(_make_receitas_zip([
        _receita_row(NR_RECIBO_DOACAO="R001", VR_RECEITA="10000,00"),
        _receita_row(NR_RECIBO_DOACAO="R002", VR_RECEITA="20000,00"),
    ]))

    load_donations(conn, years=(2022,), base=tmp_path)

    donor_count = conn.execute("SELECT COUNT(*) FROM donor").fetchone()[0]
    assert donor_count == 1   # same CPF → one donor row

    donation_count = conn.execute("SELECT COUNT(*) FROM tse_donation").fetchone()[0]
    assert donation_count == 2


def test_load_donations_idempotent_on_rerun(tmp_path):
    conn = _setup_donation_db(tmp_path)
    zip_path = tmp_path / "tse" / "receitas" / "2022.zip"
    zip_path.parent.mkdir(parents=True)
    zip_path.write_bytes(_make_receitas_zip([_receita_row(NR_RECIBO_DOACAO="R001")]))

    load_donations(conn, years=(2022,), base=tmp_path)
    load_donations(conn, years=(2022,), base=tmp_path)   # second run

    count = conn.execute("SELECT COUNT(*) FROM tse_donation").fetchone()[0]
    assert count == 1   # no duplicate


def test_load_donations_raises_if_brasil_csv_missing(tmp_path):
    conn = _setup_donation_db(tmp_path)
    # ZIP with only per-state CSV (no BRASIL)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("receitas_candidatos_2022_SP.csv", "col1\nval1")
    zip_path = tmp_path / "tse" / "receitas" / "2022.zip"
    zip_path.parent.mkdir(parents=True)
    zip_path.write_bytes(buf.getvalue())

    with pytest.raises(ValueError, match="BRASIL.csv not found"):
        load_donations(conn, years=(2022,), base=tmp_path)


def test_load_donations_filters_non_federal(tmp_path):
    conn = _setup_donation_db(tmp_path)
    zip_path = tmp_path / "tse" / "receitas" / "2022.zip"
    zip_path.parent.mkdir(parents=True)
    zip_path.write_bytes(_make_receitas_zip([
        _receita_row(DS_CARGO="DEPUTADO FEDERAL", NR_RECIBO_DOACAO="R001"),
        _receita_row(DS_CARGO="GOVERNADOR", NR_RECIBO_DOACAO="R002"),  # filtered
    ]))

    load_donations(conn, years=(2022,), base=tmp_path)

    count = conn.execute("SELECT COUNT(*) FROM tse_donation").fetchone()[0]
    assert count == 1
