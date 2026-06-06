"""Tests for load_bio() and its integration into transform() for senators.

Raw inputs are PT (verbatim API); canonical DB assertions are English.
"""
from __future__ import annotations

import pytest

from common import paths
from common.jsonio import write_json_atomic
from transform import db as txdb
from transform.senado import senadores as txsen


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _bio_payload(codigo: int, **overrides) -> dict:
    """Return a minimal bio landing-file payload for *codigo*."""
    ident = {
        "CodigoParlamentar": str(codigo),
        "NomeParlamentar": "Test Senator",
        "NomeCompletoParlamentar": "Maria do Carmo do Nascimento Alves",
        "SexoParlamentar": "Feminino",
        "EmailParlamentar": "sen.test@senado.leg.br",
        "UrlFotoParlamentar": f"http://foto/{codigo}.jpg",
    }
    basico = {
        "DataNascimento": "1941-08-23",
        "Naturalidade": "Cedro de São João",
        "UfNaturalidade": "SE",
    }
    ident.update(overrides.get("_ident", {}))
    basico.update(overrides.get("_basico", {}))
    return {
        "_meta": {
            "source": "senado-dados-abertos",
            "endpoint": f"/senador/{codigo}/detalhe",
            "codigo": codigo,
            "fetched_at": "2026-06-06T00:00:00Z",
        },
        "dados": {
            "DetalheParlamentar": {
                "Parlamentar": {
                    "IdentificacaoParlamentar": ident,
                    "DadosBasicosParlamentar": basico,
                }
            }
        },
    }


def _roster_payload(codigo: int, nome: str = "Test Senator", leg: int = 57) -> dict:
    """Return a minimal lista landing-file payload."""
    return {
        "_meta": {
            "source": "senado-dados-abertos",
            "endpoint": "/senado/lista/legislatura",
            "legislatura": leg,
            "fetched_at": "2026-06-06T00:00:00Z",
            "record_count": 1,
        },
        "dados": [
            {
                "IdentificacaoParlamentar": {
                    "CodigoParlamentar": str(codigo),
                    "NomeParlamentar": nome,
                    "UrlFotoParlamentar": f"http://foto/{codigo}.jpg",
                }
            }
        ],
    }


def _seed_bio(base, codigo: int, **overrides):
    """Write a bio file for *codigo* under *base*."""
    write_json_atomic(_bio_payload(codigo, **overrides),
                      paths.senado_bio_path(codigo, base=base))


def _seed_roster(base, codigo: int, nome: str = "Test Senator"):
    """Write roster files (leg 57 + empty leg 56) under *base*."""
    write_json_atomic(_roster_payload(codigo, nome),
                      paths.senado_lista_path(57, base=base))
    write_json_atomic({"_meta": {}, "dados": []},
                      paths.senado_lista_path(56, base=base))


# ---------------------------------------------------------------------------
# load_bio() unit tests
# ---------------------------------------------------------------------------

class TestLoadBio:
    def test_all_six_fields_mapped_correctly(self, tmp_path):
        codigo = 1023
        _seed_bio(tmp_path, codigo)

        result = txsen.load_bio([codigo], raw_base=tmp_path)

        assert codigo in result
        bio = result[codigo]
        assert bio["civil_name"] == "Maria do Carmo do Nascimento Alves"
        assert bio["date_of_birth"] == "1941-08-23"
        assert bio["birth_city"] == "Cedro de São João"
        assert bio["birth_state"] == "SE"
        assert bio["sex"] == "F"
        assert bio["email"] == "sen.test@senado.leg.br"

    def test_sex_normalization_masculino(self, tmp_path):
        codigo = 1024
        _seed_bio(tmp_path, codigo, _ident={"SexoParlamentar": "Masculino"})

        result = txsen.load_bio([codigo], raw_base=tmp_path)

        assert result[codigo]["sex"] == "M"

    def test_sex_normalization_feminino(self, tmp_path):
        codigo = 1025
        _seed_bio(tmp_path, codigo, _ident={"SexoParlamentar": "Feminino"})

        result = txsen.load_bio([codigo], raw_base=tmp_path)

        assert result[codigo]["sex"] == "F"

    def test_sex_normalization_unknown_becomes_none(self, tmp_path):
        codigo = 1026
        _seed_bio(tmp_path, codigo, _ident={"SexoParlamentar": "Outro"})

        result = txsen.load_bio([codigo], raw_base=tmp_path)

        assert result[codigo]["sex"] is None

    def test_sex_normalization_missing_becomes_none(self, tmp_path):
        codigo = 1027
        payload = _bio_payload(codigo)
        del payload["dados"]["DetalheParlamentar"]["Parlamentar"]["IdentificacaoParlamentar"]["SexoParlamentar"]
        write_json_atomic(payload, paths.senado_bio_path(codigo, base=tmp_path))

        result = txsen.load_bio([codigo], raw_base=tmp_path)

        assert result[codigo]["sex"] is None

    def test_missing_bio_file_for_id_absent_from_dict(self, tmp_path):
        result = txsen.load_bio([9999], raw_base=tmp_path)

        assert 9999 not in result
        assert result == {}

    def test_missing_file_does_not_affect_other_ids(self, tmp_path):
        codigo_present = 1028
        codigo_missing = 9999
        _seed_bio(tmp_path, codigo_present)

        result = txsen.load_bio([codigo_present, codigo_missing], raw_base=tmp_path)

        assert codigo_present in result
        assert codigo_missing not in result


# ---------------------------------------------------------------------------
# transform() integration tests
# ---------------------------------------------------------------------------

class TestTransformWithBio:
    def _make_conn(self, tmp_path):
        conn = txdb.connect(tmp_path / "t.db")
        txdb.create_schema(conn)
        return conn

    def test_bio_columns_populated_on_inserted_senator_row(self, tmp_path):
        codigo = 2001
        _seed_roster(tmp_path, codigo, nome="Test Senator Bio")
        _seed_bio(tmp_path, codigo)

        conn = self._make_conn(tmp_path)
        txsen.transform(conn, raw_base=tmp_path)

        row = conn.execute(
            "SELECT civil_name, date_of_birth, birth_city, birth_state, sex, email "
            "FROM senator WHERE id=?", (codigo,)
        ).fetchone()
        assert row is not None
        assert row["civil_name"] == "Maria do Carmo do Nascimento Alves"
        assert row["date_of_birth"] == "1941-08-23"
        assert row["birth_city"] == "Cedro de São João"
        assert row["birth_state"] == "SE"
        assert row["sex"] == "F"
        assert row["email"] == "sen.test@senado.leg.br"

    def test_senator_with_no_bio_file_has_null_bio_columns(self, tmp_path):
        codigo = 2002
        _seed_roster(tmp_path, codigo, nome="No Bio Senator")
        # Intentionally: no bio file for this senator

        conn = self._make_conn(tmp_path)
        txsen.transform(conn, raw_base=tmp_path)

        row = conn.execute(
            "SELECT civil_name, date_of_birth, birth_city, birth_state, sex, email "
            "FROM senator WHERE id=?", (codigo,)
        ).fetchone()
        assert row is not None
        assert row["civil_name"] is None
        assert row["date_of_birth"] is None
        assert row["birth_city"] is None
        assert row["birth_state"] is None
        assert row["sex"] is None
        assert row["email"] is None
