import pytest
import responses

from common.http_client import SenadoClient

BASE = "https://legis.senado.leg.br/dadosabertos"


@pytest.fixture
def client():
    # No delays/backoff so tests run fast.
    return SenadoClient(max_retries=3, backoff_base=0)


@responses.activate
def test_get_returns_parsed_json_payload(client):
    payload = {"FiliacaoParlamentar": {"Parlamentar": {"Codigo": "5672"}}}
    responses.add(responses.GET, f"{BASE}/senador/5672/filiacoes", json=payload, status=200)

    got = client.get("/senador/5672/filiacoes")

    assert got == payload
    # JSON requested via Accept header (Senado returns XML by default otherwise).
    assert responses.calls[0].request.headers["Accept"] == "application/json"


@responses.activate
def test_get_retries_transient_error_then_succeeds(client):
    responses.add(responses.GET, f"{BASE}/senador/lista/atual", status=503)
    responses.add(responses.GET, f"{BASE}/senador/lista/atual",
                  json={"ok": True}, status=200)

    got = client.get("/senador/lista/atual")

    assert got == {"ok": True}
    assert len(responses.calls) == 2


@responses.activate
def test_get_raises_after_exhausting_retries(client):
    for _ in range(4):
        responses.add(responses.GET, f"{BASE}/senador/lista/atual", status=500)

    with pytest.raises(Exception):
        client.get("/senador/lista/atual")


@responses.activate
def test_get_raises_on_client_error_without_retry(client):
    responses.add(responses.GET, f"{BASE}/senador/9999", status=404)

    with pytest.raises(Exception):
        client.get("/senador/9999")

    assert len(responses.calls) == 1
