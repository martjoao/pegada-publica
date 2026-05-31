from pathlib import Path

from common import paths


def test_camara_deputados_path_uses_legislatura_filename():
    p = paths.camara_deputados_path(57, base=Path("/tmp/raw"))
    assert p == Path("/tmp/raw/camara/deputados/legislatura-57.json")


def test_camara_deputados_path_defaults_under_data_raw():
    p = paths.camara_deputados_path(56)
    parts = p.parts
    assert parts[-4:] == ("raw", "camara", "deputados", "legislatura-56.json")
