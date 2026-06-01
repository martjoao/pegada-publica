"""End-to-end transform tests: raw landing files -> canonical SQLite rows.
Raw inputs are PT (verbatim API); the canonical DB is English (see glossary)."""
from common import paths
from common.jsonio import write_json_atomic
from transform import db as txdb
from transform.camara import deputados as txdep


def _hist_entry(dataHora, partido, nome, cond, sit, desc, leg=57):
    return {
        "dataHora": dataHora, "siglaPartido": partido, "nome": nome,
        "condicaoEleitoral": cond, "situacao": sit, "descricaoStatus": desc,
        "idLegislatura": leg,
    }


def _roster_row(dep_id, nome, partido, uf, leg):
    return {"id": dep_id, "nome": nome, "siglaPartido": partido, "siglaUf": uf,
            "urlFoto": f"http://foto/{dep_id}.jpg", "idLegislatura": leg}


def _seed_raw(base):
    write_json_atomic(
        {"_meta": {"source": "camara-dados-abertos", "endpoint": "/deputados",
                   "legislatura": 57, "fetched_at": "2026-05-31T00:00:00Z"},
         "dados": [
             # roster's first-seen name is the OLD one; history must override it
             _roster_row(226708, "Dr. Allan Garcês", "PP", "MA", 57),
             _roster_row(226708, "Allan Garcês", "PP", "MA", 57),
             _roster_row(220714, "Adail Filho", "REPUBLICANOS", "AM", 57),
             _roster_row(220714, "Adail Filho", "MDB", "AM", 57),
         ]},
        paths.camara_deputados_path(57, base=base),
    )
    write_json_atomic(
        {"_meta": {"legislatura": 56}, "dados": []},
        paths.camara_deputados_path(56, base=base),
    )
    # historico: Allan Garcês (alternate, name change, currently stepped down)
    write_json_atomic(
        {"_meta": {"deputy_id": 226708}, "dados": [
            _hist_entry("2023-02-01T00:00", "PP", "Dr. Allan Garcês", None, None,
                        "Partido no início da legislatura / Nome no início da legislatura"),
            _hist_entry("2023-09-13T16:01", "PP", "Dr. Allan Garcês", "Suplente", "Exercício",
                        "Entrada - Posse de Suplente - Posse como Suplente"),
            _hist_entry("2024-07-18T15:26", "PP", "Allan Garcês", "Suplente", "Exercício",
                        "Alteração de nome parlamentar"),
            _hist_entry("2024-12-03T10:11", "PP", "Allan Garcês", "Suplente", "Suplência",
                        "Saída - Afastamento sem prazo determinado - Afastamento de Suplente (automático)"),
        ]},
        paths.camara_historico_path(226708, base=base),
    )
    # historico: Adail Filho (party migration REPUBLICANOS -> MDB, currently in office)
    write_json_atomic(
        {"_meta": {"deputy_id": 220714}, "dados": [
            _hist_entry("2023-02-01T00:00", "REPUBLICANOS", "Adail Filho", None, None,
                        "Partido no início da legislatura / Nome no início da legislatura"),
            _hist_entry("2023-02-01T12:05", "REPUBLICANOS", "Adail Filho", "Titular", "Exercício",
                        "Entrada - Posse de Eleito Titular - Posse na Sessão Preparatória"),
            _hist_entry("2026-04-01T14:00", "MDB", "Adail Filho", "Titular", "Exercício",
                        "Alteração de partido"),
        ]},
        paths.camara_historico_path(220714, base=base),
    )


def test_create_schema_creates_all_tables(tmp_path):
    conn = txdb.connect(tmp_path / "t.db")
    txdb.create_schema(conn)
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"deputy", "mandate", "office_period", "party_affiliation",
            "name_history", "source"} <= tables


def test_transform_dedups_and_builds_canonical_rows(tmp_path):
    _seed_raw(tmp_path)
    conn = txdb.connect(tmp_path / "pegada.db")
    txdb.create_schema(conn)

    txdep.transform(conn, raw_base=tmp_path)

    n = lambda t: conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
    assert n("deputy") == 2              # 4 roster rows deduped to 2 ids
    assert n("mandate") == 2
    assert n("party_affiliation") == 3   # Garcês 1 + Adail 2
    assert n("office_period") == 2       # Garcês 1 + Adail 1
    assert n("name_history") == 3        # Garcês 2 + Adail 1

    row = conn.execute(
        "SELECT name, current_status FROM deputy WHERE id=226708").fetchone()
    assert row["name"] == "Allan Garcês"      # latest name, not roster order
    assert row["current_status"] == "substitute"
    assert conn.execute(
        "SELECT current_status FROM deputy WHERE id=220714").fetchone()[0] == "in_office"


def test_transform_supports_party_at_vote_time_query(tmp_path):
    _seed_raw(tmp_path)
    conn = txdb.connect(tmp_path / "pegada.db")
    txdb.create_schema(conn)
    txdep.transform(conn, raw_base=tmp_path)

    def party_at(dep_id, ts):
        return conn.execute(
            "SELECT party FROM party_affiliation "
            "WHERE deputy_id=? AND ?>=start_at AND (?<end_at OR end_at IS NULL)",
            (dep_id, ts, ts),
        ).fetchone()[0]

    assert party_at(220714, "2024-01-01T00:00") == "REPUBLICANOS"
    assert party_at(220714, "2026-05-01T00:00") == "MDB"


def test_transform_keeps_older_legislatures_capped_at_term_end(tmp_path):
    # A veteran's older terms are kept, but a gap (terms not served) must NOT be
    # absorbed: the leg-49 affiliation ends at the 49ª term end, not at 2023.
    write_json_atomic(
        {"_meta": {}, "dados": [_roster_row(99, "Veterano", "PSDB", "MG", 57)]},
        paths.camara_deputados_path(57, base=tmp_path))
    write_json_atomic({"_meta": {}, "dados": []},
                      paths.camara_deputados_path(56, base=tmp_path))
    write_json_atomic(
        {"_meta": {"deputy_id": 99}, "dados": [
            _hist_entry("1991-02-01T00:00", "PMDB", "Veterano", None, None,
                        "Partido no início da legislatura", leg=49),
            _hist_entry("2023-02-01T00:00", "PSDB", "Veterano", None, None,
                        "Partido no início da legislatura", leg=57),
            _hist_entry("2023-02-01T12:05", "PSDB", "Veterano", "Titular", "Exercício",
                        "Entrada - Posse de Eleito Titular", leg=57),
        ]},
        paths.camara_historico_path(99, base=tmp_path))

    conn = txdb.connect(tmp_path / "p.db")
    txdb.create_schema(conn)
    txdep.transform(conn, raw_base=tmp_path)

    rows = [tuple(r) for r in conn.execute(
        "SELECT party, start_at, end_at, legislature FROM party_affiliation "
        "WHERE deputy_id=99 ORDER BY start_at")]
    assert rows == [
        ("PMDB", "1991-02-01T00:00", "1995-02-01T00:00", 49),  # capped at 49ª end
        ("PSDB", "2023-02-01T00:00", None, 57),
    ]


def test_transform_is_idempotent(tmp_path):
    _seed_raw(tmp_path)
    conn = txdb.connect(tmp_path / "pegada.db")
    txdb.create_schema(conn)
    txdep.transform(conn, raw_base=tmp_path)
    txdep.transform(conn, raw_base=tmp_path)  # second run must not duplicate

    assert conn.execute("SELECT count(*) FROM deputy").fetchone()[0] == 2
    assert conn.execute("SELECT count(*) FROM party_affiliation").fetchone()[0] == 3
