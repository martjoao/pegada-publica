"""Build-stage tests: pegada.db -> static deputy JSON.

The build's only contract is the DB schema, so the fixture DB is created with
inline SQL (no etl import). Covers every derivation branch.
"""
import json
import sqlite3

import deputados

SCHEMA = """
CREATE TABLE deputado (id INTEGER PRIMARY KEY, nome TEXT, foto_url TEXT);
CREATE TABLE mandato (deputy_id INT, legislatura INT, uf TEXT);
CREATE TABLE party_membership (deputy_id INT, sigla_partido TEXT, start_at TEXT,
  end_at TEXT, legislatura INT, descricao_origem TEXT);
CREATE TABLE exercicio (deputy_id INT, legislatura INT, condicao TEXT,
  start_at TEXT, end_at TEXT);
CREATE TABLE name_history (deputy_id INT, nome TEXT, start_at TEXT, end_at TEXT);
"""


def _fixture_db(path):
    c = sqlite3.connect(str(path))
    c.executescript(SCHEMA)
    # 1: migrator titular, currently in exercise
    c.execute("INSERT INTO deputado VALUES (1,'Adail Filho','http://f/1.jpg')")
    c.execute("INSERT INTO mandato VALUES (1,57,'AM')")
    c.executemany("INSERT INTO party_membership VALUES (?,?,?,?,?,?)", [
        (1, 'REPUBLICANOS', '2023-02-01T00:00', '2026-04-01T14:00', 57, 'início'),
        (1, 'MDB', '2026-04-01T14:00', None, 57, 'Alteração de partido')])
    c.execute("INSERT INTO exercicio VALUES (1,57,'Titular','2023-02-01T12:05',NULL)")
    c.execute("INSERT INTO name_history VALUES (1,'Adail Filho','2023-02-01T00:00',NULL)")
    # 2: suplente, stepped down (not in exercise now), had a name change
    c.execute("INSERT INTO deputado VALUES (2,'Allan Garcês','http://f/2.jpg')")
    c.execute("INSERT INTO mandato VALUES (2,57,'MA')")
    c.execute("INSERT INTO party_membership VALUES (2,'PP','2023-02-01T00:00',NULL,57,'início')")
    c.execute("INSERT INTO exercicio VALUES (2,57,'Suplente','2023-09-13T16:01','2024-12-03T10:11')")
    c.executemany("INSERT INTO name_history VALUES (?,?,?,?)", [
        (2, 'Dr. Allan Garcês', '2023-02-01T00:00', '2024-07-18T15:26'),
        (2, 'Allan Garcês', '2024-07-18T15:26', None)])
    # 3: titular on leave (licenciado) — last exercise interval closed
    c.execute("INSERT INTO deputado VALUES (3,'José Licenciado','http://f/3.jpg')")
    c.execute("INSERT INTO mandato VALUES (3,57,'SP')")
    c.execute("INSERT INTO party_membership VALUES (3,'PT','2023-02-01T00:00',NULL,57,'início')")
    c.execute("INSERT INTO exercicio VALUES (3,57,'Titular','2023-02-01T12:05','2023-09-13T14:53')")
    c.execute("INSERT INTO name_history VALUES (3,'José Licenciado','2023-02-01T00:00',NULL)")
    # 4: no history fetched — identity + mandate only
    c.execute("INSERT INTO deputado VALUES (4,'Zico Sem Historico','http://f/4.jpg')")
    c.execute("INSERT INTO mandato VALUES (4,57,'RJ')")
    c.commit(); c.close()


def _load(out_dir, name):
    return json.loads((out_dir / "deputados" / name).read_text(encoding="utf-8"))


def test_detail_migrator_in_exercise(tmp_path):
    db = tmp_path / "p.db"; _fixture_db(db)
    out = tmp_path / "out"
    deputados.run(db_path=db, out_dir=out)

    d = _load(out, "1.json")
    assert d["partido_atual"] == "MDB"
    assert d["condicao_atual"] == "Titular"
    assert d["status_atual"] == "em_exercicio"
    assert d["em_exercicio"] is True
    assert d["uf"] == "AM"
    assert d["legislaturas"] == [57]
    assert [p["sigla"] for p in d["partidos"]] == ["REPUBLICANOS", "MDB"]
    assert d["partidos"][1]["fim"] is None


def test_detail_suplente_stepped_down(tmp_path):
    db = tmp_path / "p.db"; _fixture_db(db)
    out = tmp_path / "out"
    deputados.run(db_path=db, out_dir=out)

    d = _load(out, "2.json")
    assert d["status_atual"] == "suplente"
    assert d["em_exercicio"] is False
    assert d["condicao_atual"] is None
    assert d["partido_atual"] == "PP"
    assert [n["nome"] for n in d["nomes"]] == ["Dr. Allan Garcês", "Allan Garcês"]


def test_detail_licenciado_titular(tmp_path):
    db = tmp_path / "p.db"; _fixture_db(db)
    out = tmp_path / "out"
    deputados.run(db_path=db, out_dir=out)

    d = _load(out, "3.json")
    assert d["status_atual"] == "licenciado"
    assert d["em_exercicio"] is False
    assert d["partido_atual"] == "PT"


def test_detail_no_history_is_identity_only(tmp_path):
    db = tmp_path / "p.db"; _fixture_db(db)
    out = tmp_path / "out"
    deputados.run(db_path=db, out_dir=out)

    d = _load(out, "4.json")
    assert d["status_atual"] is None
    assert d["partido_atual"] is None
    assert d["condicao_atual"] is None
    assert d["em_exercicio"] is False
    assert d["partidos"] == [] and d["nomes"] == []
    assert d["uf"] == "RJ"


def test_index_sorted_and_slim(tmp_path):
    db = tmp_path / "p.db"; _fixture_db(db)
    out = tmp_path / "out"
    deputados.run(db_path=db, out_dir=out)

    idx = _load(out, "index.json")
    assert [c["id"] for c in idx] == [1, 2, 3, 4]  # Nome A–Z
    assert sum(1 for c in idx if c["em_exercicio"]) == 1  # only Adail seated
    card = idx[0]
    assert card == {"id": 1, "nome": "Adail Filho", "partido": "MDB", "uf": "AM",
                    "status": "em_exercicio", "condicao": "Titular",
                    "em_exercicio": True, "legislaturas": [57]}
    assert idx[3]["partido"] is None and idx[3]["status"] is None  # no-history deputy
