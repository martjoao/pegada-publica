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
