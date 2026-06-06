import json

import responses

from common import paths
from common.http_client import SenadoClient
from common.jsonio import write_json_atomic
from extract.senado import bio, lista

BASE = "https://legis.senado.leg.br/dadosabertos"


def _bio_response(codigo):
    return {"DetalheParlamentar": {"Parlamentar": {"CodigoParlamentar": str(codigo)}}}


def test_build_payload_wraps_with_meta():
    data = _bio_response(5672)
    payload = bio.build_payload(5672, data, fetched_at="2026-06-06T12:00:00Z")

    assert payload["dados"] == data
    meta = payload["_meta"]
    assert meta["source"] == "senado-dados-abertos"
    assert meta["endpoint"] == "/senador/5672"
    assert meta["codigo"] == 5672
    assert meta["fetched_at"] == "2026-06-06T12:00:00Z"


@responses.activate
def test_run_writes_one_file_per_senator(tmp_path):
    for cod in (10, 20):
        responses.add(responses.GET, f"{BASE}/senador/{cod}",
                      json=_bio_response(cod), status=200)

    client = SenadoClient(backoff_base=0, page_delay=0)
    written = bio.run(client=client, codigos=[10, 20], out_dir=tmp_path, delay=0)

    assert len(written) == 2
    f10 = json.loads(paths.senado_bio_path(10, base=tmp_path).read_text())
    assert f10["_meta"]["codigo"] == 10
    assert f10["dados"]["DetalheParlamentar"]["Parlamentar"]["CodigoParlamentar"] == "10"


def test_run_skips_already_written(tmp_path):
    existing = paths.senado_bio_path(10, base=tmp_path)
    write_json_atomic({"_meta": {"codigo": 10}, "dados": "SENTINEL"}, existing)

    with responses.RequestsMock() as rsps:
        rsps.add(rsps.GET, f"{BASE}/senador/20", json=_bio_response(20), status=200)
        client = SenadoClient(backoff_base=0, page_delay=0)
        written = bio.run(client=client, codigos=[10, 20],
                          out_dir=tmp_path, delay=0, skip_existing=True)

    assert written == [paths.senado_bio_path(20, base=tmp_path)]
    assert json.loads(existing.read_text())["dados"] == "SENTINEL"


@responses.activate
def test_run_tolerates_individual_failures(tmp_path):
    responses.add(responses.GET, f"{BASE}/senador/10", json={}, status=500)
    responses.add(responses.GET, f"{BASE}/senador/20", json=_bio_response(20), status=200)

    client = SenadoClient(backoff_base=0, page_delay=0)
    written = bio.run(client=client, codigos=[10, 20], out_dir=tmp_path, delay=0)

    assert written == [paths.senado_bio_path(20, base=tmp_path)]
    assert not paths.senado_bio_path(10, base=tmp_path).exists()


def test_codigos_default_to_roster(tmp_path):
    lista.save_payload(
        lista.build_payload(57, [
            {"IdentificacaoParlamentar": {"CodigoParlamentar": "7"}},
        ]),
        paths.senado_lista_path(57, base=tmp_path),
    )

    with responses.RequestsMock() as rsps:
        rsps.add(rsps.GET, f"{BASE}/senador/7", json=_bio_response(7), status=200)
        client = SenadoClient(backoff_base=0, page_delay=0)
        written = bio.run(client=client, raw_base=tmp_path, out_dir=tmp_path, delay=0)

    assert paths.senado_bio_path(7, base=tmp_path) in written
