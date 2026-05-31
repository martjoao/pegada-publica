import json

import responses

from common import paths
from common.http_client import CamaraClient
from common.jsonio import write_json_atomic
from extract.camara import historico

BASE = "https://dadosabertos.camara.leg.br/api/v2"


def test_build_payload_wraps_records_with_meta():
    records = [{"siglaPartido": "PP", "dataHora": "2023-02-01T00:00"}]
    payload = historico.build_payload(226708, records, fetched_at="2026-05-31T14:00:00Z")

    assert payload["dados"] == records
    meta = payload["_meta"]
    assert meta["source"] == "camara-dados-abertos"
    assert meta["endpoint"] == "/deputados/226708/historico"
    assert meta["deputy_id"] == 226708
    assert meta["record_count"] == 1
    assert meta["fetched_at"] == "2026-05-31T14:00:00Z"


def test_deputy_ids_from_roster_unions_and_dedups(tmp_path):
    # 56ª: ids 1, 2 (with a duplicate row for 2, as the real roster has)
    write_json_atomic(
        {"_meta": {}, "dados": [{"id": 1}, {"id": 2}, {"id": 2}]},
        paths.camara_deputados_path(56, base=tmp_path),
    )
    # 57ª: ids 2, 3
    write_json_atomic(
        {"_meta": {}, "dados": [{"id": 2}, {"id": 3}]},
        paths.camara_deputados_path(57, base=tmp_path),
    )

    ids = historico.deputy_ids_from_roster(raw_base=tmp_path)

    assert ids == [1, 2, 3]  # unique, sorted, unioned across legislaturas


@responses.activate
def test_run_writes_one_file_per_deputy(tmp_path):
    for dep_id in (10, 20):
        responses.add(
            responses.GET,
            f"{BASE}/deputados/{dep_id}/historico",
            json={"dados": [{"id": dep_id, "siglaPartido": "PT"}], "links": [{"rel": "self"}]},
            status=200,
        )

    client = CamaraClient(backoff_base=0, page_delay=0)
    written = historico.run(
        client=client, deputy_ids=[10, 20], out_dir=tmp_path, delay=0
    )

    assert len(written) == 2
    f10 = json.loads((tmp_path / "camara" / "historico" / "10.json").read_text())
    assert f10["_meta"]["deputy_id"] == 10
    assert f10["_meta"]["record_count"] == 1
    assert f10["dados"][0]["siglaPartido"] == "PT"


def test_run_skips_already_written_deputies(tmp_path):
    # a pre-existing landing file means a resumed run must not refetch it
    existing = paths.camara_historico_path(10, base=tmp_path)
    write_json_atomic({"_meta": {"deputy_id": 10}, "dados": ["SENTINEL"]}, existing)

    with responses.RequestsMock() as rsps:
        rsps.add(rsps.GET, f"{BASE}/deputados/20/historico",
                 json={"dados": [{"id": 20}], "links": []}, status=200)
        client = CamaraClient(backoff_base=0, page_delay=0)
        written = historico.run(client=client, deputy_ids=[10, 20],
                                out_dir=tmp_path, delay=0, skip_existing=True)

    # only 20 was fetched; 10 left untouched (no request fired for it)
    assert written == [paths.camara_historico_path(20, base=tmp_path)]
    assert json.loads(existing.read_text())["dados"] == ["SENTINEL"]


@responses.activate
def test_run_tolerates_individual_failures(tmp_path):
    responses.add(responses.GET, f"{BASE}/deputados/10/historico",
                  json={"erro": "boom"}, status=500)  # exhausts retries, raises internally
    responses.add(responses.GET, f"{BASE}/deputados/20/historico",
                  json={"dados": [{"id": 20}], "links": []}, status=200)

    client = CamaraClient(backoff_base=0, page_delay=0)
    written = historico.run(client=client, deputy_ids=[10, 20], out_dir=tmp_path, delay=0)

    # the 504-style failure on 10 must not abort the crawl; 20 still written
    assert written == [paths.camara_historico_path(20, base=tmp_path)]
    assert not (tmp_path / "camara" / "historico" / "10.json").exists()
