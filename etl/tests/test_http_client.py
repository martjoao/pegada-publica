import pytest
import responses

from pegada_etl.http_client import CamaraClient

BASE = "https://dadosabertos.camara.leg.br/api/v2"


@pytest.fixture
def client():
    # No delays/backoff so tests run fast.
    return CamaraClient(max_retries=3, backoff_base=0, page_delay=0)


@responses.activate
def test_get_all_follows_pagination_and_merges_pages(client):
    page1 = {
        "dados": [{"id": 1}, {"id": 2}],
        "links": [
            {"rel": "self", "href": f"{BASE}/deputados?pagina=1"},
            {"rel": "next", "href": f"{BASE}/deputados?pagina=2"},
            {"rel": "last", "href": f"{BASE}/deputados?pagina=2"},
        ],
    }
    page2 = {
        "dados": [{"id": 3}],
        "links": [
            {"rel": "self", "href": f"{BASE}/deputados?pagina=2"},
            {"rel": "first", "href": f"{BASE}/deputados?pagina=1"},
        ],
    }
    responses.add(responses.GET, f"{BASE}/deputados", json=page1, status=200)
    responses.add(responses.GET, f"{BASE}/deputados", json=page2, status=200)

    records = client.get_all("/deputados", {"idLegislatura": 57})

    assert [r["id"] for r in records] == [1, 2, 3]
    assert len(responses.calls) == 2


@responses.activate
def test_get_all_stops_when_no_next_link(client):
    only_page = {
        "dados": [{"id": 1}],
        "links": [{"rel": "self", "href": f"{BASE}/deputados?pagina=1"}],
    }
    responses.add(responses.GET, f"{BASE}/deputados", json=only_page, status=200)

    records = client.get_all("/deputados")

    assert records == [{"id": 1}]
    assert len(responses.calls) == 1


@responses.activate
def test_get_all_retries_transient_error_then_succeeds(client):
    responses.add(responses.GET, f"{BASE}/deputados", status=503)
    responses.add(
        responses.GET,
        f"{BASE}/deputados",
        json={"dados": [{"id": 9}], "links": []},
        status=200,
    )

    records = client.get_all("/deputados")

    assert records == [{"id": 9}]
    assert len(responses.calls) == 2


@responses.activate
def test_get_all_raises_after_exhausting_retries(client):
    for _ in range(4):
        responses.add(responses.GET, f"{BASE}/deputados", status=500)

    with pytest.raises(Exception):
        client.get_all("/deputados")


@responses.activate
def test_get_all_raises_on_client_error_without_retry(client):
    responses.add(responses.GET, f"{BASE}/deputados", status=404)

    with pytest.raises(Exception):
        client.get_all("/deputados")

    assert len(responses.calls) == 1
