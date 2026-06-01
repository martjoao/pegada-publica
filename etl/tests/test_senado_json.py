from common.senado_json import as_list, unwrap


def test_as_list_wraps_single_dict():
    # Senado JSON returns a single child as a dict, not a one-element list.
    assert as_list({"a": 1}) == [{"a": 1}]


def test_as_list_passes_through_list():
    assert as_list([{"a": 1}, {"a": 2}]) == [{"a": 1}, {"a": 2}]


def test_as_list_none_is_empty():
    assert as_list(None) == []


def test_unwrap_digs_through_envelope():
    payload = {"FiliacaoParlamentar": {"Parlamentar": {"Codigo": "5672"}}}
    assert unwrap(payload, "FiliacaoParlamentar", "Parlamentar") == {"Codigo": "5672"}


def test_unwrap_missing_key_returns_default():
    assert unwrap({"A": {}}, "A", "B", "C", default=[]) == []
