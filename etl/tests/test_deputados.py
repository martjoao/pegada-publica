import json

import responses

from common.http_client import CamaraClient
from extract.camara import deputados

BASE = "https://dadosabertos.camara.leg.br/api/v2"


def test_build_payload_wraps_records_with_meta():
    records = [{"id": 1, "nome": "Fulano"}, {"id": 2, "nome": "Beltrano"}]
    payload = deputados.build_payload(57, records, fetched_at="2026-05-31T14:00:00Z")

    assert payload["dados"] == records  # raw records untouched
    meta = payload["_meta"]
    assert meta["source"] == "camara-dados-abertos"
    assert meta["endpoint"] == "/deputados"
    assert meta["legislatura"] == 57
    assert meta["record_count"] == 2
    assert meta["fetched_at"] == "2026-05-31T14:00:00Z"


def test_save_payload_writes_json_roundtrip(tmp_path):
    payload = {"_meta": {"legislatura": 57}, "dados": [{"id": 1}]}
    out = tmp_path / "nested" / "legislatura-57.json"

    deputados.save_payload(payload, out)

    assert out.exists()
    assert json.loads(out.read_text(encoding="utf-8")) == payload
    # No leftover temp files in the directory.
    assert [p.name for p in out.parent.iterdir()] == ["legislatura-57.json"]


@responses.activate
def test_run_fetches_each_legislatura_into_its_own_file(tmp_path):
    for leg in (56, 57):
        responses.add(
            responses.GET,
            f"{BASE}/deputados",
            json={"dados": [{"id": leg, "idLegislatura": leg}], "links": []},
            status=200,
        )

    client = CamaraClient(backoff_base=0, page_delay=0)
    written = deputados.run(client=client, legislaturas=(56, 57), out_dir=tmp_path)

    assert len(written) == 2
    f56 = json.loads((tmp_path / "camara" / "deputados" / "legislatura-56.json").read_text())
    f57 = json.loads((tmp_path / "camara" / "deputados" / "legislatura-57.json").read_text())
    assert f56["_meta"]["legislatura"] == 56
    assert f56["_meta"]["record_count"] == 1
    assert f57["dados"][0]["idLegislatura"] == 57
