"""Tests for load_bio() and its integration into transform().

Raw inputs are PT (verbatim API); canonical DB assertions are English.
"""
from __future__ import annotations

import json

import pytest

from common import paths
from common.jsonio import write_json_atomic
from transform import db as txdb
from transform.camara import deputados as txdep


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _bio_payload(dep_id: int, **overrides) -> dict:
    """Return a minimal bio landing-file payload for *dep_id*."""
    dados = {
        "id": dep_id,
        "nomeCivil": "João da Silva",
        "cpf": "123.456.789-00",
        "dataNascimento": "1975-03-22",
        "dataFalecimento": None,
        "sexo": "M",
        "ufNascimento": "SP",
        "municipioNascimento": "São Paulo",
        "escolaridade": "Superior",
        "redeSocial": ["https://twitter.com/joao"],
        "urlWebsite": "https://joao.example.com",
    }
    dados.update(overrides)
    return {
        "_meta": {"source": "camara-dados-abertos", "endpoint": f"/deputados/{dep_id}",
                  "deputy_id": dep_id, "fetched_at": "2026-06-06T00:00:00Z"},
        "dados": dados,
    }


def _roster_payload(dep_id: int, nome: str = "Test Deputy", leg: int = 57) -> dict:
    """Return a minimal roster landing-file payload."""
    return {
        "_meta": {"source": "camara-dados-abertos", "endpoint": "/deputados",
                  "legislatura": leg, "fetched_at": "2026-06-06T00:00:00Z",
                  "record_count": 1},
        "dados": [
            {"id": dep_id, "nome": nome, "siglaPartido": "PT", "siglaUf": "SP",
             "urlFoto": f"http://foto/{dep_id}.jpg", "idLegislatura": leg},
        ],
    }


def _seed_bio(base, dep_id: int, **overrides):
    """Write a bio file for *dep_id* under *base*."""
    write_json_atomic(_bio_payload(dep_id, **overrides),
                      paths.camara_bio_path(dep_id, base=base))


def _seed_roster(base, dep_id: int, nome: str = "Test Deputy"):
    """Write roster files (leg 57 + empty leg 56) under *base*."""
    write_json_atomic(_roster_payload(dep_id, nome),
                      paths.camara_deputados_path(57, base=base))
    write_json_atomic({"_meta": {}, "dados": []},
                      paths.camara_deputados_path(56, base=base))


# ---------------------------------------------------------------------------
# load_bio() unit tests
# ---------------------------------------------------------------------------

class TestLoadBio:
    def test_all_ten_fields_mapped_correctly(self, tmp_path):
        dep_id = 1001
        _seed_bio(tmp_path, dep_id)

        result = txdep.load_bio([dep_id], raw_base=tmp_path)

        assert dep_id in result
        bio = result[dep_id]
        assert bio["cpf"] == "123.456.789-00"
        assert bio["civil_name"] == "João da Silva"
        assert bio["date_of_birth"] == "1975-03-22"
        assert bio["date_of_death"] is None
        assert bio["sex"] == "M"
        assert bio["birth_state"] == "SP"
        assert bio["birth_city"] == "São Paulo"
        assert bio["education"] == "Superior"
        assert bio["social_media"] == '["https://twitter.com/joao"]'
        assert bio["website"] == "https://joao.example.com"

    def test_social_media_nonempty_list_serialized_to_json_string(self, tmp_path):
        dep_id = 1002
        _seed_bio(tmp_path, dep_id,
                  redeSocial=["https://twitter.com/x", "https://instagram.com/y"])

        result = txdep.load_bio([dep_id], raw_base=tmp_path)

        social_media = result[dep_id]["social_media"]
        # Must be a JSON string, not a list
        assert isinstance(social_media, str)
        parsed = json.loads(social_media)
        assert parsed == ["https://twitter.com/x", "https://instagram.com/y"]

    def test_social_media_empty_list_produces_empty_json_array(self, tmp_path):
        dep_id = 1003
        _seed_bio(tmp_path, dep_id, redeSocial=[])

        result = txdep.load_bio([dep_id], raw_base=tmp_path)

        assert result[dep_id]["social_media"] == "[]"

    def test_social_media_absent_key_produces_empty_json_array(self, tmp_path):
        dep_id = 1004
        payload = _bio_payload(dep_id)
        del payload["dados"]["redeSocial"]
        write_json_atomic(payload, paths.camara_bio_path(dep_id, base=tmp_path))

        result = txdep.load_bio([dep_id], raw_base=tmp_path)

        assert result[dep_id]["social_media"] == "[]"

    def test_missing_bio_file_for_id_absent_from_dict(self, tmp_path):
        # No bio file written for this id
        result = txdep.load_bio([9999], raw_base=tmp_path)

        assert 9999 not in result
        assert result == {}

    def test_missing_file_does_not_affect_other_ids(self, tmp_path):
        dep_present = 1005
        dep_missing = 9999
        _seed_bio(tmp_path, dep_present)

        result = txdep.load_bio([dep_present, dep_missing], raw_base=tmp_path)

        assert dep_present in result
        assert dep_missing not in result

    def test_date_of_death_falsy_string_becomes_none(self, tmp_path):
        dep_id = 1006
        _seed_bio(tmp_path, dep_id, dataFalecimento="")

        result = txdep.load_bio([dep_id], raw_base=tmp_path)

        assert result[dep_id]["date_of_death"] is None

    def test_date_of_death_real_date_passes_through(self, tmp_path):
        dep_id = 1007
        _seed_bio(tmp_path, dep_id, dataFalecimento="2020-05-10")

        result = txdep.load_bio([dep_id], raw_base=tmp_path)

        assert result[dep_id]["date_of_death"] == "2020-05-10"


# ---------------------------------------------------------------------------
# transform() integration tests
# ---------------------------------------------------------------------------

class TestTransformWithBio:
    def _make_conn(self, tmp_path):
        conn = txdb.connect(tmp_path / "t.db")
        txdb.create_schema(conn)
        return conn

    def test_bio_columns_populated_on_inserted_deputy_row(self, tmp_path):
        dep_id = 2001
        _seed_roster(tmp_path, dep_id, nome="Test Deputy Bio")
        _seed_bio(tmp_path, dep_id)

        conn = self._make_conn(tmp_path)
        txdep.transform(conn, raw_base=tmp_path)

        row = conn.execute(
            "SELECT cpf, civil_name, date_of_birth, date_of_death, sex, "
            "birth_state, birth_city, education, social_media, website "
            "FROM deputy WHERE id=?", (dep_id,)
        ).fetchone()
        assert row is not None
        assert row["cpf"] == "123.456.789-00"
        assert row["civil_name"] == "João da Silva"
        assert row["date_of_birth"] == "1975-03-22"
        assert row["date_of_death"] is None
        assert row["sex"] == "M"
        assert row["birth_state"] == "SP"
        assert row["birth_city"] == "São Paulo"
        assert row["education"] == "Superior"
        assert row["social_media"] == '["https://twitter.com/joao"]'
        assert row["website"] == "https://joao.example.com"

    def test_deputy_with_no_bio_file_has_null_bio_columns(self, tmp_path):
        dep_id = 2002
        _seed_roster(tmp_path, dep_id, nome="No Bio Deputy")
        # Intentionally: no bio file for this deputy

        conn = self._make_conn(tmp_path)
        txdep.transform(conn, raw_base=tmp_path)

        row = conn.execute(
            "SELECT cpf, civil_name, date_of_birth, date_of_death, sex, "
            "birth_state, birth_city, education, social_media, website "
            "FROM deputy WHERE id=?", (dep_id,)
        ).fetchone()
        assert row is not None
        assert row["cpf"] is None
        assert row["civil_name"] is None
        assert row["date_of_birth"] is None
        assert row["date_of_death"] is None
        assert row["sex"] is None
        assert row["birth_state"] is None
        assert row["birth_city"] is None
        assert row["education"] is None
        assert row["social_media"] is None
        assert row["website"] is None
