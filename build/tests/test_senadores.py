"""Build-stage tests: pegada.db -> static senator JSON.

The build's only contract is the DB schema, so the fixture DB is created with
inline SQL (no etl import). Canonical English throughout. Covers every branch.
"""
import json
import sqlite3

import pytest
import senadores

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


def _fixture_db(path):
    c = sqlite3.connect(str(path))
    c.executescript(SCHEMA)
    # 1: titular in office, party migration; mandate spans 57 + 58 — has full bio
    c.execute(
        "INSERT INTO senator (id,name,photo_url,current_status,"
        "civil_name,date_of_birth,birth_state,birth_city,sex,email) "
        "VALUES (1,'Alan Rick','http://f/1.jpg','in_office',"
        "'Alan Rick de Oliveira','1978-11-22','AC','Rio Branco','M','alan@senado.leg.br')"
    )
    c.executemany("INSERT INTO senate_term VALUES (?,?,?,?)", [
        (1, 57, 'AC', 'titular'), (1, 58, 'AC', 'titular')])
    c.executemany("INSERT INTO senator_party_affiliation VALUES (?,?,?,?,?)", [
        (1, 'UNIÃO', '2022-02-24', '2025-11-10', None),
        (1, 'REPUBLICANOS', '2025-11-12', None, None)])
    c.execute("INSERT INTO senator_office_period VALUES (1,57,'titular','2023-02-01',NULL,NULL)")
    c.execute("INSERT INTO senator_name_history VALUES (1,'Alan Rick','1900-01-01',NULL)")
    # 2: suplente, stepped back (substitute) — no bio
    c.execute("INSERT INTO senator (id,name,photo_url,current_status) VALUES (2,'Ana Paula Lobato','http://f/2.jpg','substitute')")
    c.executemany("INSERT INTO senate_term VALUES (?,?,?,?)", [
        (2, 57, 'MA', 'alternate'), (2, 58, 'MA', 'alternate')])
    c.execute("INSERT INTO senator_party_affiliation VALUES (2,'PDT','2018-01-01',NULL,NULL)")
    c.execute("INSERT INTO senator_office_period VALUES (2,57,'alternate','2023-02-02','2024-01-31','Retorno do titular')")
    c.execute("INSERT INTO senator_name_history VALUES (2,'Ana Paula Lobato','1900-01-01',NULL)")
    # 3: suplente who never assumed — identity + term only, null status, no bio
    c.execute("INSERT INTO senator (id,name,photo_url,current_status) VALUES (3,'Zico Suplente','http://f/3.jpg',NULL)")
    c.execute("INSERT INTO senate_term VALUES (3,57,'RJ','alternate')")
    c.execute("INSERT INTO senator_name_history VALUES (3,'Zico Suplente','1900-01-01',NULL)")
    c.commit(); c.close()


def _load(out_dir, name):
    return json.loads((out_dir / "senadores" / name).read_text(encoding="utf-8"))


def test_detail_titular_in_office(tmp_path):
    db = tmp_path / "p.db"; _fixture_db(db)
    out = tmp_path / "out"
    senadores.run(db_path=db, out_dir=out)

    d = _load(out, "1.json")
    assert d["current_party"] == "REPUBLICANOS"
    assert d["current_condition"] == "titular"
    assert d["current_status"] == "in_office"
    assert d["in_office"] is True
    assert d["state"] == "AC"
    assert d["legislatures"] == [57, 58]
    assert [p["party"] for p in d["parties"]] == ["UNIÃO", "REPUBLICANOS"]
    assert d["parties"][1]["end"] is None


def test_detail_suplente_stepped_back(tmp_path):
    db = tmp_path / "p.db"; _fixture_db(db)
    out = tmp_path / "out"
    senadores.run(db_path=db, out_dir=out)

    d = _load(out, "2.json")
    assert d["current_status"] == "substitute"
    assert d["in_office"] is False
    assert d["current_condition"] == "alternate"
    assert d["current_party"] == "PDT"
    assert d["office_periods"][0]["cause"] == "Retorno do titular"


def test_detail_never_assumed_is_identity_only(tmp_path):
    db = tmp_path / "p.db"; _fixture_db(db)
    out = tmp_path / "out"
    senadores.run(db_path=db, out_dir=out)

    d = _load(out, "3.json")
    assert d["current_status"] is None
    assert d["current_party"] is None
    assert d["current_condition"] == "alternate"  # known from the term, even unassumed
    assert d["in_office"] is False
    assert d["parties"] == [] and d["office_periods"] == []
    assert d["state"] == "RJ"


def test_index_sorted_and_slim(tmp_path):
    db = tmp_path / "p.db"; _fixture_db(db)
    out = tmp_path / "out"
    senadores.run(db_path=db, out_dir=out)

    idx = _load(out, "index.json")
    assert [c["id"] for c in idx] == [1, 2, 3]  # name A–Z
    assert sum(1 for c in idx if c["in_office"]) == 1  # only Alan seated
    assert idx[0] == {"id": 1, "name": "Alan Rick", "photo_url": "http://f/1.jpg",
                      "party": "REPUBLICANOS", "state": "AC", "status": "in_office",
                      "condition": "titular", "in_office": True, "legislatures": [57, 58]}
    assert idx[2]["party"] is None and idx[2]["status"] is None


def test_detail_bio_fields(tmp_path):
    db = tmp_path / "p.db"; _fixture_db(db)
    out = tmp_path / "out"
    senadores.run(db_path=db, out_dir=out)

    d = _load(out, "1.json")
    assert d["civil_name"] == "Alan Rick de Oliveira"
    assert d["date_of_birth"] == "1978-11-22"
    assert d["birth_state"] == "AC"
    assert d["birth_city"] == "Rio Branco"
    assert d["sex"] == "M"
    assert d["email"] == "alan@senado.leg.br"

    d3 = _load(out, "3.json")
    assert d3["civil_name"] is None
    assert d3["email"] is None


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
