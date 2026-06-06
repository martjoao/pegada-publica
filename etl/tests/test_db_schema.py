"""Schema-level tests: assert that the canonical tables have the expected columns
with correct nullability.

Strategy: create the schema in a temp in-memory DB, then query PRAGMA table_info()
which returns (cid, name, type, notnull, dflt_value, pk) for each column.
"""
import sqlite3
import pytest
from transform import db as txdb


def _column_info(conn: sqlite3.Connection, table: str) -> dict:
    """Return {column_name: {type, notnull, pk}} for every column in *table*."""
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {
        row[1]: {"type": row[2], "notnull": bool(row[3]), "pk": bool(row[5])}
        for row in rows
    }


@pytest.fixture(scope="module")
def schema_conn():
    """In-memory DB with the full schema applied once for all tests in this module."""
    conn = sqlite3.connect(":memory:")
    txdb.create_schema(conn)
    return conn


# ---------------------------------------------------------------------------
# deputy table
# ---------------------------------------------------------------------------

class TestDeputyColumns:
    def test_id_is_pk_not_null(self, schema_conn):
        cols = _column_info(schema_conn, "deputy")
        assert cols["id"]["pk"] is True

    def test_name_is_not_null(self, schema_conn):
        cols = _column_info(schema_conn, "deputy")
        assert cols["name"]["notnull"] is True

    def test_photo_url_is_nullable(self, schema_conn):
        cols = _column_info(schema_conn, "deputy")
        assert cols["photo_url"]["notnull"] is False

    def test_current_status_is_nullable(self, schema_conn):
        cols = _column_info(schema_conn, "deputy")
        assert cols["current_status"]["notnull"] is False

    def test_cpf_exists_and_is_nullable(self, schema_conn):
        cols = _column_info(schema_conn, "deputy")
        assert "cpf" in cols
        assert cols["cpf"]["notnull"] is False

    def test_civil_name_exists_and_is_nullable(self, schema_conn):
        cols = _column_info(schema_conn, "deputy")
        assert "civil_name" in cols
        assert cols["civil_name"]["notnull"] is False

    def test_date_of_birth_exists_and_is_nullable(self, schema_conn):
        cols = _column_info(schema_conn, "deputy")
        assert "date_of_birth" in cols
        assert cols["date_of_birth"]["notnull"] is False

    def test_date_of_death_exists_and_is_nullable(self, schema_conn):
        cols = _column_info(schema_conn, "deputy")
        assert "date_of_death" in cols
        assert cols["date_of_death"]["notnull"] is False

    def test_sex_exists_and_is_nullable(self, schema_conn):
        cols = _column_info(schema_conn, "deputy")
        assert "sex" in cols
        assert cols["sex"]["notnull"] is False

    def test_birth_state_exists_and_is_nullable(self, schema_conn):
        cols = _column_info(schema_conn, "deputy")
        assert "birth_state" in cols
        assert cols["birth_state"]["notnull"] is False

    def test_birth_city_exists_and_is_nullable(self, schema_conn):
        cols = _column_info(schema_conn, "deputy")
        assert "birth_city" in cols
        assert cols["birth_city"]["notnull"] is False

    def test_education_exists_and_is_nullable(self, schema_conn):
        cols = _column_info(schema_conn, "deputy")
        assert "education" in cols
        assert cols["education"]["notnull"] is False

    def test_social_media_exists_and_is_nullable(self, schema_conn):
        cols = _column_info(schema_conn, "deputy")
        assert "social_media" in cols
        assert cols["social_media"]["notnull"] is False

    def test_website_exists_and_is_nullable(self, schema_conn):
        cols = _column_info(schema_conn, "deputy")
        assert "website" in cols
        assert cols["website"]["notnull"] is False

    def test_deputy_has_no_cpf_as_not_null(self, schema_conn):
        """cpf must remain nullable — LGPD requires internal-only handling."""
        cols = _column_info(schema_conn, "deputy")
        assert cols["cpf"]["notnull"] is False


# ---------------------------------------------------------------------------
# senator table
# ---------------------------------------------------------------------------

class TestSenatorColumns:
    def test_id_is_pk_not_null(self, schema_conn):
        cols = _column_info(schema_conn, "senator")
        assert cols["id"]["pk"] is True

    def test_name_is_not_null(self, schema_conn):
        cols = _column_info(schema_conn, "senator")
        assert cols["name"]["notnull"] is True

    def test_photo_url_is_nullable(self, schema_conn):
        cols = _column_info(schema_conn, "senator")
        assert cols["photo_url"]["notnull"] is False

    def test_current_status_is_nullable(self, schema_conn):
        cols = _column_info(schema_conn, "senator")
        assert cols["current_status"]["notnull"] is False

    def test_civil_name_exists_and_is_nullable(self, schema_conn):
        cols = _column_info(schema_conn, "senator")
        assert "civil_name" in cols
        assert cols["civil_name"]["notnull"] is False

    def test_date_of_birth_exists_and_is_nullable(self, schema_conn):
        cols = _column_info(schema_conn, "senator")
        assert "date_of_birth" in cols
        assert cols["date_of_birth"]["notnull"] is False

    def test_birth_state_exists_and_is_nullable(self, schema_conn):
        cols = _column_info(schema_conn, "senator")
        assert "birth_state" in cols
        assert cols["birth_state"]["notnull"] is False

    def test_birth_city_exists_and_is_nullable(self, schema_conn):
        cols = _column_info(schema_conn, "senator")
        assert "birth_city" in cols
        assert cols["birth_city"]["notnull"] is False

    def test_sex_exists_and_is_nullable(self, schema_conn):
        cols = _column_info(schema_conn, "senator")
        assert "sex" in cols
        assert cols["sex"]["notnull"] is False

    def test_email_exists_and_is_nullable(self, schema_conn):
        cols = _column_info(schema_conn, "senator")
        assert "email" in cols
        assert cols["email"]["notnull"] is False

    def test_cpf_exists_and_is_nullable(self, schema_conn):
        """cpf column was added to senator for TSE backfill; confirm it is nullable."""
        cols = _column_info(schema_conn, "senator")
        assert "cpf" in cols
        assert cols["cpf"]["notnull"] is False
