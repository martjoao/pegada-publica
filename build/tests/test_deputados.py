"""Build-stage tests: pegada.db -> static deputy JSON.

The build's only contract is the DB schema, so the fixture DB is created with
inline SQL (no etl import). Canonical English throughout. Covers every branch.
"""
import json
import sqlite3

import deputados

SCHEMA = """
CREATE TABLE deputy (id INTEGER PRIMARY KEY, name TEXT, photo_url TEXT, current_status TEXT);
CREATE TABLE mandate (deputy_id INT, legislature INT, state TEXT);
CREATE TABLE party_affiliation (deputy_id INT, party TEXT, start_at TEXT,
  end_at TEXT, legislature INT, source_note TEXT);
CREATE TABLE office_period (deputy_id INT, legislature INT, condition TEXT,
  start_at TEXT, end_at TEXT);
CREATE TABLE name_history (deputy_id INT, name TEXT, start_at TEXT, end_at TEXT);
"""


def _fixture_db(path):
    c = sqlite3.connect(str(path))
    c.executescript(SCHEMA)
    # 1: migrator titular, currently in office
    c.execute("INSERT INTO deputy VALUES (1,'Adail Filho','http://f/1.jpg','in_office')")
    c.execute("INSERT INTO mandate VALUES (1,57,'AM')")
    c.executemany("INSERT INTO party_affiliation VALUES (?,?,?,?,?,?)", [
        (1, 'REPUBLICANOS', '2023-02-01T00:00', '2026-04-01T14:00', 57, 'início'),
        (1, 'MDB', '2026-04-01T14:00', None, 57, 'Alteração de partido')])
    c.execute("INSERT INTO office_period VALUES (1,57,'titular','2023-02-01T12:05',NULL)")
    c.execute("INSERT INTO name_history VALUES (1,'Adail Filho','2023-02-01T00:00',NULL)")
    # 2: alternate, stepped down (substitute), had a name change
    c.execute("INSERT INTO deputy VALUES (2,'Allan Garcês','http://f/2.jpg','substitute')")
    c.execute("INSERT INTO mandate VALUES (2,57,'MA')")
    c.execute("INSERT INTO party_affiliation VALUES (2,'PP','2023-02-01T00:00',NULL,57,'início')")
    c.execute("INSERT INTO office_period VALUES (2,57,'alternate','2023-09-13T16:01','2024-12-03T10:11')")
    c.executemany("INSERT INTO name_history VALUES (?,?,?,?)", [
        (2, 'Dr. Allan Garcês', '2023-02-01T00:00', '2024-07-18T15:26'),
        (2, 'Allan Garcês', '2024-07-18T15:26', None)])
    # 3: titular on leave
    c.execute("INSERT INTO deputy VALUES (3,'José Licenciado','http://f/3.jpg','on_leave')")
    c.execute("INSERT INTO mandate VALUES (3,57,'SP')")
    c.execute("INSERT INTO party_affiliation VALUES (3,'PT','2023-02-01T00:00',NULL,57,'início')")
    c.execute("INSERT INTO office_period VALUES (3,57,'titular','2023-02-01T12:05','2023-09-13T14:53')")
    c.execute("INSERT INTO name_history VALUES (3,'José Licenciado','2023-02-01T00:00',NULL)")
    # 4: no history fetched — identity + mandate only
    c.execute("INSERT INTO deputy VALUES (4,'Zico Sem Historico','http://f/4.jpg',NULL)")
    c.execute("INSERT INTO mandate VALUES (4,57,'RJ')")
    c.commit(); c.close()


def _load(out_dir, name):
    return json.loads((out_dir / "deputados" / name).read_text(encoding="utf-8"))


def test_detail_migrator_in_office(tmp_path):
    db = tmp_path / "p.db"; _fixture_db(db)
    out = tmp_path / "out"
    deputados.run(db_path=db, out_dir=out)

    d = _load(out, "1.json")
    assert d["current_party"] == "MDB"
    assert d["current_condition"] == "titular"
    assert d["current_status"] == "in_office"
    assert d["in_office"] is True
    assert d["state"] == "AM"
    assert d["legislatures"] == [57]
    assert [p["party"] for p in d["parties"]] == ["REPUBLICANOS", "MDB"]
    assert d["parties"][1]["end"] is None


def test_detail_alternate_stepped_down(tmp_path):
    db = tmp_path / "p.db"; _fixture_db(db)
    out = tmp_path / "out"
    deputados.run(db_path=db, out_dir=out)

    d = _load(out, "2.json")
    assert d["current_status"] == "substitute"
    assert d["in_office"] is False
    assert d["current_condition"] == "alternate"
    assert d["current_party"] == "PP"
    assert [n["name"] for n in d["names"]] == ["Dr. Allan Garcês", "Allan Garcês"]


def test_detail_on_leave_titular(tmp_path):
    db = tmp_path / "p.db"; _fixture_db(db)
    out = tmp_path / "out"
    deputados.run(db_path=db, out_dir=out)

    d = _load(out, "3.json")
    assert d["current_status"] == "on_leave"
    assert d["in_office"] is False
    assert d["current_party"] == "PT"


def test_detail_no_history_is_identity_only(tmp_path):
    db = tmp_path / "p.db"; _fixture_db(db)
    out = tmp_path / "out"
    deputados.run(db_path=db, out_dir=out)

    d = _load(out, "4.json")
    assert d["current_status"] is None
    assert d["current_party"] is None
    assert d["current_condition"] is None
    assert d["in_office"] is False
    assert d["parties"] == [] and d["names"] == []
    assert d["state"] == "RJ"


def test_index_sorted_and_slim(tmp_path):
    db = tmp_path / "p.db"; _fixture_db(db)
    out = tmp_path / "out"
    deputados.run(db_path=db, out_dir=out)

    idx = _load(out, "index.json")
    assert [c["id"] for c in idx] == [1, 2, 3, 4]  # name A–Z
    assert sum(1 for c in idx if c["in_office"]) == 1  # only Adail seated
    assert idx[0] == {"id": 1, "name": "Adail Filho", "photo_url": "http://f/1.jpg",
                      "party": "MDB", "state": "AM", "status": "in_office",
                      "condition": "titular", "in_office": True, "legislatures": [57]}
    assert idx[3]["party"] is None and idx[3]["status"] is None  # no-history deputy
