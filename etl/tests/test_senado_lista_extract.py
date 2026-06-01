import json

import responses

from common.http_client import SenadoClient
from extract.senado import lista

BASE = "https://legis.senado.leg.br/dadosabertos"


def _roster_payload(*codigos):
    parlamentares = [
        {"IdentificacaoParlamentar": {"CodigoParlamentar": str(c), "NomeParlamentar": f"Sen {c}"}}
        for c in codigos
    ]
    return {
        "ListaParlamentarLegislatura": {
            "Parlamentares": {"Parlamentar": parlamentares}
        }
    }


def test_build_payload_wraps_records_with_meta():
    records = [{"IdentificacaoParlamentar": {"CodigoParlamentar": "5672"}}]
    payload = lista.build_payload(57, records, fetched_at="2026-06-01T00:00:00Z")

    assert payload["dados"] == records  # raw records untouched
    meta = payload["_meta"]
    assert meta["source"] == "senado-dados-abertos"
    assert meta["endpoint"] == "/senador/lista/legislatura/57"
    assert meta["legislatura"] == 57
    assert meta["record_count"] == 1
    assert meta["fetched_at"] == "2026-06-01T00:00:00Z"


@responses.activate
def test_run_fetches_each_legislatura_into_its_own_file(tmp_path):
    responses.add(responses.GET, f"{BASE}/senador/lista/legislatura/56",
                  json=_roster_payload(1, 2), status=200)
    responses.add(responses.GET, f"{BASE}/senador/lista/legislatura/57",
                  json=_roster_payload(2, 3), status=200)

    client = SenadoClient(backoff_base=0, page_delay=0)
    written = lista.run(client=client, legislaturas=(56, 57), out_dir=tmp_path)

    assert len(written) == 2
    f56 = json.loads((tmp_path / "senado" / "lista" / "legislatura-56.json").read_text())
    assert f56["_meta"]["legislatura"] == 56
    assert f56["_meta"]["record_count"] == 2
    assert f56["dados"][0]["IdentificacaoParlamentar"]["CodigoParlamentar"] == "1"


@responses.activate
def test_run_handles_single_parlamentar_as_dict(tmp_path):
    # Senado returns a single child as a dict, not a one-element list.
    single = {"ListaParlamentarLegislatura": {"Parlamentares": {
        "Parlamentar": {"IdentificacaoParlamentar": {"CodigoParlamentar": "9"}}}}}
    responses.add(responses.GET, f"{BASE}/senador/lista/legislatura/57",
                  json=single, status=200)

    client = SenadoClient(backoff_base=0, page_delay=0)
    lista.run(client=client, legislaturas=(57,), out_dir=tmp_path)

    f = json.loads((tmp_path / "senado" / "lista" / "legislatura-57.json").read_text())
    assert f["_meta"]["record_count"] == 1
    assert f["dados"][0]["IdentificacaoParlamentar"]["CodigoParlamentar"] == "9"


def test_senator_codes_from_roster_unions_and_dedups(tmp_path):
    lista.save_payload(lista.build_payload(56, [
        {"IdentificacaoParlamentar": {"CodigoParlamentar": "1"}},
        {"IdentificacaoParlamentar": {"CodigoParlamentar": "2"}},
    ]), tmp_path / "senado" / "lista" / "legislatura-56.json")
    lista.save_payload(lista.build_payload(57, [
        {"IdentificacaoParlamentar": {"CodigoParlamentar": "2"}},
        {"IdentificacaoParlamentar": {"CodigoParlamentar": "3"}},
    ]), tmp_path / "senado" / "lista" / "legislatura-57.json")

    codes = lista.senator_codes_from_roster(raw_base=tmp_path)

    assert codes == [1, 2, 3]  # unique, sorted, unioned across legislaturas
