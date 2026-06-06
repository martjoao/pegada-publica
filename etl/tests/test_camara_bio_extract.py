import json

import responses

from common import paths
from common.http_client import CamaraClient
from common.jsonio import write_json_atomic
from extract.camara import bio

BASE = "https://dadosabertos.camara.leg.br/api/v2"


def test_build_payload_wraps_with_meta():
    data = {"id": 226708, "nome": "Test Deputy", "nomeCivil": "Test Name"}
    payload = bio.build_payload(226708, data, fetched_at="2026-06-06T12:00:00Z")

    assert payload["dados"] == data
    meta = payload["_meta"]
    assert meta["source"] == "camara-dados-abertos"
    assert meta["endpoint"] == "/deputados/226708"
    assert meta["deputy_id"] == 226708
    assert meta["fetched_at"] == "2026-06-06T12:00:00Z"


@responses.activate
def test_run_writes_one_file_per_deputy(tmp_path):
    for dep_id in (10, 20):
        responses.add(
            responses.GET,
            f"{BASE}/deputados/{dep_id}",
            json={"dados": {"id": dep_id, "nome": f"Deputy {dep_id}"}, "links": []},
            status=200,
        )

    client = CamaraClient(backoff_base=0, page_delay=0)
    written = bio.run(client=client, deputy_ids=[10, 20], out_dir=tmp_path, delay=0)

    assert len(written) == 2
    f10 = json.loads((tmp_path / "camara" / "bio" / "10.json").read_text())
    assert f10["_meta"]["deputy_id"] == 10
    assert f10["_meta"]["endpoint"] == "/deputados/10"
    assert f10["dados"]["id"] == 10
    assert f10["dados"]["nome"] == "Deputy 10"


def test_run_skips_already_written_deputies(tmp_path):
    existing = paths.camara_bio_path(10, base=tmp_path)
    write_json_atomic({"_meta": {"deputy_id": 10}, "dados": "SENTINEL"}, existing)

    with responses.RequestsMock() as rsps:
        rsps.add(rsps.GET, f"{BASE}/deputados/20",
                 json={"dados": {"id": 20}, "links": []}, status=200)
        client = CamaraClient(backoff_base=0, page_delay=0)
        written = bio.run(client=client, deputy_ids=[10, 20],
                          out_dir=tmp_path, delay=0, skip_existing=True)

    assert written == [paths.camara_bio_path(20, base=tmp_path)]
    assert json.loads(existing.read_text())["dados"] == "SENTINEL"


@responses.activate
def test_run_tolerates_individual_failures(tmp_path):
    responses.add(responses.GET, f"{BASE}/deputados/10", json={}, status=500)
    responses.add(responses.GET, f"{BASE}/deputados/20",
                  json={"dados": {"id": 20}, "links": []}, status=200)

    client = CamaraClient(backoff_base=0, page_delay=0)
    written = bio.run(client=client, deputy_ids=[10, 20], out_dir=tmp_path, delay=0)

    assert written == [paths.camara_bio_path(20, base=tmp_path)]
    assert not (tmp_path / "camara" / "bio" / "10.json").exists()
