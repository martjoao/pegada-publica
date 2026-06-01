import json

import responses

from common import paths
from common.http_client import SenadoClient
from common.jsonio import write_json_atomic
from extract.senado import detalhe

BASE = "https://legis.senado.leg.br/dadosabertos"


def _mandatos(cod):
    return {"MandatoParlamentar": {"Parlamentar": {"Codigo": str(cod)}}}


def _filiacoes(cod):
    return {"FiliacaoParlamentar": {"Parlamentar": {"Codigo": str(cod)}}}


def test_build_payload_wraps_with_meta():
    payload = detalhe.build_payload("mandatos", 5672, {"x": 1},
                                    fetched_at="2026-06-01T00:00:00Z")
    assert payload["dados"] == {"x": 1}
    meta = payload["_meta"]
    assert meta["source"] == "senado-dados-abertos"
    assert meta["endpoint"] == "/senador/5672/mandatos"
    assert meta["codigo"] == 5672
    assert meta["fetched_at"] == "2026-06-01T00:00:00Z"


@responses.activate
def test_run_writes_mandatos_and_filiacoes_per_senator(tmp_path):
    for cod in (10, 20):
        responses.add(responses.GET, f"{BASE}/senador/{cod}/mandatos",
                      json=_mandatos(cod), status=200)
        responses.add(responses.GET, f"{BASE}/senador/{cod}/filiacoes",
                      json=_filiacoes(cod), status=200)

    client = SenadoClient(backoff_base=0, page_delay=0)
    written = detalhe.run(client=client, codigos=[10, 20], out_dir=tmp_path, delay=0)

    assert len(written) == 4  # 2 senators x 2 resources
    m10 = json.loads(paths.senado_mandatos_path(10, base=tmp_path).read_text())
    f10 = json.loads(paths.senado_filiacoes_path(10, base=tmp_path).read_text())
    assert m10["_meta"]["codigo"] == 10
    assert m10["dados"]["MandatoParlamentar"]["Parlamentar"]["Codigo"] == "10"
    assert f10["dados"]["FiliacaoParlamentar"]["Parlamentar"]["Codigo"] == "10"


def test_run_skips_already_written(tmp_path):
    # both resources of senator 10 already on disk -> a resumed run refetches neither
    write_json_atomic({"_meta": {"codigo": 10}, "dados": "SENTINEL"},
                      paths.senado_mandatos_path(10, base=tmp_path))
    write_json_atomic({"_meta": {"codigo": 10}, "dados": "SENTINEL"},
                      paths.senado_filiacoes_path(10, base=tmp_path))

    with responses.RequestsMock() as rsps:
        rsps.add(rsps.GET, f"{BASE}/senador/20/mandatos", json=_mandatos(20), status=200)
        rsps.add(rsps.GET, f"{BASE}/senador/20/filiacoes", json=_filiacoes(20), status=200)
        client = SenadoClient(backoff_base=0, page_delay=0)
        written = detalhe.run(client=client, codigos=[10, 20], out_dir=tmp_path,
                              delay=0, skip_existing=True)

    assert paths.senado_mandatos_path(20, base=tmp_path) in written
    assert paths.senado_mandatos_path(10, base=tmp_path) not in written
    assert json.loads(paths.senado_mandatos_path(10, base=tmp_path).read_text())["dados"] == "SENTINEL"


@responses.activate
def test_run_tolerates_individual_failures(tmp_path):
    responses.add(responses.GET, f"{BASE}/senador/10/mandatos", json={"e": 1}, status=500)
    responses.add(responses.GET, f"{BASE}/senador/10/filiacoes", json=_filiacoes(10), status=200)
    responses.add(responses.GET, f"{BASE}/senador/20/mandatos", json=_mandatos(20), status=200)
    responses.add(responses.GET, f"{BASE}/senador/20/filiacoes", json=_filiacoes(20), status=200)

    client = SenadoClient(backoff_base=0, page_delay=0)
    written = detalhe.run(client=client, codigos=[10, 20], out_dir=tmp_path, delay=0)

    # the failed mandatos/10 must not abort; the other three are written
    assert not paths.senado_mandatos_path(10, base=tmp_path).exists()
    assert paths.senado_filiacoes_path(10, base=tmp_path).exists()
    assert paths.senado_mandatos_path(20, base=tmp_path).exists()
    assert paths.senado_filiacoes_path(20, base=tmp_path).exists()


def test_codigos_default_to_roster(tmp_path):
    from extract.senado import lista
    lista.save_payload(lista.build_payload(57, [
        {"IdentificacaoParlamentar": {"CodigoParlamentar": "7"}},
    ]), paths.senado_lista_path(57, base=tmp_path))

    with responses.RequestsMock() as rsps:
        rsps.add(rsps.GET, f"{BASE}/senador/7/mandatos", json=_mandatos(7), status=200)
        rsps.add(rsps.GET, f"{BASE}/senador/7/filiacoes", json=_filiacoes(7), status=200)
        client = SenadoClient(backoff_base=0, page_delay=0)
        written = detalhe.run(client=client, raw_base=tmp_path, out_dir=tmp_path, delay=0)

    assert paths.senado_mandatos_path(7, base=tmp_path) in written
