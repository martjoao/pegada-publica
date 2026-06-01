"""End-to-end transform tests: raw Senado landing files -> canonical SQLite rows.
Raw inputs are PT (verbatim API); the canonical DB is English (see glossary)."""
from common import paths
from common.jsonio import write_json_atomic
from transform import db as txdb
from transform.senado import senadores as txsen


def _roster_row(cod, nome, partido="PT", uf="AC"):
    return {"IdentificacaoParlamentar": {
        "CodigoParlamentar": str(cod), "NomeParlamentar": nome,
        "SiglaPartidoParlamentar": partido, "UfParlamentar": uf,
        "UrlFotoParlamentar": f"http://foto/{cod}.jpg"}}


def _mandatos_payload(cod, mandato):
    return {"_meta": {"codigo": cod}, "dados": {
        "MandatoParlamentar": {"Parlamentar": {"Mandatos": {"Mandato": mandato}}}}}


def _filiacoes_payload(cod, filiacoes):
    return {"_meta": {"codigo": cod}, "dados": {
        "FiliacaoParlamentar": {"Parlamentar": {"Filiacoes": {"Filiacao": filiacoes}}}}}


def _seed(base):
    # roster: leg 57 has senators 5672 (in office) and 6358 (suplente, stepped back)
    write_json_atomic(
        {"_meta": {"source": "senado-dados-abertos", "legislatura": 57,
                   "fetched_at": "2026-06-01T00:00:00Z"},
         "dados": [_roster_row(5672, "Alan Rick", "REPUBLICANOS", "AC"),
                   _roster_row(6358, "Ana Paula Lobato", "PDT", "MA")]},
        paths.senado_lista_path(57, base=base))
    write_json_atomic({"_meta": {"legislatura": 56}, "dados": []},
                      paths.senado_lista_path(56, base=base))

    # 5672 Alan Rick — titular, open current exercicio, party migration history
    write_json_atomic(_mandatos_payload(5672, {
        "UfParlamentar": "AC", "DescricaoParticipacao": "Titular",
        "PrimeiraLegislaturaDoMandato": {"NumeroLegislatura": "57", "DataFim": "2027-01-31"},
        "SegundaLegislaturaDoMandato": {"NumeroLegislatura": "58", "DataFim": "2031-01-31"},
        "Exercicios": {"Exercicio": {"DataInicio": "2023-02-01"}}}),
        paths.senado_mandatos_path(5672, base=base))
    write_json_atomic(_filiacoes_payload(5672, [
        {"Partido": {"SiglaPartido": "REPUBLICANOS"}, "DataFiliacao": "2025-11-12"},
        {"Partido": {"SiglaPartido": "UNIÃO"}, "DataFiliacao": "2022-02-24",
         "DataDesfiliacao": "2025-11-10"}]),
        paths.senado_filiacoes_path(5672, base=base))

    # 6358 Ana Paula Lobato — suplente, served then titular returned (RET)
    write_json_atomic(_mandatos_payload(6358, {
        "UfParlamentar": "MA", "DescricaoParticipacao": "1º Suplente",
        "PrimeiraLegislaturaDoMandato": {"NumeroLegislatura": "57", "DataFim": "2027-01-31"},
        "SegundaLegislaturaDoMandato": {"NumeroLegislatura": "58", "DataFim": "2031-01-31"},
        "Exercicios": {"Exercicio": {"DataInicio": "2023-02-02", "DataFim": "2024-01-31",
                                     "SiglaCausaAfastamento": "RET",
                                     "DescricaoCausaAfastamento": "Retorno do titular"}}}),
        paths.senado_mandatos_path(6358, base=base))
    write_json_atomic(_filiacoes_payload(6358,
        {"Partido": {"SiglaPartido": "PDT"}, "DataFiliacao": "2018-01-01"}),
        paths.senado_filiacoes_path(6358, base=base))


def test_create_schema_creates_senator_tables(tmp_path):
    conn = txdb.connect(tmp_path / "t.db")
    txdb.create_schema(conn)
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"senator", "senate_term", "senator_office_period",
            "senator_party_affiliation", "senator_name_history"} <= tables
    # deputy tables must still exist (regression — deputy pipeline untouched)
    assert {"deputy", "mandate", "office_period", "party_affiliation",
            "name_history"} <= tables


def test_transform_builds_canonical_senator_rows(tmp_path):
    _seed(tmp_path)
    conn = txdb.connect(tmp_path / "pegada.db")
    txdb.create_schema(conn)
    txsen.transform(conn, raw_base=tmp_path, today="2026-06-01")

    n = lambda t: conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
    assert n("senator") == 2
    assert n("senate_term") == 4              # each senator spans 57 + 58
    assert n("senator_office_period") == 2    # one exercicio each
    assert n("senator_party_affiliation") == 3  # Alan 2 + Ana 1

    alan = conn.execute("SELECT name, current_status FROM senator WHERE id=5672").fetchone()
    assert alan["name"] == "Alan Rick"
    assert alan["current_status"] == "in_office"      # open current exercicio
    ana = conn.execute("SELECT current_status FROM senator WHERE id=6358").fetchone()
    assert ana["current_status"] == "substitute"      # titular returned (RET)

    cond = conn.execute(
        "SELECT condition FROM senate_term WHERE senator_id=6358 AND legislature=57").fetchone()[0]
    assert cond == "alternate"


def test_transform_supports_party_at_date_query(tmp_path):
    _seed(tmp_path)
    conn = txdb.connect(tmp_path / "pegada.db")
    txdb.create_schema(conn)
    txsen.transform(conn, raw_base=tmp_path, today="2026-06-01")

    def party_at(sid, ts):
        return conn.execute(
            "SELECT party FROM senator_party_affiliation "
            "WHERE senator_id=? AND ?>=start_at AND (?<end_at OR end_at IS NULL)",
            (sid, ts, ts)).fetchone()[0]

    assert party_at(5672, "2024-01-01") == "UNIÃO"
    assert party_at(5672, "2026-01-01") == "REPUBLICANOS"


def test_transform_is_idempotent(tmp_path):
    _seed(tmp_path)
    conn = txdb.connect(tmp_path / "pegada.db")
    txdb.create_schema(conn)
    txsen.transform(conn, raw_base=tmp_path, today="2026-06-01")
    txsen.transform(conn, raw_base=tmp_path, today="2026-06-01")

    assert conn.execute("SELECT count(*) FROM senator").fetchone()[0] == 2
    assert conn.execute("SELECT count(*) FROM senator_party_affiliation").fetchone()[0] == 3
