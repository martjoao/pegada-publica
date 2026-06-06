# TSE Donations Transform Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Load TSE candidatos + receitas ZIPs into `pegada.db` (3 new tables), backfill `senator.cpf`, resolve FK links to deputy/senator entities, and extend build outputs with a donors ranking JSON and per-parliamentarian `top_donors` arrays.

**Architecture:** Four-step sequential transform in `etl/transform/tse/donations.py`: load candidates → backfill senator CPFs → resolve FKs → load donors + donations. Build layer: new `build/doadores.py` for the ranking; `build/deputados.py` and `build/senadores.py` extended with `top_donors`. All canonicalization (PT→EN) happens at the transform DB-write boundary.

**Tech Stack:** Python stdlib only (`csv`, `zipfile`, `io`, `sqlite3`, `unicodedata`, `re`, `logging`). No new dependencies. Tests use `pytest` + `tmp_path`. The venv is `etl/.venv`; run ETL tests as `cd etl && .venv/bin/python -m pytest -q`; run build tests as `cd build && PYTHONPATH=../etl ../etl/.venv/bin/python -m pytest -q`.

---

## File Map

| Action | Path | Responsibility |
|---|---|---|
| Modify | `etl/transform/db.py` | Add `cpf` to `senator`; add `tse_candidate`, `donor`, `tse_donation` tables |
| Create | `etl/transform/tse/donations.py` | All transform logic: helpers + 4-step pipeline + `run()` |
| Create | `etl/tests/test_tse_donations_transform.py` | All transform tests |
| Create | `build/doadores.py` | Donors ranking build script |
| Create | `build/tests/test_doadores.py` | Build tests for donors ranking |
| Modify | `build/deputados.py` | Add `top_donors` to detail JSON |
| Modify | `build/senadores.py` | Add `top_donors` to detail JSON |
| Modify | `build/tests/test_deputados.py` | Add `top_donors` test |
| Modify | `build/tests/test_senadores.py` | Add `top_donors` test |
| Modify | `docs/glossario.md` | Add new canonical terms |
| Modify | `docs/decisions.md` | Add decision 027 |

---

## Task 1: DB schema — add `senator.cpf` and three new tables

**Files:**
- Modify: `etl/transform/db.py`

- [ ] **Step 1: Add `cpf` column to `senator` and insert the three new tables into SCHEMA**

In `etl/transform/db.py`, make two changes:

*Change 1* — add `cpf TEXT` to the `senator` CREATE TABLE (after `id`, before `name`... actually add it after `email` for minimal diff):

Find the senator table definition and add `cpf TEXT` as the last column:
```sql
CREATE TABLE senator (
  id             INTEGER PRIMARY KEY,
  name           TEXT NOT NULL,
  photo_url      TEXT,
  current_status TEXT,
  civil_name     TEXT,
  date_of_birth  TEXT,
  birth_state    TEXT,
  birth_city     TEXT,
  sex            TEXT,
  email          TEXT,
  cpf            TEXT                   -- nullable; internal only (LGPD); backfilled by TSE transform
);
```

*Change 2* — add DROP + CREATE statements for the three new tables. Insert them just before the final `"""` of the SCHEMA string, after the existing `source` table:

```sql
DROP TABLE IF EXISTS tse_donation;
DROP TABLE IF EXISTS tse_candidate;
DROP TABLE IF EXISTS donor;

CREATE TABLE tse_candidate (
  id              INTEGER PRIMARY KEY,
  election_year   INTEGER NOT NULL,
  office          TEXT NOT NULL,        -- federal_deputy | senator | president
  tse_seq         INTEGER NOT NULL,     -- SQ_CANDIDATO (unique within year)
  cpf             TEXT,                 -- NR_CPF_CANDIDATO; internal only (LGPD)
  name            TEXT NOT NULL,        -- NM_CANDIDATO
  party           TEXT NOT NULL,        -- SG_PARTIDO
  state           TEXT NOT NULL,        -- SG_UF
  election_result TEXT,                 -- elected | not_elected | alternate | invalidated | withdrew | pending | NULL
  deputy_id       INTEGER REFERENCES deputy(id),
  senator_id      INTEGER REFERENCES senator(id),
  UNIQUE(election_year, tse_seq)
);

CREATE TABLE donor (
  id         INTEGER PRIMARY KEY,
  cpf_cnpj   TEXT UNIQUE,              -- nullable (party transfers carry none); internal only (LGPD)
  name       TEXT NOT NULL,
  city       TEXT,
  state      TEXT,
  donor_type TEXT                       -- individual | company | party | unknown
);

CREATE TABLE tse_donation (
  id                INTEGER PRIMARY KEY,
  election_year     INTEGER NOT NULL,
  tse_candidate_id  INTEGER NOT NULL REFERENCES tse_candidate(id),
  donor_id          INTEGER NOT NULL REFERENCES donor(id),
  amount            REAL NOT NULL,
  date              TEXT,               -- ISO-8601 YYYY-MM-DD
  funding_source    TEXT,               -- individual_donation | self_funding | party_transfer |
                                        --   electoral_fund | party_fund | candidate_transfer | other
  receipt_number    TEXT,
  UNIQUE(election_year, receipt_number)
);
```

Also add the three DROP statements to the top of SCHEMA (with the other DROPs), in dependency order — drop children before parents:
```sql
DROP TABLE IF EXISTS tse_donation;
DROP TABLE IF EXISTS tse_candidate;
DROP TABLE IF EXISTS donor;
```
Add these three lines at the top of the SCHEMA string, before `DROP TABLE IF EXISTS name_history`.

- [ ] **Step 2: Run existing ETL tests to confirm schema change doesn't break anything**

```bash
cd etl && .venv/bin/python -m pytest -q
```
Expected: all existing tests pass (the schema is tested indirectly by transform tests that call `create_schema()`).

- [ ] **Step 3: Commit**

```bash
git add etl/transform/db.py
git commit -m "feat(db): add senator.cpf and tse_candidate/donor/tse_donation tables"
```

---

## Task 2: Canonicalization helpers + tests

**Files:**
- Create: `etl/transform/tse/donations.py`
- Create: `etl/tests/test_tse_donations_transform.py`

The `etl/transform/tse/` directory uses namespace packages (no `__init__.py`) — same as all other packages in this project.

- [ ] **Step 1: Write failing tests**

Create `etl/tests/test_tse_donations_transform.py`:

```python
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
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd etl && .venv/bin/python -m pytest tests/test_tse_donations_transform.py -q
```
Expected: `ModuleNotFoundError` or `ImportError` — `transform.tse.donations` doesn't exist yet.

- [ ] **Step 3: Create `etl/transform/tse/donations.py` with helpers**

```python
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
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
cd etl && .venv/bin/python -m pytest tests/test_tse_donations_transform.py -q
```
Expected: all helper tests pass.

- [ ] **Step 5: Commit**

```bash
git add etl/transform/tse/donations.py etl/tests/test_tse_donations_transform.py
git commit -m "feat(tse): add canonicalization helpers for donations transform"
```

---

## Task 3: `load_candidates()` + tests

**Files:**
- Modify: `etl/transform/tse/donations.py`
- Modify: `etl/tests/test_tse_donations_transform.py`

- [ ] **Step 1: Add test for `load_candidates()`**

Add to `etl/tests/test_tse_donations_transform.py` — after the helper tests:

```python
from transform import db as txdb
from transform.tse.donations import load_candidates

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
    # Presidential candidate with two round rows
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
```

Note: `load_candidates(conn, years=(2022,), base=tmp_path)` uses `paths.tse_candidatos_zip_path(2022, base=tmp_path)` which resolves to `tmp_path/tse/candidatos/2022.zip`. The test must write the ZIP there.

- [ ] **Step 2: Run to confirm failure**

```bash
cd etl && .venv/bin/python -m pytest tests/test_tse_donations_transform.py::test_load_candidates_inserts_federal_rows -q
```
Expected: `ImportError` for `load_candidates`.

- [ ] **Step 3: Add `load_candidates()` to `etl/transform/tse/donations.py`**

Append after the helpers section:

```python
# ── Pipeline steps ────────────────────────────────────────────────────────────

def load_candidates(
    conn: sqlite3.Connection,
    years: Sequence[int] = ELECTIONS,
    base: Optional[Path] = None,
) -> None:
    """Load tse_candidate rows from consulta_cand ZIPs (one per year)."""
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
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
cd etl && .venv/bin/python -m pytest tests/test_tse_donations_transform.py -q
```
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add etl/transform/tse/donations.py etl/tests/test_tse_donations_transform.py
git commit -m "feat(tse): add load_candidates() step to donations transform"
```

---

## Task 4: `backfill_senator_cpf()` + tests

**Files:**
- Modify: `etl/transform/tse/donations.py`
- Modify: `etl/tests/test_tse_donations_transform.py`

- [ ] **Step 1: Add tests for `backfill_senator_cpf()`**

Add to the test file (after the `load_candidates` tests):

```python
from transform.tse.donations import backfill_senator_cpf


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
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd etl && .venv/bin/python -m pytest tests/test_tse_donations_transform.py::test_backfill_senator_cpf_matches_by_normalized_name -q
```
Expected: `ImportError` for `backfill_senator_cpf`.

- [ ] **Step 3: Add `backfill_senator_cpf()` to `etl/transform/tse/donations.py`**

Append after `load_candidates()`:

```python
def backfill_senator_cpf(conn: sqlite3.Connection) -> None:
    """Update senator.cpf from tse_candidate for matched senators.

    Matches on normalized civil_name (uppercase, accents stripped). Senators
    with null civil_name are skipped. Unmatched tse_candidate senator rows
    produce a WARNING (expected for senators outside our 2018/2022 scope).
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
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
cd etl && .venv/bin/python -m pytest tests/test_tse_donations_transform.py -q
```
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add etl/transform/tse/donations.py etl/tests/test_tse_donations_transform.py
git commit -m "feat(tse): add backfill_senator_cpf() step"
```

---

## Task 5: `resolve_candidate_fks()` + tests

**Files:**
- Modify: `etl/transform/tse/donations.py`
- Modify: `etl/tests/test_tse_donations_transform.py`

- [ ] **Step 1: Add tests for `resolve_candidate_fks()`**

Append to test file:

```python
from transform.tse.donations import resolve_candidate_fks


def test_resolve_candidate_fks_deputy(tmp_path):
    conn = _db(tmp_path)
    conn.execute(
        "INSERT INTO deputy (id, name, cpf) VALUES (1, 'Ana Silva', '12345678901')"
    )
    conn.execute(
        "INSERT INTO tse_candidate (election_year, office, tse_seq, cpf, name, party, state) "
        "VALUES (2022, 'federal_deputy', 100, '12345678901', 'ANA SILVA', 'PT', 'SP')"
    )
    conn.commit()

    resolve_candidate_fks(conn)

    dep_id = conn.execute(
        "SELECT deputy_id FROM tse_candidate WHERE tse_seq = 100"
    ).fetchone()["deputy_id"]
    assert dep_id == 1


def test_resolve_candidate_fks_senator(tmp_path):
    conn = _db(tmp_path)
    conn.execute(
        "INSERT INTO senator (id, name, cpf) VALUES (10, 'Bruno Lima', '98765432100')"
    )
    conn.execute(
        "INSERT INTO tse_candidate (election_year, office, tse_seq, cpf, name, party, state) "
        "VALUES (2022, 'senator', 200, '98765432100', 'BRUNO LIMA', 'PL', 'RJ')"
    )
    conn.commit()

    resolve_candidate_fks(conn)

    sen_id = conn.execute(
        "SELECT senator_id FROM tse_candidate WHERE tse_seq = 200"
    ).fetchone()["senator_id"]
    assert sen_id == 10


def test_resolve_candidate_fks_president_stays_null(tmp_path):
    conn = _db(tmp_path)
    conn.execute(
        "INSERT INTO tse_candidate (election_year, office, tse_seq, cpf, name, party, state) "
        "VALUES (2022, 'president', 300, '11111111111', 'LULA', 'PT', 'BR')"
    )
    conn.commit()

    resolve_candidate_fks(conn)

    row = conn.execute(
        "SELECT deputy_id, senator_id FROM tse_candidate WHERE tse_seq = 300"
    ).fetchone()
    assert row["deputy_id"] is None
    assert row["senator_id"] is None


def test_resolve_candidate_fks_no_cpf_match_stays_null(tmp_path):
    conn = _db(tmp_path)
    conn.execute(
        "INSERT INTO deputy (id, name, cpf) VALUES (1, 'Ana Silva', '12345678901')"
    )
    # tse_candidate CPF doesn't match any deputy
    conn.execute(
        "INSERT INTO tse_candidate (election_year, office, tse_seq, cpf, name, party, state) "
        "VALUES (2022, 'federal_deputy', 101, '99999999999', 'OUTRO CAND', 'MDB', 'MG')"
    )
    conn.commit()

    resolve_candidate_fks(conn)

    dep_id = conn.execute(
        "SELECT deputy_id FROM tse_candidate WHERE tse_seq = 101"
    ).fetchone()["deputy_id"]
    assert dep_id is None
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd etl && .venv/bin/python -m pytest tests/test_tse_donations_transform.py::test_resolve_candidate_fks_deputy -q
```
Expected: `ImportError` for `resolve_candidate_fks`.

- [ ] **Step 3: Add `resolve_candidate_fks()` to donations.py**

Append after `backfill_senator_cpf()`:

```python
def resolve_candidate_fks(conn: sqlite3.Connection) -> None:
    """Set deputy_id/senator_id FKs on tse_candidate via CPF matching."""
    conn.execute("""
        UPDATE tse_candidate
        SET deputy_id = (
            SELECT id FROM deputy WHERE deputy.cpf = tse_candidate.cpf
        )
        WHERE office = 'federal_deputy' AND tse_candidate.cpf IS NOT NULL
    """)
    conn.execute("""
        UPDATE tse_candidate
        SET senator_id = (
            SELECT id FROM senator WHERE senator.cpf = tse_candidate.cpf
        )
        WHERE office = 'senator' AND tse_candidate.cpf IS NOT NULL
    """)
    conn.commit()
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
cd etl && .venv/bin/python -m pytest tests/test_tse_donations_transform.py -q
```
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add etl/transform/tse/donations.py etl/tests/test_tse_donations_transform.py
git commit -m "feat(tse): add resolve_candidate_fks() step"
```

---

## Task 6: `load_donations()` + `run()` + tests

**Files:**
- Modify: `etl/transform/tse/donations.py`
- Modify: `etl/tests/test_tse_donations_transform.py`

- [ ] **Step 1: Add tests for `load_donations()`**

Append to test file:

```python
from transform.tse.donations import load_donations

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
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd etl && .venv/bin/python -m pytest tests/test_tse_donations_transform.py::test_load_donations_creates_donor_and_donation -q
```
Expected: `ImportError` for `load_donations`.

- [ ] **Step 3: Add `load_donations()` and `run()` to donations.py**

Append after `resolve_candidate_fks()`:

```python
def _get_or_create_donor(
    conn: sqlite3.Connection,
    cpf_cnpj: Optional[str],
    name: str,
    city: Optional[str],
    state: Optional[str],
    donor_type: str,
) -> int:
    """Return existing donor id or insert and return new id."""
    if cpf_cnpj:
        row = conn.execute(
            "SELECT id FROM donor WHERE cpf_cnpj = ?", (cpf_cnpj,)
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT id FROM donor WHERE cpf_cnpj IS NULL AND name = ?", (name,)
        ).fetchone()
    if row:
        return row["id"]
    conn.execute(
        "INSERT INTO donor (cpf_cnpj, name, city, state, donor_type) VALUES (?, ?, ?, ?, ?)",
        (cpf_cnpj, name, city, state, donor_type),
    )
    return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def load_donations(
    conn: sqlite3.Connection,
    years: Sequence[int] = ELECTIONS,
    base: Optional[Path] = None,
) -> None:
    """Load donor + tse_donation rows from receitas_candidatos ZIPs.

    Reads only the BRASIL.csv from each year's ZIP (the per-state CSVs contain
    the same records partitioned by UF — reading both would double-count).
    Raises ValueError if BRASIL.csv is not found.
    """
    for year in years:
        zip_path = paths.tse_receitas_zip_path(year, base=base)
        with zipfile.ZipFile(zip_path) as zf:
            brasil_files = [n for n in zf.namelist() if _BRASIL_RE.match(n)]
            if not brasil_files:
                raise ValueError(
                    f"BRASIL.csv not found in {zip_path}. "
                    f"Found: {zf.namelist()[:5]}"
                )

            with zf.open(brasil_files[0]) as raw:
                text = io.TextIOWrapper(raw, encoding=ENCODING)
                reader = csv.DictReader(text, delimiter=";")
                for row in reader:
                    if row["DS_CARGO"].strip().upper() not in FEDERAL_CARGOS:
                        continue

                    cpf_cnpj = row["NR_CPF_CNPJ_DOADOR"].strip() or None
                    name = (
                        row["NM_DOADOR_RFB"].strip()
                        or row["NM_DOADOR"].strip()
                        or "Doador não identificado"
                    )
                    city = row["NM_MUNICIPIO_DOADOR"].strip() or None
                    state = row["SG_UF_DOADOR"].strip() or None

                    donor_id = _get_or_create_donor(
                        conn, cpf_cnpj, name, city, state, infer_donor_type(cpf_cnpj)
                    )

                    seq = int(row["SQ_CANDIDATO"])
                    cand = conn.execute(
                        "SELECT id FROM tse_candidate "
                        "WHERE election_year = ? AND tse_seq = ?",
                        (year, seq),
                    ).fetchone()
                    if cand is None:
                        log.warning(
                            "load_donations: no tse_candidate for SQ=%d year=%d", seq, year
                        )
                        continue

                    receipt = row["NR_RECIBO_DOACAO"].strip() or None
                    conn.execute(
                        """INSERT OR IGNORE INTO tse_donation
                           (election_year, tse_candidate_id, donor_id, amount,
                            date, funding_source, receipt_number)
                           VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (
                            year,
                            cand["id"],
                            donor_id,
                            parse_br_decimal(row["VR_RECEITA"]),
                            _parse_br_date(row["DT_RECEITA"]),
                            canonicalize_funding_source(row["DS_FONTE_RECEITA"]),
                            receipt,
                        ),
                    )
                text.detach()
        conn.commit()


def run(
    db: Optional[Path] = None,
    years: Sequence[int] = ELECTIONS,
    base: Optional[Path] = None,
) -> None:
    """Full TSE donations transform: candidates → senator CPF backfill → FKs → donations."""
    conn = txdb.connect(db or paths.db_path())
    print("Step 1: loading tse_candidate from consulta_cand...")
    load_candidates(conn, years=years, base=base)
    print("Step 2: backfilling senator.cpf from tse_candidate...")
    backfill_senator_cpf(conn)
    print("Step 3: resolving deputy_id/senator_id FKs...")
    resolve_candidate_fks(conn)
    print("Step 4: loading donor + tse_donation from receitas_candidatos...")
    load_donations(conn, years=years, base=base)
    print("Done.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run()
```

- [ ] **Step 4: Run all ETL tests**

```bash
cd etl && .venv/bin/python -m pytest -q
```
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add etl/transform/tse/donations.py etl/tests/test_tse_donations_transform.py
git commit -m "feat(tse): complete donations transform — load_donations() and run()"
```

---

## Task 7: Glossario + decisions.md

**Files:**
- Modify: `docs/glossario.md`
- Modify: `docs/decisions.md`

- [ ] **Step 1: Add new terms to `docs/glossario.md`**

Under the **Entities / tables** section, add:

```markdown
| `tse_candidate` | candidato TSE | A federal candidate in a TSE election year. |
| `donor` | doador | A unique campaign donor, deduplicated by CPF/CNPJ. |
| `tse_donation` | receita eleitoral | A single campaign donation record from TSE `receitas_candidatos`. |
```

Under the **Columns** section, add:

```markdown
| `office` | cargo / DS_CARGO | The elected office sought: `federal_deputy`, `senator`, or `president`. |
| `election_result` | DS_SIT_TOT_TURNO | Final election outcome: `elected`, `not_elected`, `alternate`, `invalidated`, `withdrew`, `pending`, or NULL. |
| `funding_source` | DS_FONTE_RECEITA | Canonical donation source type: `individual_donation`, `self_funding`, `party_transfer`, `electoral_fund`, `party_fund`, `candidate_transfer`, or `other`. |
| `donor_type` | (derived) | `individual` (CPF, 11 digits), `company` (CNPJ, 14 digits), `party` (no CPF), `unknown` (other length). |
```

- [ ] **Step 2: Add decision 027 to `docs/decisions.md`**

Append after decision 026:

```markdown
**027 — Milestone: TSE donations transform designed.** Three new tables in `pegada.db`:
`tse_candidate` (one row per federal candidate per election year from `consulta_cand`,
with `deputy_id`/`senator_id` FKs resolved via CPF matching), `donor` (one row per
unique donor deduplicated by CPF/CNPJ), `tse_donation` (one row per donation from
`receitas_candidatos` BRASIL.csv). Transform pipeline: load candidates → backfill
`senator.cpf` (closes decision 025 deferral) → resolve FKs → load donations. Build
outputs: `donors_ranking.json` (top 500 donors by total amount, with full recipient
list) and `top_donors` arrays on each deputy/senator detail JSON (top 20 donors).
→ spec: `docs/superpowers/specs/2026-06-06-tse-donations-transform-design.md`
```

- [ ] **Step 3: Commit**

```bash
git add docs/glossario.md docs/decisions.md
git commit -m "docs: add TSE donations terms to glossario and decision 027"
```

---

## Task 8: `build/doadores.py` + tests

**Files:**
- Create: `build/doadores.py`
- Create: `build/tests/test_doadores.py`

- [ ] **Step 1: Write failing test**

Create `build/tests/test_doadores.py`:

```python
"""Build-stage tests: pegada.db -> donors_ranking.json."""
import json
import sqlite3

import pytest

import doadores

SCHEMA = """
CREATE TABLE deputy (id INTEGER PRIMARY KEY, name TEXT);
CREATE TABLE senator (id INTEGER PRIMARY KEY, name TEXT);
CREATE TABLE tse_candidate (
  id INTEGER PRIMARY KEY,
  election_year INTEGER NOT NULL,
  office TEXT NOT NULL,
  tse_seq INTEGER NOT NULL,
  name TEXT NOT NULL,
  party TEXT NOT NULL,
  state TEXT NOT NULL,
  election_result TEXT,
  deputy_id INTEGER,
  senator_id INTEGER
);
CREATE TABLE donor (
  id INTEGER PRIMARY KEY,
  cpf_cnpj TEXT UNIQUE,
  name TEXT NOT NULL,
  city TEXT,
  state TEXT,
  donor_type TEXT
);
CREATE TABLE tse_donation (
  id INTEGER PRIMARY KEY,
  election_year INTEGER NOT NULL,
  tse_candidate_id INTEGER NOT NULL,
  donor_id INTEGER NOT NULL,
  amount REAL NOT NULL,
  date TEXT,
  funding_source TEXT,
  receipt_number TEXT
);
"""


def _fixture_db(path):
    c = sqlite3.connect(str(path))
    c.executescript(SCHEMA)
    c.execute("INSERT INTO deputy (id, name) VALUES (1, 'Ana Silva')")
    c.execute("INSERT INTO deputy (id, name) VALUES (2, 'Bruno Lima')")
    # Candidates
    c.execute(
        "INSERT INTO tse_candidate VALUES (1,2022,'federal_deputy',100,'ANA SILVA','PT','SP','elected',1,NULL)"
    )
    c.execute(
        "INSERT INTO tse_candidate VALUES (2,2022,'federal_deputy',101,'BRUNO LIMA','PL','RJ','elected',2,NULL)"
    )
    c.execute(
        "INSERT INTO tse_candidate VALUES (3,2022,'federal_deputy',102,'CARLOS NETO','MDB','MG','not_elected',NULL,NULL)"
    )
    # Donors
    c.execute(
        "INSERT INTO donor VALUES (1,'12345678901','João Silva','São Paulo','SP','individual')"
    )
    c.execute(
        "INSERT INTO donor VALUES (2,'98765432100','Maria Souza','Rio de Janeiro','RJ','individual')"
    )
    # Donations: donor 1 → Ana (50k) + Bruno (30k) = 80k total; donor 2 → Ana (20k)
    c.execute("INSERT INTO tse_donation VALUES (1,2022,1,1,50000.0,'2022-09-01','individual_donation','R001')")
    c.execute("INSERT INTO tse_donation VALUES (2,2022,2,1,30000.0,'2022-09-02','individual_donation','R002')")
    c.execute("INSERT INTO tse_donation VALUES (3,2022,1,2,20000.0,'2022-09-03','individual_donation','R003')")
    c.commit(); c.close()


def _load_ranking(out_dir):
    return json.loads((out_dir / "donors_ranking.json").read_text(encoding="utf-8"))


def test_ranking_order(tmp_path):
    db = tmp_path / "p.db"; _fixture_db(db)
    out = tmp_path / "out"
    doadores.run(db_path=db, out_dir=out)

    ranking = _load_ranking(out)
    assert ranking["donors"][0]["name"] == "João Silva"       # 80k total
    assert ranking["donors"][0]["total_amount"] == pytest.approx(80000.0)
    assert ranking["donors"][1]["name"] == "Maria Souza"      # 20k total
    assert ranking["donors"][0]["rank"] == 1
    assert ranking["donors"][1]["rank"] == 2


def test_ranking_total_donors_count(tmp_path):
    db = tmp_path / "p.db"; _fixture_db(db)
    out = tmp_path / "out"
    doadores.run(db_path=db, out_dir=out)

    ranking = _load_ranking(out)
    assert ranking["total_donors"] == 2


def test_ranking_donations_include_linked_and_unlinked(tmp_path):
    db = tmp_path / "p.db"; _fixture_db(db)
    out = tmp_path / "out"
    doadores.run(db_path=db, out_dir=out)

    ranking = _load_ranking(out)
    joao = ranking["donors"][0]
    assert len(joao["donations"]) == 2
    # Ana Silva has deputy_id=1 → linked
    ana_donation = next(d for d in joao["donations"] if d["candidate_name"] == "ANA SILVA")
    assert ana_donation["deputy_id"] == 1
    # Bruno Lima has deputy_id=2 → linked
    bruno_donation = next(d for d in joao["donations"] if d["candidate_name"] == "BRUNO LIMA")
    assert bruno_donation["deputy_id"] == 2


def test_ranking_no_cpf_in_output(tmp_path):
    db = tmp_path / "p.db"; _fixture_db(db)
    out = tmp_path / "out"
    doadores.run(db_path=db, out_dir=out)

    raw = (out / "donors_ranking.json").read_text()
    assert "cpf" not in raw.lower()
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd build && PYTHONPATH=../etl ../etl/.venv/bin/python -m pytest tests/test_doadores.py -q
```
Expected: `ModuleNotFoundError` for `doadores`.

- [ ] **Step 3: Create `build/doadores.py`**

```python
"""Build step: generate donors_ranking.json from pegada.db.

Ranks all donors by total campaign donation amount across all election years
and emits the top 500 with their full recipient list.

Run with:
    python build/doadores.py
"""
from __future__ import annotations

import json
import sqlite3
import unicodedata
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
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
cd build && PYTHONPATH=../etl ../etl/.venv/bin/python -m pytest tests/test_doadores.py -q
```
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add build/doadores.py build/tests/test_doadores.py
git commit -m "feat(build): add doadores.py donors ranking build script"
```

---

## Task 9: `build/deputados.py` — add `top_donors` + test

**Files:**
- Modify: `build/deputados.py`
- Modify: `build/tests/test_deputados.py`

- [ ] **Step 1: Add failing test**

Open `build/tests/test_deputados.py`. The existing `SCHEMA` constant at the top defines the tables the build sees. Add the TSE tables to it:

Replace the existing `SCHEMA = """..."""` with:

```python
SCHEMA = """
CREATE TABLE deputy (id INTEGER PRIMARY KEY, name TEXT, photo_url TEXT, current_status TEXT,
  civil_name TEXT, date_of_birth TEXT, date_of_death TEXT, sex TEXT,
  birth_state TEXT, birth_city TEXT, education TEXT, social_media TEXT, website TEXT);
CREATE TABLE mandate (deputy_id INT, legislature INT, state TEXT);
CREATE TABLE party_affiliation (deputy_id INT, party TEXT, start_at TEXT,
  end_at TEXT, legislature INT, source_note TEXT);
CREATE TABLE office_period (deputy_id INT, legislature INT, condition TEXT,
  start_at TEXT, end_at TEXT);
CREATE TABLE name_history (deputy_id INT, name TEXT, start_at TEXT, end_at TEXT);
CREATE TABLE tse_candidate (id INTEGER PRIMARY KEY, election_year INTEGER,
  office TEXT, tse_seq INTEGER, name TEXT, party TEXT, state TEXT,
  election_result TEXT, deputy_id INTEGER, senator_id INTEGER);
CREATE TABLE donor (id INTEGER PRIMARY KEY, cpf_cnpj TEXT, name TEXT,
  city TEXT, state TEXT, donor_type TEXT);
CREATE TABLE tse_donation (id INTEGER PRIMARY KEY, election_year INTEGER,
  tse_candidate_id INTEGER, donor_id INTEGER, amount REAL,
  date TEXT, funding_source TEXT, receipt_number TEXT);
"""
```

Then add a new test function at the end of the file:

```python
def test_top_donors_in_deputy_detail(tmp_path):
    db = tmp_path / "p.db"
    c = sqlite3.connect(str(db))
    c.executescript(SCHEMA)
    c.execute(
        "INSERT INTO deputy (id,name,photo_url,current_status) VALUES (1,'Ana Silva','http://f/1.jpg','in_office')"
    )
    c.execute("INSERT INTO mandate VALUES (1,57,'SP')")
    c.execute("INSERT INTO party_affiliation VALUES (1,'PT','2023-02-01',NULL,57,NULL)")
    c.execute("INSERT INTO office_period VALUES (1,57,'titular','2023-02-01',NULL)")
    c.execute("INSERT INTO name_history VALUES (1,'Ana Silva','2023-02-01',NULL)")
    # TSE data: two donors donated to deputy 1
    c.execute("INSERT INTO tse_candidate VALUES (1,2022,'federal_deputy',100,'ANA SILVA','PT','SP','elected',1,NULL)")
    c.execute("INSERT INTO donor VALUES (1,'12345678901','João Silva','São Paulo','SP','individual')")
    c.execute("INSERT INTO donor VALUES (2,'98765432100','Maria Souza','Campinas','SP','individual')")
    c.execute("INSERT INTO tse_donation VALUES (1,2022,1,1,50000.0,'2022-09-01','individual_donation','R001')")
    c.execute("INSERT INTO tse_donation VALUES (2,2022,1,2,30000.0,'2022-09-02','individual_donation','R002')")
    c.commit(); c.close()

    out = tmp_path / "out"
    deputados.run(db_path=db, out_dir=out)

    d = _load(out, "1.json")
    assert "top_donors" in d
    assert len(d["top_donors"]) == 2
    # João Silva donated most — should be first
    assert d["top_donors"][0]["name"] == "João Silva"
    assert d["top_donors"][0]["total_amount"] == pytest.approx(50000.0)
    assert d["top_donors"][0]["elections"] == [2022]
    assert "cpf" not in str(d["top_donors"])
```

Also add `import pytest` at the top of `build/tests/test_deputados.py` (after the existing `import sqlite3` line), since the new test uses `pytest.approx`.

- [ ] **Step 2: Run to confirm failure**

```bash
cd build && PYTHONPATH=../etl ../etl/.venv/bin/python -m pytest tests/test_deputados.py::test_top_donors_in_deputy_detail -q
```
Expected: FAIL — `top_donors` key missing from output.

- [ ] **Step 3: Modify `build/deputados.py`**

*Change 1* — add a helper function above `build_deputy()`:

```python
def _fetch_top_donors(conn: sqlite3.Connection, deputy_id: int) -> List[Dict[str, Any]]:
    """Return top 20 donors for this deputy, ordered by total amount descending."""
    try:
        rows = conn.execute(
            """
            SELECT d.name, d.city, d.state, d.donor_type,
                   SUM(td.amount) AS total_amount,
                   GROUP_CONCAT(DISTINCT CAST(td.election_year AS TEXT)) AS years_str
            FROM tse_donation td
            JOIN tse_candidate tc ON tc.id = td.tse_candidate_id
            JOIN donor d ON d.id = td.donor_id
            WHERE tc.deputy_id = ?
            GROUP BY d.id
            ORDER BY total_amount DESC
            LIMIT 20
            """,
            (deputy_id,),
        ).fetchall()
    except sqlite3.OperationalError:
        return []   # TSE tables not yet created — graceful degradation

    result = []
    for r in rows:
        years = sorted(int(y) for y in r["years_str"].split(",")) if r["years_str"] else []
        result.append({
            "name": r["name"],
            "city": r["city"],
            "state": r["state"],
            "donor_type": r["donor_type"],
            "total_amount": r["total_amount"],
            "elections": years,
        })
    return result
```

*Change 2* — update `build_deputy()` signature to accept `top_donors`:

```python
def build_deputy(
    dep: sqlite3.Row,
    mandates: List[sqlite3.Row],
    parties: List[sqlite3.Row],
    office_periods: List[sqlite3.Row],
    names: List[sqlite3.Row],
    top_donors: List[Dict[str, Any]],
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
```

*Change 3* — add `"top_donors": top_donors` to the `detail` dict in `build_deputy()`, after `"website"`:

```python
        "website": dep["website"],
        "top_donors": top_donors,
```

*Change 4* — in `run()`, fetch `top_donors` and pass it to `build_deputy()`. Find the line `detail, card = build_deputy(dep, mandates, parties, office_periods, names)` and replace with:

```python
            top_donors = _fetch_top_donors(conn, dep_id)
            detail, card = build_deputy(dep, mandates, parties, office_periods, names, top_donors)
```

- [ ] **Step 4: Run all build tests**

```bash
cd build && PYTHONPATH=../etl ../etl/.venv/bin/python -m pytest -q
```
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add build/deputados.py build/tests/test_deputados.py
git commit -m "feat(build): add top_donors to deputy detail JSON"
```

---

## Task 10: `build/senadores.py` — add `top_donors` + test

**Files:**
- Modify: `build/senadores.py`
- Modify: `build/tests/test_senadores.py`

- [ ] **Step 1: Add failing test**

Open `build/tests/test_senadores.py`. Replace `SCHEMA` with the version that includes TSE tables:

```python
SCHEMA = """
CREATE TABLE senator (id INTEGER PRIMARY KEY, name TEXT, photo_url TEXT, current_status TEXT,
  civil_name TEXT, date_of_birth TEXT, birth_state TEXT, birth_city TEXT, sex TEXT, email TEXT);
CREATE TABLE senate_term (senator_id INT, legislature INT, state TEXT, condition TEXT);
CREATE TABLE senator_party_affiliation (senator_id INT, party TEXT, start_at TEXT,
  end_at TEXT, source_note TEXT);
CREATE TABLE senator_office_period (senator_id INT, legislature INT, condition TEXT,
  start_at TEXT, end_at TEXT, cause TEXT);
CREATE TABLE senator_name_history (senator_id INT, name TEXT, start_at TEXT, end_at TEXT);
CREATE TABLE tse_candidate (id INTEGER PRIMARY KEY, election_year INTEGER,
  office TEXT, tse_seq INTEGER, name TEXT, party TEXT, state TEXT,
  election_result TEXT, deputy_id INTEGER, senator_id INTEGER);
CREATE TABLE donor (id INTEGER PRIMARY KEY, cpf_cnpj TEXT, name TEXT,
  city TEXT, state TEXT, donor_type TEXT);
CREATE TABLE tse_donation (id INTEGER PRIMARY KEY, election_year INTEGER,
  tse_candidate_id INTEGER, donor_id INTEGER, amount REAL,
  date TEXT, funding_source TEXT, receipt_number TEXT);
"""
```

Add new test at the end:

```python
def test_top_donors_in_senator_detail(tmp_path):
    db = tmp_path / "p.db"
    c = sqlite3.connect(str(db))
    c.executescript(SCHEMA)
    c.execute(
        "INSERT INTO senator (id,name,photo_url,current_status,"
        "civil_name,date_of_birth,birth_state,birth_city,sex,email) "
        "VALUES (1,'Alan Rick','http://f/1.jpg','in_office',"
        "'Alan Rick de Oliveira','1978-11-22','AC','Rio Branco','M','alan@senado.leg.br')"
    )
    c.execute("INSERT INTO senate_term VALUES (1,57,'AC','titular')")
    c.execute("INSERT INTO senator_party_affiliation VALUES (1,'UNIÃO','2022-02-24',NULL,NULL)")
    c.execute("INSERT INTO senator_office_period VALUES (1,57,'titular','2023-02-01',NULL,NULL)")
    c.execute("INSERT INTO senator_name_history VALUES (1,'Alan Rick','1900-01-01',NULL)")
    # TSE data
    c.execute("INSERT INTO tse_candidate VALUES (1,2022,'senator',200,'ALAN RICK','UNIÃO','AC','elected',NULL,1)")
    c.execute("INSERT INTO donor VALUES (1,'11122233344','Pedro Costa','Brasília','DF','individual')")
    c.execute("INSERT INTO tse_donation VALUES (1,2022,1,1,25000.0,'2022-08-15','individual_donation','R010')")
    c.commit(); c.close()

    out = tmp_path / "out"
    senadores.run(db_path=db, out_dir=out)

    d = json.loads((out / "senadores" / "1.json").read_text())
    assert "top_donors" in d
    assert len(d["top_donors"]) == 1
    assert d["top_donors"][0]["name"] == "Pedro Costa"
    assert d["top_donors"][0]["total_amount"] == pytest.approx(25000.0)
    assert "cpf" not in str(d["top_donors"])
```

Also add `import pytest` at the top of `build/tests/test_senadores.py` (after the existing `import sqlite3` line), since the new test uses `pytest.approx`.

- [ ] **Step 2: Run to confirm failure**

```bash
cd build && PYTHONPATH=../etl ../etl/.venv/bin/python -m pytest tests/test_senadores.py::test_top_donors_in_senator_detail -q
```
Expected: FAIL.

- [ ] **Step 3: Modify `build/senadores.py`**

*Change 1* — add `_fetch_top_donors_senator()` above `build_senator()`:

```python
def _fetch_top_donors_senator(conn: sqlite3.Connection, senator_id: int) -> List[Dict[str, Any]]:
    """Return top 20 donors for this senator, ordered by total amount descending."""
    try:
        rows = conn.execute(
            """
            SELECT d.name, d.city, d.state, d.donor_type,
                   SUM(td.amount) AS total_amount,
                   GROUP_CONCAT(DISTINCT CAST(td.election_year AS TEXT)) AS years_str
            FROM tse_donation td
            JOIN tse_candidate tc ON tc.id = td.tse_candidate_id
            JOIN donor d ON d.id = td.donor_id
            WHERE tc.senator_id = ?
            GROUP BY d.id
            ORDER BY total_amount DESC
            LIMIT 20
            """,
            (senator_id,),
        ).fetchall()
    except sqlite3.OperationalError:
        return []

    result = []
    for r in rows:
        years = sorted(int(y) for y in r["years_str"].split(",")) if r["years_str"] else []
        result.append({
            "name": r["name"],
            "city": r["city"],
            "state": r["state"],
            "donor_type": r["donor_type"],
            "total_amount": r["total_amount"],
            "elections": years,
        })
    return result
```

*Change 2* — update `build_senator()` signature:

```python
def build_senator(
    sen: sqlite3.Row,
    terms: List[sqlite3.Row],
    parties: List[sqlite3.Row],
    office_periods: List[sqlite3.Row],
    names: List[sqlite3.Row],
    top_donors: List[Dict[str, Any]],
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
```

*Change 3* — add `"top_donors": top_donors` to `detail` dict in `build_senator()`, after `"email"`:

```python
        "email": sen["email"],
        "top_donors": top_donors,
```

*Change 4* — in `run()`, replace `detail, card = build_senator(sen, terms, parties, office_periods, names)` with:

```python
            top_donors = _fetch_top_donors_senator(conn, sid)
            detail, card = build_senator(sen, terms, parties, office_periods, names, top_donors)
```

- [ ] **Step 4: Run all build tests**

```bash
cd build && PYTHONPATH=../etl ../etl/.venv/bin/python -m pytest -q
```
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add build/senadores.py build/tests/test_senadores.py
git commit -m "feat(build): add top_donors to senator detail JSON"
```

---

## Task 11: Full test suite + final commit

- [ ] **Step 1: Run full ETL test suite**

```bash
cd etl && .venv/bin/python -m pytest -q
```
Expected: all tests pass. Fix any failures before continuing.

- [ ] **Step 2: Run full build test suite**

```bash
cd build && PYTHONPATH=../etl ../etl/.venv/bin/python -m pytest -q
```
Expected: all tests pass.

- [ ] **Step 3: Commit (only if there were fixes)**

If no fixes were needed in steps 1–2, skip this step. Otherwise:

```bash
git add -p
git commit -m "fix: resolve any cross-task test failures"
```
